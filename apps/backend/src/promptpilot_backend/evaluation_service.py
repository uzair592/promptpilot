"""Deterministic and provider-backed response evaluation."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable
from typing import Any, Protocol, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm_provider import OpenAICompatibleProvider
from .models import Evaluation, EvaluationItem, Message, ModelRun, PromptVersion
from .schemas import (
    EVALUATION_DIMENSIONS,
    LLMJudgeOutput,
    ResponseScore,
)
from .schemas import (
    EVALUATION_WEIGHTS as SCHEMA_EVALUATION_WEIGHTS,
)

RUBRIC_VERSION = "response-evaluation-v1"
EVALUATION_WEIGHTS: dict[str, int] = SCHEMA_EVALUATION_WEIGHTS


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
            cast(int, getattr(score, dimension)) * EVALUATION_WEIGHTS[dimension] / 100
            for dimension in EVALUATION_DIMENSIONS
        ),
        2,
    )


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _text_values(values: list[dict[str, object] | str]) -> str:
    return " ".join(
        value if isinstance(value, str) else " ".join(str(item) for item in value.values())
        for value in values
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
    task_tokens = _tokens(task)
    response_tokens = _tokens(response)
    task_overlap = task_tokens & response_tokens
    requirement_tokens = _tokens(_text_values(requirements))
    constraint_tokens = _tokens(_text_values(constraints))
    context_tokens = _tokens(_text_values(context))

    relevance = (
        100
        if not task_tokens
        else max(0, round(100 * len(task_overlap) / len(task_tokens)))
    )
    completeness_target = requirement_tokens or task_tokens
    completeness = (
        100
        if not completeness_target
        else max(
            0,
            round(100 * len(completeness_target & response_tokens) / len(completeness_target)),
        )
    )
    instruction_target = constraint_tokens | {
        token
        for token in task_tokens
        if token not in {"please", "write", "provide", "explain", "describe", "tell"}
    }
    instruction_following = (
        100
        if not instruction_target
        else max(
            0,
            round(100 * len(instruction_target & response_tokens) / len(instruction_target)),
        )
    )
    contextual_grounding = (
        100
        if not context_tokens
        else max(0, round(100 * len(context_tokens & response_tokens) / len(context_tokens)))
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
            f"Covered {len(completeness_target & response_tokens)} of "
            f"{len(completeness_target)} requirement terms."
        ),
        "instruction_following": (
            f"Covered {len(instruction_target & response_tokens)} of "
            f"{len(instruction_target)} instruction terms."
        ),
        "contextual_grounding": (
            "No additional context was supplied."
            if not context_tokens
            else (
                f"Matched {len(context_tokens & response_tokens)} of "
                f"{len(context_tokens)} context terms."
            )
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
        task_text = original_task or task or (
            source_message.content if source_message else run.optimized_prompt
        )
        version_metadata: dict[str, Any] = {}
        if run.prompt_version_id:
            version = db.get(PromptVersion, run.prompt_version_id)
            if version:
                try:
                    version_metadata = json.loads(version.metadata_json)
                except json.JSONDecodeError:
                    version_metadata = {}
        evidence: dict[str, Any] = {
            "original_task": task_text,
            "baseline_executed_prompt": run.optimized_prompt
            if run.execution_strategy == "baseline"
            else (
                other_run.optimized_prompt
                if other_run and other_run.execution_strategy == "baseline"
                else None
            ),
            "optimized_prompt": run.optimized_prompt
            if run.execution_strategy == "promptpilot"
            else (
                other_run.optimized_prompt
                if other_run and other_run.execution_strategy == "promptpilot"
                else None
            ),
            "baseline_response": run.response_text
            if run.execution_strategy == "baseline"
            else (
                other_run.response_text
                if other_run and other_run.execution_strategy == "baseline"
                else None
            ),
            "promptpilot_response": run.response_text
            if run.execution_strategy == "promptpilot"
            else (
                other_run.response_text
                if other_run and other_run.execution_strategy == "promptpilot"
                else None
            ),
            "requirements": requirements,
            "constraints": constraints,
            "context": context,
            "prompt_version_metadata": version_metadata,
        }
        return task_text, evidence

    def _judge(
        self, task: str, response_a: str, response_b: str, evidence: dict[str, Any]
    ) -> tuple[EvaluationResult, EvaluationResult]:
        try:
            output = self.judge_provider.judge_response(
                task, response_a, response_b, evidence=evidence
            )
        except TypeError:
            # Keep the provider abstraction compatible with small test providers.
            output = self.judge_provider.judge_response(task, response_a, response_b)
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
