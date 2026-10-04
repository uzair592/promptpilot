"""Safety regressions for guarded production-pipeline execution."""

import pytest
from conftest import EXPERIMENT_DATASET

from promptpilot_backend.benchmark import load_dataset
from promptpilot_backend.benchmark_experiment_execution import ExecutionGateError
from promptpilot_backend.benchmark_live_runner import LiveExperimentRunner
from promptpilot_backend.benchmark_provider_adapter import ProviderAdapterFactory


def test_per_unit_runner_rejects_synthetic_offline_results(
    experiment_env, db_session
) -> None:
    with pytest.raises(ExecutionGateError) as caught:
        LiveExperimentRunner(
            db=db_session,
            run_id=experiment_env.run_id,
            binding=experiment_env.binding,
            protocol=experiment_env.protocol,
            dataset=load_dataset(EXPERIMENT_DATASET),
            fixture_manifests=[],
            adapter_factory=ProviderAdapterFactory("offline_dry_run"),
        )

    assert caught.value.code == "live_execution_required"
