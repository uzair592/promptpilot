"""Deterministic and provider-backed response evaluation."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm_provider import OpenAICompatibleProvider
from .models import Evaluation, EvaluationItem, Message, ModelRun
from .schemas import (
    EVALUATION_DIMENSIONS,
    LLMJudgeOutput,
    ResponseScore,
)
from .schemas import (
    EVALUATION_WEIGHTS as SCHEMA_EVALUATION_WEIGHTS,
)

RUBRIC_VERSION = "v1"
EVALUATION_WEIGHTS: dict[str, int] = SCHEMA_EVALUATION_WEIGHTS
TASK_INSTRUCTION_WORDS = {
    "answer",
    "describe",
    "explain",
    "give",
    "list",
    "please",
    "provide",
    "summarize",
    "tell",
    "write",
}


class EvaluationResult(BaseModel):
    score: ResponseScore
    weighted_score: float


class JudgeProvider(Protocol):
    name: str
    model: str

    def judge_response(
        self,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any] | None = None,
    ) -> LLMJudgeOutput: ...


def weighted_aggregate(score: ResponseScore) -> float:
    """Calculate the backend-owned weighted score for a response."""

    return round(
        sum(
            int(getattr(score, dimension)) * EVALUATION_WEIGHTS[dimension]
            for dimension in EVALUATION_DIMENSIONS
        )
        / 100,
        2,
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _text_values(values: list[dict[str, object] | str]) -> str:
    return " ".join(
        value if isinstance(value, str) else " ".join(str(item) for item in value.values())
        for value in values
    )


def _item_texts(values: list[dict[str, object] | str]) -> list[str]:
    return [
        value if isinstance(value, str) else " ".join(str(item) for item in value.values())
        for value in values
    ]


def _coverage(target: str, response_tokens: set[str]) -> tuple[int, int]:
    target_tokens = _tokens(target)
    if not target_tokens:
        return 0, 0
    return len(target_tokens & response_tokens), len(target_tokens)


def _is_negated(response: str, phrase: str) -> bool:
    """Detect an explicit negation of a supplied fact or instruction."""

    normalized = " ".join(phrase.lower().split())
    if not normalized:
        return False
    escaped = re.escape(normalized)
    return bool(
        re.search(
            rf"\b(?:not|no|never|without|isn't|aren't|doesn't|don't|can't|cannot)\b"
            rf"(?:\W+\w+){{0,3}}\W+{escaped}\b",
            response.lower(),
        )
    )


def _is_contradicted(response: str, phrase: str) -> bool:
    """Detect a response that explicitly negates a supplied fact."""

    fact = re.search(r"(.+?)\b(?:is|are|was|were|equals?)\b\s+(.+)", phrase.lower())
    if not fact:
        return _is_negated(response, phrase)
    prefix = " ".join(re.findall(r"[a-z0-9]+", fact.group(1)))
    value = " ".join(re.findall(r"[a-z0-9]+", fact.group(2)))
    if not prefix or not value:
        return _is_negated(response, phrase)
    return bool(
        re.search(
            rf"\b{re.escape(prefix)}\b(?:\W+\w+){{0,3}}\W+"
            rf"(?:not|no|never|isn't|aren't|wasn't|weren't)\b"
            rf"(?:\W+\w+){{0,2}}\W+{re.escape(value)}\b",
            response.lower(),
        )
    )


def _item_score(target: str, response: str, response_tokens: set[str]) -> int:
    matched, total = _coverage(target, response_tokens)
    if not total:
        return 100
    if _is_contradicted(response, target):
        return 0
    return round(100 * matched / total)


def _instruction_score(task: str, constraints: list[str], response: str) -> tuple[int, str]:
    """Score explicit constraints and output instructions independently of relevance."""

    instruction_items = list(constraints)
    lowered_task = task.lower()
    format_match = re.search(r"\b(?:json|yaml|xml)\b", lowered_task)
    if format_match:
        instruction_items.append("return " + format_match.group(0))
    output_match = re.search(
        r"\b(?:bullet points?|numbered list|table|one sentence|paragraph)\b",
        lowered_task,
    )
    if output_match:
        instruction_items.append(output_match.group(0))

    if not instruction_items:
        return 100, "No explicit output constraints were supplied."
    if not response.strip():
        return 0, "Response is empty and cannot follow output instructions."

    response_tokens = _tokens(response)
    scores: list[int] = []
    violated = 0
    for item in instruction_items:
        item_lower = item.lower()
        forbidden = re.search(
            r"\b(?:do not|don't|must not|never|avoid|without)\s+(.+)",
            item_lower,
        )
        if forbidden:
            forbidden_tokens = _tokens(forbidden.group(1))
            item_score = 0 if forbidden_tokens & response_tokens else 100
        elif "bullet point" in item_lower:
            item_score = 100 if len(re.findall(r"(?m)^\s*[-*]\s+", response)) >= 2 else 0
        elif "numbered list" in item_lower:
            item_score = 100 if len(re.findall(r"(?m)^\s*\d+[.)]\s+", response)) >= 2 else 0
        elif "table" in item_lower:
            item_score = 100 if "|" in response and re.search(r"\|?\s*:?-{3,}", response) else 0
        elif "one sentence" in item_lower:
            item_score = 100 if len(re.findall(r"[.!?](?:\s|$)", response.strip())) <= 1 else 0
        elif "concise" in item_lower:
            item_score = 100 if len(response.split()) <= 100 else 0
        else:
            item_score = _item_score(item, response, response_tokens)
        if re.search(r"\b(?:json|yaml|xml)\b", item_lower):
            try:
                json.loads(response)
                item_score = 100
            except json.JSONDecodeError:
                item_score = 0
        word_limit = re.search(
            r"\b(?:under|below|at most|no more than)\s+(\d+)\s+words?\b",
            item_lower,
        )
        if word_limit and len(response.split()) > int(word_limit.group(1)):
            item_score = 0
        if item_score == 0:
            violated += 1
        scores.append(item_score)
    score = round(sum(scores) / len(scores))
    return (
        score,
        f"Followed {len(scores) - violated} of {len(scores)} explicit output instructions.",
    )


def heuristic_score(
    task: str,
    response: str,
    requirements: list[dict[str, object] | str] | None = None,
    constraints: list[dict[str, object] | str] | None = None,
    context: list[dict[str, object] | str] | None = None,
) -> EvaluationResult:
    """Score observable response quality without claiming factual verification."""

    requirements = requirements or []
    constraints = constraints or []
    context = context or []
    task_tokens = _tokens(task) - TASK_INSTRUCTION_WORDS
    response_tokens = _tokens(response)
    task_overlap = task_tokens & response_tokens
    requirement_texts = _item_texts(requirements)
    constraint_texts = _item_texts(constraints)
    context_texts = _item_texts(context)

    relevance = (
        100 if not task_tokens else max(0, round(100 * len(task_overlap) / len(task_tokens)))
    )
    requirement_scores = [
        _item_score(item, response, response_tokens) for item in requirement_texts
    ]
    completeness = (
        round(sum(requirement_scores) / len(requirement_scores)) if requirement_scores else 100
    )
    instruction_following, instruction_explanation = _instruction_score(
        task, constraint_texts, response
    )
    context_scores = [_item_score(item, response, response_tokens) for item in context_texts]
    contextual_grounding = (
        round(sum(context_scores) / len(context_scores)) if context_scores else 100
    )

    stripped = response.strip()
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", stripped))
    clarity = 0 if not stripped else 100
    if stripped and len(stripped) > 12000:
        clarity -= 20
    if stripped and sentence_count == 0:
        clarity -= 10
    if stripped and len(_tokens(stripped)) < 3:
        clarity -= 20
    clarity = max(0, clarity)

    explanations = {
        "relevance": f"Matched {len(task_overlap)} of {len(task_tokens)} task terms.",
        "completeness": (
            "No explicit requirements were supplied."
            if not requirement_texts
            else f"Covered {sum(score == 100 for score in requirement_scores)} of "
            f"{len(requirement_scores)} explicit requirements."
        ),
        "instruction_following": instruction_explanation,
        "contextual_grounding": (
            "No additional context was supplied."
            if not context_texts
            else f"Grounded {sum(score == 100 for score in context_scores)} of "
            f"{len(context_scores)} supplied context items."
        ),
        "clarity": (
            "Response is empty."
            if not stripped
            else "Response has readable length and sentence structure."
        ),
    }
    score = ResponseScore(
        relevance=relevance,
        completeness=completeness,
        instruction_following=instruction_following,
        contextual_grounding=contextual_grounding,
        clarity=clarity,
        explanations=explanations,
        evidence={
            "task_terms": ", ".join(sorted(task_tokens)),
            "matched_task_terms": ", ".join(sorted(task_overlap)),
        },
    )
    return EvaluationResult(score=score, weighted_score=weighted_aggregate(score))


def _random_assignment() -> bool:
    return bool(secrets.randbelow(2))


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    return [str(item) for item in parsed] if isinstance(parsed, list) else [str(parsed)]


def _generation_parameters(run: ModelRun) -> dict[str, object] | None:
    """Read optional comparable generation parameters without treating usage as parameters."""

    for attribute in ("generation_parameters", "parameters"):
        value = getattr(run, attribute, None)
        if isinstance(value, dict):
            return value
    try:
        metadata = json.loads(run.usage_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict):
        return None
    for key in ("generation_parameters", "parameters"):
        value = metadata.get(key)
        if isinstance(value, dict):
            return value
    comparable_keys = {
        "temperature",
        "top_p",
        "max_tokens",
        "seed",
        "frequency_penalty",
        "presence_penalty",
        "stop",
    }
    comparable = {key: metadata[key] for key in comparable_keys if key in metadata}
    return comparable or None


def _strengths_and_weaknesses(result: EvaluationResult) -> tuple[list[str], list[str]]:
    strengths = [
        dimension.replace("_", " ")
        for dimension in EVALUATION_DIMENSIONS
        if getattr(result.score, dimension) >= 80
    ]
    weaknesses = [
        dimension.replace("_", " ")
        for dimension in EVALUATION_DIMENSIONS
        if getattr(result.score, dimension) < 60
    ]
    return strengths, weaknesses


class ResponseEvaluationService:
    def __init__(
        self,
        judge_provider: JudgeProvider | None = None,
        assignment: Callable[[], bool] | None = None,
    ) -> None:
        self.judge_provider = judge_provider or OpenAICompatibleProvider()
        self.assignment = assignment or _random_assignment

    def validate_run(self, db: Session, conversation_id: UUID, run_id: UUID) -> ModelRun:
        run = db.get(ModelRun, run_id)
        if run is None or run.conversation_id != conversation_id:
            raise ValueError("Model run does not belong to this conversation")
        if run.status != "succeeded" or not run.response_text:
            raise ValueError("Only succeeded model runs with a response can be evaluated")
        return run

    def validate_pair(
        self, db: Session, conversation_id: UUID, baseline_run_id: UUID, promptpilot_run_id: UUID
    ) -> tuple[ModelRun, ModelRun]:
        baseline = self.validate_run(db, conversation_id, baseline_run_id)
        promptpilot = self.validate_run(db, conversation_id, promptpilot_run_id)
        if baseline.execution_strategy != "baseline":
            raise ValueError("baseline_model_run_id must reference a baseline run")
        if promptpilot.execution_strategy != "promptpilot":
            raise ValueError("promptpilot_model_run_id must reference a PromptPilot run")
        if (
            baseline.project_id != promptpilot.project_id
            or baseline.source_message_id != promptpilot.source_message_id
        ):
            raise ValueError("Paired runs must share project and source task")
        if baseline.provider != promptpilot.provider or baseline.model != promptpilot.model:
            raise ValueError("Paired runs must use the same target provider and model")
        baseline_parameters = _generation_parameters(baseline)
        promptpilot_parameters = _generation_parameters(promptpilot)
        if (
            baseline_parameters is not None
            and promptpilot_parameters is not None
            and baseline_parameters != promptpilot_parameters
        ):
            raise ValueError("Paired runs must use comparable generation parameters")
        return baseline, promptpilot

    @staticmethod
    def _task_and_evidence(
        db: Session,
        run: ModelRun,
        task: str | None,
        original_task: str | None,
        requirements: list[dict[str, object] | str],
        constraints: list[dict[str, object] | str],
        context: list[dict[str, object] | str],
        other_run: ModelRun | None = None,
    ) -> tuple[str, dict[str, Any]]:
        source_message = db.get(Message, run.source_message_id)
        task_text = (
            original_task
            or task
            or (source_message.content if source_message else run.optimized_prompt)
        )
        promptpilot_prompt = (
            run.optimized_prompt if run.execution_strategy == "promptpilot" else None
        )
        baseline_prompt = run.optimized_prompt if run.execution_strategy == "baseline" else None
        if other_run:
            if other_run.execution_strategy == "baseline":
                baseline_prompt = other_run.optimized_prompt
            elif other_run.execution_strategy == "promptpilot":
                promptpilot_prompt = other_run.optimized_prompt
        evidence: dict[str, Any] = {
            "original_task": task_text,
            "baseline_executed_prompt": baseline_prompt,
            "optimized_prompt": promptpilot_prompt,
            "requirements": requirements,
            "constraints": constraints,
            "context": context,
        }
        return task_text, evidence

    def _judge(
        self, task: str, response_a: str, response_b: str, evidence: dict[str, Any]
    ) -> tuple[EvaluationResult, EvaluationResult]:
        judge_evidence = {
            "task": task,
            "requirements": evidence.get("requirements", []),
            "constraints": evidence.get("constraints", []),
            "context": evidence.get("context", []),
            "response_a": response_a,
            "response_b": response_b,
        }
        output = self.judge_provider.judge_response(
            task, response_a, response_b, evidence=judge_evidence
        )
        output = LLMJudgeOutput.model_validate(output)
        return (
            EvaluationResult(
                score=output.response_a, weighted_score=weighted_aggregate(output.response_a)
            ),
            EvaluationResult(
                score=output.response_b, weighted_score=weighted_aggregate(output.response_b)
            ),
        )

    def _results(
        self,
        method: str,
        task: str,
        response_a: str,
        response_b: str,
        evidence: dict[str, Any],
        requirements: list[dict[str, object] | str],
        constraints: list[dict[str, object] | str],
        context: list[dict[str, object] | str],
    ) -> tuple[EvaluationResult, EvaluationResult | None]:
        if method == "llm_judge":
            return self._judge(task, response_a, response_b, evidence)
        return (
            heuristic_score(task, response_a, requirements, constraints, context),
            heuristic_score(task, response_b, requirements, constraints, context)
            if response_b
            else None,
        )

    def evaluate_single(
        self,
        db: Session,
        conversation_id: UUID,
        run_id: UUID,
        task: str | None,
        method: str,
        original_task: str | None = None,
        requirements: list[dict[str, object] | str] | None = None,
        constraints: list[dict[str, object] | str] | None = None,
        context: list[dict[str, object] | str] | None = None,
    ) -> Evaluation:
        if method not in {"heuristic", "llm_judge"}:
            raise ValueError("Unsupported evaluation method")
        run = self.validate_run(db, conversation_id, run_id)
        requirements, constraints, context = requirements or [], constraints or [], context or []
        task_text, evidence = self._task_and_evidence(
            db, run, task, original_task, requirements, constraints, context
        )
        evidence["response_a"] = run.response_text or ""
        evidence["response_b"] = ""
        result, _ = self._results(
            method,
            task_text,
            run.response_text or "",
            "",
            evidence,
            requirements,
            constraints,
            context,
        )
        baseline_id = run.id if run.execution_strategy == "baseline" else None
        promptpilot_id = run.id if run.execution_strategy == "promptpilot" else None
        strengths, weaknesses = _strengths_and_weaknesses(result)
        evaluation = Evaluation(
            project_id=run.project_id,
            conversation_id=run.conversation_id,
            baseline_model_run_id=baseline_id,
            promptpilot_model_run_id=promptpilot_id,
            method=method,
            evaluator_provider=getattr(self.judge_provider, "name", "deterministic")
            if method == "llm_judge"
            else "deterministic",
            evaluator_model=getattr(self.judge_provider, "model", "heuristic-v1")
            if method == "llm_judge"
            else "heuristic-v1",
            rubric_version=RUBRIC_VERSION,
            baseline_score=result.weighted_score if baseline_id else None,
            promptpilot_score=result.weighted_score if promptpilot_id else None,
            baseline_strengths=json.dumps(strengths) if baseline_id else None,
            baseline_weaknesses=json.dumps(weaknesses) if baseline_id else None,
            promptpilot_strengths=json.dumps(strengths) if promptpilot_id else None,
            promptpilot_weaknesses=json.dumps(weaknesses) if promptpilot_id else None,
            comparison_summary="Single response evaluation.",
            metadata_json=json.dumps(evidence, default=str),
        )
        label = "baseline" if baseline_id else "promptpilot" if promptpilot_id else "single"
        for dimension in EVALUATION_DIMENSIONS:
            evaluation.items.append(
                EvaluationItem(
                    response_label=label,
                    dimension=dimension,
                    score=getattr(result.score, dimension),
                    explanation=result.score.explanations.get(
                        dimension, "No explanation was supplied by the evaluator."
                    ),
                )
            )
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)
        return evaluation

    def evaluate_pair(
        self,
        db: Session,
        conversation_id: UUID,
        baseline_run_id: UUID,
        promptpilot_run_id: UUID,
        task: str | None,
        method: str,
        original_task: str | None = None,
        requirements: list[dict[str, object] | str] | None = None,
        constraints: list[dict[str, object] | str] | None = None,
        context: list[dict[str, object] | str] | None = None,
    ) -> Evaluation:
        if method not in {"heuristic", "llm_judge"}:
            raise ValueError("Unsupported evaluation method")
        baseline, promptpilot = self.validate_pair(
            db, conversation_id, baseline_run_id, promptpilot_run_id
        )
        requirements, constraints, context = requirements or [], constraints or [], context or []
        task_text, evidence = self._task_and_evidence(
            db, baseline, task, original_task, requirements, constraints, context, promptpilot
        )
        evidence["response_a"] = baseline.response_text or ""
        evidence["response_b"] = promptpilot.response_text or ""
        if method == "llm_judge":
            first, second = (
                (baseline, promptpilot) if self.assignment() else (promptpilot, baseline)
            )
            first_result, second_result = self._judge(
                task_text, first.response_text or "", second.response_text or "", evidence
            )
            results = {first.id: first_result, second.id: second_result}
        else:
            results = {
                baseline.id: heuristic_score(
                    task_text, baseline.response_text or "", requirements, constraints, context
                ),
                promptpilot.id: heuristic_score(
                    task_text, promptpilot.response_text or "", requirements, constraints, context
                ),
            }
        baseline_result = results[baseline.id]
        promptpilot_result = results[promptpilot.id]
        delta = round(promptpilot_result.weighted_score - baseline_result.weighted_score, 2)
        winner = "promptpilot" if delta > 0 else "baseline" if delta < 0 else "tie"
        baseline_strengths, baseline_weaknesses = _strengths_and_weaknesses(baseline_result)
        promptpilot_strengths, promptpilot_weaknesses = _strengths_and_weaknesses(
            promptpilot_result
        )
        evaluation = Evaluation(
            project_id=baseline.project_id,
            conversation_id=baseline.conversation_id,
            baseline_model_run_id=baseline.id,
            promptpilot_model_run_id=promptpilot.id,
            method=method,
            evaluator_provider=getattr(self.judge_provider, "name", "deterministic")
            if method == "llm_judge"
            else "deterministic",
            evaluator_model=getattr(self.judge_provider, "model", "heuristic-v1")
            if method == "llm_judge"
            else "heuristic-v1",
            rubric_version=RUBRIC_VERSION,
            baseline_score=baseline_result.weighted_score,
            promptpilot_score=promptpilot_result.weighted_score,
            overall_delta=delta,
            winner=winner,
            comparison_summary=(
                f"{winner.capitalize()} scored {abs(delta):.2f} points "
                f"{'higher' if delta else 'the same'} overall."
            ),
            baseline_strengths=json.dumps(baseline_strengths),
            baseline_weaknesses=json.dumps(baseline_weaknesses),
            promptpilot_strengths=json.dumps(promptpilot_strengths),
            promptpilot_weaknesses=json.dumps(promptpilot_weaknesses),
            metadata_json=json.dumps(evidence, default=str),
        )
        for label, result in (("baseline", baseline_result), ("promptpilot", promptpilot_result)):
            for dimension in EVALUATION_DIMENSIONS:
                evaluation.items.append(
                    EvaluationItem(
                        response_label=label,
                        dimension=dimension,
                        score=getattr(result.score, dimension),
                        explanation=result.score.explanations.get(
                            dimension, "No explanation was supplied by the evaluator."
                        ),
                    )
                )
        db.add(evaluation)
        db.commit()
        db.refresh(evaluation)
        return evaluation


def list_evaluations(db: Session, conversation_id: UUID) -> list[Evaluation]:
    return list(
        db.scalars(
            select(Evaluation)
            .where(Evaluation.conversation_id == conversation_id)
            .order_by(Evaluation.created_at.desc())
        ).all()
    )


def evaluation_metadata(evaluation: Evaluation) -> dict[str, object]:
    try:
        metadata = json.loads(evaluation.metadata_json)
    except json.JSONDecodeError:
        metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def evaluation_lists(evaluation: Evaluation) -> dict[str, list[str]]:
    return {
        "baseline_strengths": _json_list(evaluation.baseline_strengths),
        "baseline_weaknesses": _json_list(evaluation.baseline_weaknesses),
        "promptpilot_strengths": _json_list(evaluation.promptpilot_strengths),
        "promptpilot_weaknesses": _json_list(evaluation.promptpilot_weaknesses),
    }
