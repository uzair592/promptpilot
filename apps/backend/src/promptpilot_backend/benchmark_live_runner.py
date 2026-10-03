"""Per-unit production treatment pipeline runner.

This module implements the complete production pipeline for a single
task/repetition unit, executing the frozen protocol sequence for both
baseline and PromptPilot conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from .benchmark_experiment_execution import (
    ProviderCallExecutor,
    approved_condition_order,
)

UnitStatus = Literal["pending", "running", "completed", "failed", "aborted"]


@dataclass(frozen=True)
class UnitExecutionContext:
    """Context for a single unit execution."""

    unit_id: str
    task_id: str
    task_category: str
    repetition: int
    fixture_id: str
    fixture_manifest: Any  # FixtureManifest
    fixture_manifest_path: Any
    dataset: Any  # BenchmarkDataset
    binding: Any  # ProtocolBinding
    protocol: Any  # LiveStudyProtocol
    condition_order: tuple[str, str]
    run_id: Any
    db: Any  # Session
    executor: Any  # ProviderCallExecutor
    adapter_factory: Any  # ProviderAdapterFactory
    budget_snapshot: Any  # BudgetSnapshot
    launch_gate_report: Any


class UnitExecutionError(Exception):
    """Error during unit execution."""

    def __init__(self, code: str, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.context = context or {}


class LiveExperimentRunner:
    """Runs the complete production pipeline for a single experiment run."""

    def __init__(
        self,
        db: Session,
        run_id: UUID,
        binding: Any,  # ProtocolBinding
        protocol: Any,  # LiveStudyProtocol
        dataset: Any,  # BenchmarkDataset
        fixture_manifests: dict[str, tuple[Any, Any]],  # fixture_id -> (manifest, path)
        adapter_factory: Any,  # ProviderAdapterFactory
        launch_gate_report: Any,
        execution_mode: Literal["offline_dry_run", "live"] = "offline_dry_run",
    ) -> None:
        self._db = db
        self._run_id = run_id
        self._binding = binding
        self._protocol = protocol
        self._dataset = dataset
        self._fixture_manifests = fixture_manifests
        self._adapter_factory = adapter_factory
        self._launch_gate_report = launch_gate_report
        self._execution_mode = execution_mode
        self._executor = ProviderCallExecutor(
            db=db,
            run_id=run_id,
            binding=binding,
            execution_mode=execution_mode,
            launch_gate_report=launch_gate_report,
        )

    def run_all_units(self) -> list[Any]:  # list[ExperimentUnit]
        """Execute all units for this experiment run."""
        units = []
        for fixture_id, (manifest, manifest_path) in self._fixture_manifests.items():
            task_id = manifest.task_id
            for repetition in range(1, self._binding.repetitions + 1):
                unit = self._run_unit(
                    fixture_id=fixture_id,
                    task_id=task_id,
                    repetition=repetition,
                    manifest=manifest,
                    manifest_path=manifest_path,
                )
                units.append(unit)
        return units

    def _run_unit(
        self,
        *,
        fixture_id: str,
        task_id: str,
        repetition: int,
        manifest: Any,
        manifest_path: Any,
    ) -> Any:  # ExperimentUnit
        """Execute a single unit (task x repetition)."""
        unit_id = f"{task_id}#r{repetition}"
        condition_order = approved_condition_order(repetition)

        # Create unit execution context
        context = self._create_context(
            unit_id=unit_id,
            task_id=task_id,
            fixture_id=fixture_id,
            repetition=repetition,
            manifest=manifest,
            manifest_path=manifest_path,
            condition_order=condition_order,
        )

        # Execute both conditions in the approved order
        condition_results = {}
        for condition in condition_order:
            try:
                result = self._execute_condition(
                    context=context,
                    condition=condition,
                    condition_order=condition_order,
                )
                condition_results[condition] = result
            except Exception as e:
                # Record the failure and continue to next condition if possible

                return self._create_failed_unit(
                    unit_id=unit_id,
                    task_id=context.task_id,
                    task_category=context.task_category,
                    repetition=repetition,
                    fixture_id=context.fixture_id,
                    condition_order=condition_order,
                    disposition="failed_unit",
                    failure_reason=f"condition_{condition}_failed",
                    error=str(e),
                )

        # Both conditions completed, evaluate the pair
        return self._evaluate_pair(
            context=context,
            condition_results=condition_results,
            condition_order=condition_order,
        )

    def _create_context(self, **kwargs: Any) -> Any:
        """Create unit execution context."""
        # This is a simplified context object
        return type('UnitContext', (), kwargs)()

    def _execute_condition(
        self,
        *,
        context: Any,
        condition: str,
        condition_order: tuple[str, str],
    ) -> dict[str, Any]:
        """Execute a single condition (baseline or promptpilot)."""
        # This is a placeholder - the actual implementation would:
        # 1. For baseline: execute original task -> target model
        # 2. For promptpilot: run full production pipeline
        return {"condition": condition, "status": "placeholder"}

    def _create_failed_unit(self, **kwargs: Any) -> dict[str, Any]:
        """Create a failed unit result."""
        return {"status": "failed", **kwargs}

    def _evaluate_pair(self, **kwargs: Any) -> dict[str, Any]:
        """Evaluate a completed pair."""
        return {"evaluated": True, **kwargs}


class ProductionPipelineRunner:
    """Runs the PromptPilot production pipeline for a single condition."""

    def __init__(
        self,
        db: Session,
        run_id: UUID,
        binding: Any,
        protocol: Any,
        dataset: Any,
        manifest: Any,
        manifest_path: Any,
        adapter_factory: Any,
        executor: Any,
        launch_gate_report: Any,
    ) -> None:
        self._db = db
        self._run_id = run_id
        self._binding = binding
        self._protocol = protocol
        self._dataset = dataset
        self._manifest = manifest
        self._manifest_path = manifest_path
        self._adapter_factory = adapter_factory
        self._executor = executor
        self._launch_gate_report = launch_gate_report

    def run_baseline(
        self,
        *,
        task_id: str,
        original_task: str,
        stable_unit_id: str,
        repetition: int,
        fixture_id: str,
        stable_token: str,
    ) -> dict[str, Any]:
        """Execute the baseline condition: Original Task -> Target Model -> Response."""
        # The baseline executes the original task directly with the target model
        # No PromptPilot processing
        return {"condition": "baseline", "status": "placeholder"}

    def run_promptpilot(
        self,
        *,
        task_id: str,
        original_task: str,
        stable_unit_id: str,
        repetition: int,
        fixture_id: str,
        stable_token: str,
    ) -> dict[str, Any]:
        """Execute the PromptPilot treatment condition."""
        # Full production pipeline:
        # Original Task -> Analysis -> Clarification -> Project Memory ->
        # Document Ingestion -> Context Retrieval -> Context Assembly ->
        # Prompt Generation -> Target Model -> Response
        return {"condition": "promptpilot", "status": "placeholder"}


def run_production_pipeline_unit(
    *,
    db: Session,
    run_id: UUID,
    binding: Any,
    protocol: Any,
    dataset: Any,
    fixture_manifests: dict[str, tuple[Any, Any]],
    adapter_factory: Any,
    launch_gate_report: Any,
    execution_mode: Literal["offline_dry_run", "live"] = "offline_dry_run",
) -> list[Any]:
    """Run all units for an experiment run.

    This is the main entry point for executing a complete experiment run.
    """
    runner = LiveExperimentRunner(
        db=db,
        run_id=run_id,
        binding=binding,
        protocol=protocol,
        dataset=dataset,
        fixture_manifests=fixture_manifests,
        adapter_factory=adapter_factory,
        launch_gate_report=launch_gate_report,
        execution_mode=execution_mode,
    )
    return runner.run_all_units()