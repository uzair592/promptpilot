"""Offline validation and typed inputs for future production-pipeline benchmarks.

This module does not execute a benchmark or call a provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .analyzer_service import DIMENSIONS
from .benchmark import BenchmarkDataset, dataset_sha256, load_dataset
from .document_service import ALLOWED_TYPES

Sha256 = str
SourceType = Literal[
    "dataset_original",
    "synthetic_test",
    "user_supplied_project_fact",
    "user_supplied_answer",
    "frozen_document",
    "evaluation_only",
]


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_hash(actual: str, declared: str, label: str) -> None:
    if actual != declared:
        raise ValueError(f"{label} content_sha256 does not match content")


def _normalized_key(dimension: str, question_target: str) -> tuple[str, str]:
    return (dimension.strip().casefold(), " ".join(question_target.split()).casefold())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    source_type: SourceType
    source_id: str = Field(min_length=1)
    description: str = Field(min_length=1)


class TextSource(StrictModel):
    fixture_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    source_type: SourceType
    content: str = Field(min_length=1)
    content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: Provenance

    @model_validator(mode="after")
    def validate_content(self) -> TextSource:
        _require_hash(text_sha256(self.content), self.content_sha256, self.fixture_id)
        if self.provenance.source_type != self.source_type:
            raise ValueError(f"{self.fixture_id} provenance source_type differs from source_type")
        return self


class OriginalTask(TextSource):
    source_type: Literal["dataset_original"] = "dataset_original"


class ProjectFact(TextSource):
    source_type: Literal["synthetic_test", "user_supplied_project_fact"]


class GapMatchKey(StrictModel):
    dimension: str = Field(min_length=1)
    question_target: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_key(self) -> GapMatchKey:
        if self.dimension not in DIMENSIONS or not self.question_target.strip():
            raise ValueError("Gap key requires a known dimension and nonblank question_target")
        return self

    def canonical(self) -> tuple[str, str]:
        return _normalized_key(self.dimension, self.question_target)


class ClarificationAnswer(TextSource):
    source_type: Literal["synthetic_test", "user_supplied_answer"]
    gap_key: GapMatchKey


class FrozenDocument(StrictModel):
    fixture_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    source_type: Literal["frozen_document"] = "frozen_document"
    path: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: Provenance

    @model_validator(mode="after")
    def validate_document(self) -> FrozenDocument:
        if self.provenance.source_type != self.source_type:
            raise ValueError(f"{self.fixture_id} provenance source_type differs from source_type")
        if Path(self.filename).name != self.filename:
            raise ValueError("Document filename must be a basename")
        if ALLOWED_TYPES.get(Path(self.filename).suffix.lower()) != self.media_type:
            raise ValueError("Document media_type does not match a supported filename extension")
        return self


class EvaluationCriterion(TextSource):
    source_type: Literal["evaluation_only"] = "evaluation_only"


class Review(StrictModel):
    status: Literal["synthetic", "pending", "human_approved"]
    reviewer_id: str | None = None
    reviewed_at: datetime | None = None


class FixtureManifest(StrictModel):
    schema_version: Literal["v1"]
    fixture_id: str = Field(min_length=1)
    fixture_kind: Literal["synthetic_offline_test", "experimental_candidate"]
    review: Review
    dataset_name: str = Field(min_length=1)
    dataset_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str = Field(min_length=1)
    original_task: OriginalTask
    project_facts: list[ProjectFact] = Field(default_factory=list)
    clarification_answers: list[ClarificationAnswer] = Field(default_factory=list)
    frozen_documents: list[FrozenDocument] = Field(default_factory=list)
    evaluation_only: list[EvaluationCriterion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> FixtureManifest:
        if self.fixture_kind == "synthetic_offline_test":
            if (
                self.review.status != "synthetic"
                or self.review.reviewer_id
                or self.review.reviewed_at
            ):
                raise ValueError("Synthetic fixtures cannot claim human review")
        elif self.review.status == "synthetic":
            raise ValueError("Experimental candidates cannot have synthetic review status")
        if self.review.status == "human_approved":
            if not self.review.reviewer_id or not self.review.reviewed_at:
                raise ValueError("Human approval requires reviewer_id and reviewed_at")
        elif self.review.reviewer_id or self.review.reviewed_at:
            raise ValueError("Reviewer fields require human_approved status")

        sources: list[TextSource | FrozenDocument] = [
            self.original_task,
            *self.project_facts,
            *self.clarification_answers,
            *self.frozen_documents,
            *self.evaluation_only,
        ]
        ids = [source.fixture_id for source in sources]
        if len(ids) != len(set(ids)):
            raise ValueError("Fixture source IDs must be unique")
        if any(source.task_id != self.task_id for source in sources):
            raise ValueError("All sources must reference the manifest task_id")
        if self.fixture_kind == "synthetic_offline_test":
            if any(
                source.source_type
                not in {"dataset_original", "synthetic_test", "frozen_document", "evaluation_only"}
                for source in sources
            ):
                raise ValueError("Synthetic fixtures cannot claim user-supplied sources")
        elif any(source.source_type == "synthetic_test" for source in sources):
            raise ValueError("Experimental candidates cannot contain synthetic test sources")
        keys = [answer.gap_key.canonical() for answer in self.clarification_answers]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate or ambiguous clarification gap keys")
        return self

    @property
    def live_eligible(self) -> bool:
        return (
            self.fixture_kind == "experimental_candidate" and self.review.status == "human_approved"
        )

    def answer_for_gap(self, gap: GapMatchKey) -> ClarificationAnswer | None:
        """Return only an exact reviewed key match; unknown gaps remain unanswered."""

        matches = [
            a for a in self.clarification_answers if a.gap_key.canonical() == gap.canonical()
        ]
        if len(matches) > 1:
            raise ValueError("Ambiguous clarification gap key")
        return matches[0] if matches else None


def manifest_sha256(manifest: FixtureManifest) -> str:
    """Stable identity for the validated declaration, including source checksums."""

    canonical = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class FrozenDocumentInput(StrictModel):
    fixture_id: str
    filename: str
    media_type: str
    content: bytes
    content_sha256: str
    provenance: Provenance


class GenerationFixtureInputs(StrictModel):
    original_task: OriginalTask
    project_facts: list[ProjectFact]
    clarification_answers: list[ClarificationAnswer]
    frozen_documents: list[FrozenDocumentInput]


def _read_document(document: FrozenDocument, manifest_path: Path) -> bytes:
    base = manifest_path.resolve().parent
    relative = Path(document.path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{document.fixture_id} path must stay within the manifest directory")
    resolved = (base / relative).resolve()
    if not resolved.is_relative_to(base):
        raise ValueError(f"{document.fixture_id} path escapes the manifest directory")
    content = resolved.read_bytes()
    _require_hash(hashlib.sha256(content).hexdigest(), document.content_sha256, document.fixture_id)
    return content


def validate_manifest(
    manifest: FixtureManifest, dataset: BenchmarkDataset, manifest_path: Path
) -> None:
    if manifest.dataset_name != dataset.name or manifest.dataset_sha256 != dataset_sha256(dataset):
        raise ValueError("Manifest dataset identity/hash differs from the source dataset")
    try:
        task = dataset.task(manifest.task_id)
    except KeyError as exc:
        raise ValueError("Manifest references an unknown task_id") from exc
    if manifest.original_task.content != task.task_text:
        raise ValueError("Original-task content differs from the dataset task_text")
    for document in manifest.frozen_documents:
        _read_document(document, manifest_path)


def load_fixture_manifest(path: str | Path, dataset: BenchmarkDataset) -> FixtureManifest:
    manifest_path = Path(path)
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = FixtureManifest.model_validate(json.load(handle))
    validate_manifest(manifest, dataset, manifest_path)
    return manifest


def generation_inputs(
    manifest: FixtureManifest, manifest_path: str | Path
) -> GenerationFixtureInputs:
    """Explicit allowlist: evaluation_only cannot appear in generation inputs."""

    return GenerationFixtureInputs(
        original_task=manifest.original_task,
        project_facts=manifest.project_facts,
        clarification_answers=manifest.clarification_answers,
        frozen_documents=[
            FrozenDocumentInput(
                fixture_id=doc.fixture_id,
                filename=doc.filename,
                media_type=doc.media_type,
                content=_read_document(doc, Path(manifest_path)),
                content_sha256=doc.content_sha256,
                provenance=doc.provenance,
            )
            for doc in manifest.frozen_documents
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a production benchmark fixture offline")
    parser.add_argument("validate", choices=["validate"])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = load_fixture_manifest(args.manifest, load_dataset(args.dataset))
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Fixture validation failed: {exc}\n")
    print(f"Valid fixture: {manifest.fixture_id}; live_eligible={manifest.live_eligible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
