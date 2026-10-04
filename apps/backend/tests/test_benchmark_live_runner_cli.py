"""Safe CLI planning and protocol-relative fixture loading."""

from argparse import Namespace

from conftest import EXPERIMENT_DATASET, EXPERIMENT_PROTOCOL

from promptpilot_backend.benchmark_experiment_analysis import frozen_study_call_ceiling
from promptpilot_backend.benchmark_live_runner_cli import cmd_dry_run, cmd_validate


def test_dry_run_loads_sibling_manifest_and_only_reports_a_plan(capsys) -> None:
    result = cmd_dry_run(
        Namespace(
            protocol=str(EXPERIMENT_PROTOCOL),
            dataset=str(EXPERIMENT_DATASET),
            output=None,
        )
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "Units: 2" in output
    assert "Total Calls: 12" in output
    assert "Network Calls: 0" in output
    assert "Cost Estimate: 0" in output


def test_offline_validate_and_dry_run_never_open_a_network_connection(
    monkeypatch, capsys
) -> None:
    network_attempts: list[object] = []

    def forbidden_urlopen(request, *args, **kwargs):
        network_attempts.append(request)
        raise AssertionError("Offline CLI paths must not open a network connection")

    monkeypatch.setattr(
        "promptpilot_backend.llm_provider.urlopen",
        forbidden_urlopen,
    )
    args = Namespace(
        protocol=str(EXPERIMENT_PROTOCOL),
        dataset=str(EXPERIMENT_DATASET),
        output=None,
    )

    cmd_validate(args)
    cmd_dry_run(args)

    assert network_attempts == []
    assert "Network Calls: 0" in capsys.readouterr().out


def test_frozen_study_call_ceiling_remains_168() -> None:
    ceiling = frozen_study_call_ceiling()

    assert sum(ceiling.model_dump().values()) == 168
    assert ceiling.analysis == 24
    assert ceiling.question_generation == 48
    assert ceiling.prompt_generation == 24
    assert ceiling.target_execution == 48
    assert ceiling.judge == 24
