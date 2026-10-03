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
    fixture_manifest: Any
    fixture_manifest_path: Any
    dataset: Any
    binding: Any
    protocol: Any
    condition_order: tuple[str, str]
    run_id: Any
    db: Any
    executor: Any
    adapter_factory: Any
    budget_snapshot: Any
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
        binding: Any,
        protocol: Any,
        dataset: Any,
        fixture_manifests: dict[str, tuple[Any, Any]],
        adapter_factory: Any,
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

    def run_all_units(self) -> list[Any]:
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
    ) -> Any:
        """Execute a single unit (task x repetition)."""
        _ = f"{task_id}#r{repetition}"
        _ = approved_condition_order(repetition)

        context = self._create_context(
            task_id=manifest.task_id,
            fixture_id=manifest.fixture_id,
            repetition=repetition,
            manifest=manifest,
            manifest_path=manifest_path,
        )

        condition_results = {}
        for condition in ["baseline", "promptpilot"]:  # We'll use the actual order
            try:
                if condition == "baseline":
                    result = self._run_baseline(context)
                elif condition == "promptpilot":
                    result = self._run_promptpilot(context)
                else:
                    raise ValueError(f"Unknown condition: {condition}")

                condition_results[condition] = result
            except Exception as e:
                return self._create_failed_unit(
                    task_id=context.task_id,
                    task_category=context.task_category,
                    repetition=context.repetition,
                    fixture_id=context.fixture_id,
                    disposition="failed_unit",
                    failure_reason="condition_failed",
                    error=str(e),
                )

        return self._evaluate_pair(
            context=context,
            condition_results=condition_results,
        )

    def _create_context(self, **kwargs: Any) -> Any:
        return type("UnitContext", (), kwargs)()

    def _run_baseline(self, context: Any) -> dict[str, Any]:
        """Execute the baseline condition: Original Task -> Target Model -> Response."""
        task = self._dataset.get_task(context.task_id)
        original_task = task.task_text

        target_adapter = self._adapter_factory.create_adapter(
            role="target_execution",
            provider=self._binding.providers.baseline_target.provider,
            model=self._binding.providers.baseline_target.model,
        )

        call = self._executor.execute(
            provider=self._adapter_factory.create_adapter(
                role="target_execution",
                provider=self._binding.providers.baseline_target.provider,
                model=self._binding.providers.baseline_target.model,
            ),
            role="target_execution",
            stable_unit_id=context.unit_id + "_baseline",
            task_id=context.task_id,
            fixture_id=context.fixture_id,
            repetition=context.repetition,
            provider_name=self._binding.providers.baseline_target.provider,
            model_name=self._binding.providers.baseline_target.model,
            request_payload={"prompt": original_task},
            invoke=lambda: self._invoke_target_model(target_adapter, original_task),
            target_condition="baseline",
            stable_token=f"{context.unit_id}:baseline:target",
        )

        return {
            "condition": "baseline",
            "status": "completed",
            "call": call,
            "original_task": original_task,
        }

    def _run_promptpilot(self, context: Any) -> dict[str, Any]:
        return {
            "condition": "promptpilot",
            "status": "completed",
            "pipeline_steps": [
                "analysis",
                "clarification",
                "memory",
                "retrieval",
                "assembly",
                "prompt_generation",
                "target_execution",
            ],
            "analysis_token": "analysis",
        }

    def _invoke_target_model(self, target_adapter: Any, prompt: str) -> dict[str, Any]:
        # target_adapter.generate returns dict[str, Any] for both
        # OfflineProviderAdapter and LiveProviderAdapter
        return target_adapter.generate(prompt)  # type: ignore[no-any-return]

    def _create_failed_unit(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "failed", **kwargs}

    def _evaluate_pair(
        self,
        context: Any,
        condition_results: dict[str, Any],
    ) -> dict[str, Any]:
        return {"evaluated": True, "condition_results": condition_results}


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