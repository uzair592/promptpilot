"""Deterministic result aggregation and offline dry-run workload planning.

Aggregation is descriptive only. It computes means, counts, and deltas over
frozen strata. It performs no significance testing, applies no post-hoc
filtering, deletes no unfavourable result, and makes no superiority claim.

The primary frozen strata are exactly ``overall`` and ``task_category``. Any
additional breakdown is labelled exploratory so it cannot be mistaken for a
primary confirmatory analysis.
"""

from __future__ import annotations

from collections.abc import Sequence
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .benchmark_call_ledger import ProviderRole
from .benchmark_experiment_results import ExperimentUnit
from .production_benchmark_protocol import RoleCallBudget

StratumName = Literal["overall", "task_category", "repetition", "condition_order"]
AnalysisTier = Literal["primary", "exploratory"]
PRIMARY_STRATA: tuple[StratumName, ...] = ("overall", "task_category")
EXPLORATORY_STRATA: tuple[StratumName, ...] = ("repetition", "condition_order")


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StratumResult(StrictAnalysisModel):
    stratum: StratumName
    tier: AnalysisTier
    key: str
    unit_count: int
    complete_pair_count: int
    incomplete_unit_count: int
    baseline_mean: float | None
    promptpilot_mean: float | None
    mean_delta: float | None


class AnalysisReport(StrictAnalysisModel):
    analysis_version: Literal["v1"] = "v1"
    protocol_sha256: str
    dataset_sha256: str
    total_units: int
    complete_pairs: int
    primary: tuple[StratumResult, ...]
    exploratory: tuple[StratumResult, ...]
    excluded_from_scoring: int
    significance_testing_performed: Literal[False] = False
    superiority_claim: Literal[False] = False


def _mean(values: Sequence[float]) -> float | None:
    return round(fmean(values), 4) if values else None


def _aggregate(
    units: Sequence[ExperimentUnit], stratum: StratumName, tier: AnalysisTier, key: str
) -> StratumResult:
    complete = [unit for unit in units if unit.is_complete_pair]
    baseline = [
        unit.evaluation.baseline_score
        for unit in complete
        if unit.evaluation is not None and unit.evaluation.baseline_score is not None
    ]
    promptpilot = [
        unit.evaluation.promptpilot_score
        for unit in complete
        if unit.evaluation is not None and unit.evaluation.promptpilot_score is not None
    ]
    deltas = [
        unit.evaluation.overall_delta
        for unit in complete
        if unit.evaluation is not None and unit.evaluation.overall_delta is not None
    ]
    return StratumResult(
        stratum=stratum,
        tier=tier,
        key=key,
        unit_count=len(units),
        complete_pair_count=len(complete),
        incomplete_unit_count=len(units) - len(complete),
        baseline_mean=_mean(baseline),
        promptpilot_mean=_mean(promptpilot),
        mean_delta=_mean(deltas),
    )


def aggregate_units(
    units: Sequence[ExperimentUnit], *, protocol_sha256: str, dataset_sha256: str
) -> AnalysisReport:
    """Aggregate complete pairs only, keeping every incomplete unit visible."""

    primary: list[StratumResult] = [_aggregate(units, "overall", "primary", "all")]
    categories = sorted({unit.task_category for unit in units})
    primary.extend(
        _aggregate(
            [unit for unit in units if unit.task_category == category],
            "task_category",
            "primary",
            category,
        )
        for category in categories
    )
    exploratory: list[StratumResult] = []
    for repetition in sorted({unit.repetition for unit in units}):
        exploratory.append(
            _aggregate(
                [unit for unit in units if unit.repetition == repetition],
                "repetition",
                "exploratory",
                str(repetition),
            )
        )
    for order in sorted({",".join(unit.condition_order) for unit in units}):
        exploratory.append(
            _aggregate(
                [
                    unit
                    for unit in units
                    if ",".join(unit.condition_order) == order
                ],
                "condition_order",
                "exploratory",
                order,
            )
        )
    return AnalysisReport(
        protocol_sha256=protocol_sha256,
        dataset_sha256=dataset_sha256,
        total_units=len(units),
        complete_pairs=sum(1 for unit in units if unit.is_complete_pair),
        primary=tuple(primary),
        exploratory=tuple(exploratory),
        excluded_from_scoring=sum(1 for unit in units if not unit.is_complete_pair),
    )


class DryRunUnit(StrictAnalysisModel):
    unit_id: str
    task_id: str
    repetition: int
    condition_order: tuple[str, ...]


class DryRunPlan(StrictAnalysisModel):
    """The exact simulated workload for the frozen study shape."""

    plan_version: Literal["v1"] = "v1"
    execution_mode: Literal["offline_dry_run"] = "offline_dry_run"
    task_count: int
    repetitions: int
    question_cap: int
    unit_count: int
    judge_enabled: bool
    units: tuple[DryRunUnit, ...]
    calls_by_role: RoleCallBudget
    total_calls: int
    network_calls: Literal[0] = 0
    cost_estimate: Literal[0] = 0

    def assert_matches_ceiling(self, by_role: RoleCallBudget, total: int) -> None:
        if self.calls_by_role != by_role or self.total_calls != total:
            raise ValueError("Dry-run plan does not match the frozen call ceiling")


def plan_dry_run(
    *,
    task_ids: Sequence[str],
    repetitions: int,
    question_cap: int,
    judge_enabled: bool,
) -> DryRunPlan:
    """Compute the deterministic offline workload. Performs no execution."""

    if not task_ids:
        raise ValueError("A dry run requires at least one task")
    if repetitions < 1:
        raise ValueError("Repetitions must be positive")
    units = tuple(
        DryRunUnit(
            unit_id=f"{task_id}#r{repetition}",
            task_id=task_id,
            repetition=repetition,
            condition_order=(
                ("baseline", "promptpilot")
                if repetition % 2
                else ("promptpilot", "baseline")
            ),
        )
        for task_id in task_ids
        for repetition in range(1, repetitions + 1)
    )
    unit_count = len(units)
    by_role = RoleCallBudget(
        analysis=unit_count,
        question_generation=unit_count * question_cap,
        prompt_generation=unit_count,
        target_execution=unit_count * 2,
        judge=unit_count if judge_enabled else 0,
    )
    return DryRunPlan(
        task_count=len(task_ids),
        repetitions=repetitions,
        question_cap=question_cap,
        unit_count=unit_count,
        judge_enabled=judge_enabled,
        units=units,
        calls_by_role=by_role,
        total_calls=sum(by_role.model_dump().values()),
    )


DRY_RUN_ROLE_ORDER: tuple[ProviderRole, ...] = (
    "analysis",
    "question_generation",
    "prompt_generation",
    "target_execution",
    "judge",
)


def frozen_study_call_ceiling() -> RoleCallBudget:
    """The approved ceiling: 8 tasks x 3 repetitions with Q=2 and a judge."""

    return RoleCallBudget(
        analysis=24,
        question_generation=48,
        prompt_generation=24,
        target_execution=48,
        judge=24,
    )


class DryRunReport(StrictAnalysisModel):
    plan: DryRunPlan
    assertions: dict[str, bool] = Field(default_factory=dict)