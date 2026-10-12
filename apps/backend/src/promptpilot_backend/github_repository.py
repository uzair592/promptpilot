"""Explicit, owner-controlled publication of reviewed agent files to GitHub."""

import json
from base64 import b64decode
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AgentTask, ProjectRepository
from .orchestration_service import _cipher
from .schemas import ProjectRepositoryRequest, ProjectRepositoryResponse, PublishTaskResponse


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url="https://api.github.com",
        timeout=get_settings().llm_timeout,
        follow_redirects=False,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )


def _json(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("Unexpected GitHub response")
    return value


def repository_response(repository: ProjectRepository) -> ProjectRepositoryResponse:
    return ProjectRepositoryResponse(
        owner=repository.owner,
        repo=repository.repo,
        default_branch=repository.default_branch,
        url=f"https://github.com/{repository.owner}/{repository.repo}",
    )


def connect_repository(
    db: Session, project_id: UUID, payload: ProjectRepositoryRequest
) -> ProjectRepository:
    owner, repo, token = payload.owner, payload.repo, payload.token.strip()
    if not token:
        raise HTTPException(status_code=422, detail="GitHub token is required")
    path = f"/repos/{owner}/{repo}"
    try:
        with _client(token) as client:
            details = _json(client, "GET", path)
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=502, detail="Could not verify the GitHub repository"
        ) from error
    if (
        details.get("full_name", "").casefold() != f"{owner}/{repo}".casefold()
        or not details.get("permissions", {}).get("push")
        or not isinstance(details.get("default_branch"), str)
    ):
        raise HTTPException(
            status_code=422, detail="Token must have write access to the selected repository"
        )
    repository = db.get(ProjectRepository, project_id)
    if repository is None:
        repository = ProjectRepository(project_id=project_id)
        db.add(repository)
    repository.owner = owner
    repository.repo = repo
    repository.default_branch = details["default_branch"]
    repository.encrypted_token = _cipher().encrypt(token.encode()).decode()
    db.commit()
    db.refresh(repository)
    return repository


def reviewed_files(output: str | None) -> list[dict[str, str]]:
    try:
        payload = json.loads(output or "")
    except (TypeError, ValueError) as error:
        raise HTTPException(
            status_code=422, detail="Agent output must be a JSON object with a files array"
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise HTTPException(status_code=422, detail="Agent output needs a files array")
    values = payload["files"]
    if not 1 <= len(values) <= 10:
        raise HTTPException(status_code=422, detail="Publish between 1 and 10 files")
    files: list[dict[str, str]] = []
    paths: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail="Each file needs a path and content")
        path, content = item.get("path"), item.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise HTTPException(status_code=422, detail="Each file needs text path and content")
        parts = PurePosixPath(path).parts
        if (
            not path
            or len(path) > 240
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(char) < 32 for char in path)
            or parts[0] in {".git", ".github"}
            or path in paths
            or len(content.encode()) > 100_000
        ):
            raise HTTPException(status_code=422, detail="Agent file path or size is not allowed")
        paths.add(path)
        files.append({"path": path, "mode": "100644", "type": "blob", "content": content})
    return files


def repository_context(repository: ProjectRepository, role: str) -> str:
    """Bounded source snapshot; dependent PR drafts come from task handoffs."""
    token = _cipher().decrypt(repository.encrypted_token.encode()).decode()
    prefix = f"/repos/{repository.owner}/{repository.repo}"
    branch = quote(repository.default_branch, safe="")
    try:
        with _client(token) as client:
            tree = _json(client, "GET", f"{prefix}/git/trees/{branch}", params={"recursive": 1})
            entries = tree.get("tree", [])
            if not isinstance(entries, list):
                return ""
            selected = []
            for item in entries:
                if not isinstance(item, dict) or item.get("type") != "blob":
                    continue
                path = item.get("path", "")
                size = item.get("size", 0)
                if not isinstance(path, str) or not isinstance(size, int) or size > 8000:
                    continue
                allowed = (
                    path.lower() in {"readme.md", "package.json", "pyproject.toml"}
                    or role == "frontend" and path.startswith("apps/frontend/")
                    or role in {"backend", "api", "tester"} and path.startswith("apps/backend/")
                )
                if allowed and path.endswith((".md", ".json", ".py", ".ts", ".tsx", ".toml")):
                    selected.append(item)
            selected.sort(key=lambda item: (item["path"].count("/"), item["path"]))
            snippets = []
            total = 0
            for item in selected[:10]:
                blob = _json(client, "GET", f"{prefix}/git/blobs/{item['sha']}")
                if blob.get("encoding") != "base64":
                    continue
                content = b64decode(blob["content"]).decode("utf-8", errors="replace")
                if total + len(content) > 35000:
                    break
                snippets.append(f"File: {item['path']}\n{content}")
                total += len(content)
            return "\n\n".join(snippets)
    except (httpx.HTTPError, KeyError, ValueError):
        return ""


def publish_task(
    db: Session, task: AgentTask, repository: ProjectRepository
) -> PublishTaskResponse:
    if task.pull_request_url:
        return PublishTaskResponse(
            pull_request_url=task.pull_request_url,
            branch=f"promptpilot/task-{task.id}",
        )
    if task.role not in {"frontend", "backend", "api"} or task.status != "review":
        raise HTTPException(status_code=409, detail="A reviewed code task is required")
    files = reviewed_files(task.output_text)
    branch = f"promptpilot/task-{task.id}"
    prefix = f"/repos/{repository.owner}/{repository.repo}"
    token = _cipher().decrypt(repository.encrypted_token.encode()).decode()
    try:
        with _client(token) as client:
            existing = client.get(f"{prefix}/git/ref/heads/{branch}")
            if existing.status_code == 200:
                # A previous attempt can leave a branch if PR creation failed.
                raise HTTPException(status_code=409, detail="Task branch already exists on GitHub")
            if existing.status_code != 404:
                existing.raise_for_status()
            default = quote(repository.default_branch, safe="")
            reference = _json(client, "GET", f"{prefix}/git/ref/heads/{default}")
            base_sha = reference["object"]["sha"]
            parent = _json(client, "GET", f"{prefix}/git/commits/{base_sha}")
            tree = _json(
                client, "POST", f"{prefix}/git/trees",
                json={"base_tree": parent["tree"]["sha"], "tree": files},
            )
            commit = _json(
                client, "POST", f"{prefix}/git/commits",
                json={
                    "message": f"PromptPilot: {task.title[:120]}",
                    "tree": tree["sha"], "parents": [base_sha],
                },
            )
            _json(client, "POST", f"{prefix}/git/refs", json={
                "ref": f"refs/heads/{branch}", "sha": commit["sha"],
            })
            pull = _json(client, "POST", f"{prefix}/pulls", json={
                "title": f"PromptPilot: {task.title[:120]}",
                "head": branch, "base": repository.default_branch,
                "body": (
                    f"Draft from the {task.role} specialist. Review and run tests "
                    f"before merging.\n\nTask: {task.description[:1500]}"
                ),
                "draft": True,
            })
    except HTTPException:
        raise
    except (httpx.HTTPError, KeyError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail="GitHub publication failed; inspect the task branch before retrying",
        ) from error
    task.pull_request_url = pull["html_url"]
    db.commit()
    return PublishTaskResponse(pull_request_url=task.pull_request_url, branch=branch)
