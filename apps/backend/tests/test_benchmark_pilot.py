import sys
from pathlib import Path
from uuid import UUID

import pytest

from promptpilot_backend import benchmark_pilot as pilot

DATASET = Path(__file__).resolve().parents[1] / "benchmark_dataset.json"


@pytest.mark.parametrize(
    "invalid_destination",
    ["missing_parent", "json_exists", "csv_exists", "directory_target"],
)
def test_invalid_export_destinations_make_zero_provider_calls(
    tmp_path, monkeypatch, invalid_destination
):
    prefix = tmp_path / "results"
    if invalid_destination == "missing_parent":
        prefix = tmp_path / "missing" / "results"
    elif invalid_destination == "json_exists":
        Path(f"{prefix}.json").write_text("previous results", encoding="utf-8")
    elif invalid_destination == "csv_exists":
        Path(f"{prefix}.csv").write_text("previous results", encoding="utf-8")
    else:
        Path(f"{prefix}.json").mkdir()

    provider_calls = []
    monkeypatch.setattr(pilot, "require_live_config", lambda: UUID(int=1))
    monkeypatch.setattr(
        pilot, "OpenAICompatibleProvider", lambda: provider_calls.append("constructed")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["benchmark_pilot", "--dataset", str(DATASET), "--output-prefix", str(prefix)],
    )
    with pytest.raises(ValueError):
        pilot.main()
    assert provider_calls == []


def test_unwritable_export_destination_makes_zero_provider_calls(tmp_path, monkeypatch):
    provider_calls = []
    monkeypatch.setattr(pilot, "require_live_config", lambda: UUID(int=1))
    monkeypatch.setattr(
        pilot, "OpenAICompatibleProvider", lambda: provider_calls.append("constructed")
    )
    monkeypatch.setattr(
        pilot.tempfile, "mkstemp", lambda **kwargs: (_ for _ in ()).throw(PermissionError())
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_pilot", "--dataset", str(DATASET),
            "--output-prefix", str(tmp_path / "results"),
        ],
    )
    with pytest.raises(PermissionError):
        pilot.main()
    assert provider_calls == []


def test_unwritable_second_destination_cleans_first_stage(tmp_path, monkeypatch):
    actual_mkstemp = pilot.tempfile.mkstemp
    calls = 0
    provider_calls = []

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("second destination is unwritable")
        return actual_mkstemp(**kwargs)

    monkeypatch.setattr(pilot.tempfile, "mkstemp", fail_second)
    monkeypatch.setattr(pilot, "require_live_config", lambda: UUID(int=1))
    monkeypatch.setattr(
        pilot, "OpenAICompatibleProvider", lambda: provider_calls.append("constructed")
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark_pilot", "--dataset", str(DATASET),
            "--output-prefix", str(tmp_path / "results"),
        ],
    )
    with pytest.raises(PermissionError):
        pilot.main()
    assert provider_calls == []
    assert list(tmp_path.iterdir()) == []


def test_exports_are_staged_then_published_without_overwrite(tmp_path):
    prefix = str(tmp_path / "results")
    with pilot.prepared_exports(prefix) as (stages, targets):
        assert all(stage.is_file() for stage in stages)
        assert all(not target.exists() for target in targets)
        stages[0].write_text("json", encoding="utf-8")
        stages[1].write_text("csv", encoding="utf-8")
        pilot.publish_exports(stages, targets)
        with pytest.raises(FileExistsError):
            pilot.publish_exports(stages, targets)
    assert targets[0].read_text(encoding="utf-8") == "json"
    assert targets[1].read_text(encoding="utf-8") == "csv"
    assert all(not stage.exists() for stage in stages)
