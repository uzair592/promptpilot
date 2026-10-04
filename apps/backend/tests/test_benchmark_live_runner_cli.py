"""Safe CLI planning and protocol-relative fixture loading."""

from argparse import Namespace

from conftest import EXPERIMENT_DATASET, EXPERIMENT_PROTOCOL

from promptpilot_backend.benchmark_live_runner_cli import cmd_dry_run


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
