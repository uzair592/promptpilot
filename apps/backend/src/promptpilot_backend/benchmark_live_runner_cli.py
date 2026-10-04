"""Safe live-runner CLI for the guarded production benchmark.

This CLI provides safe operations for the live runner:
- validate: Validate a protocol and admission
- dry-run: Simulate the full 168-call workload
- stage: Stage an experiment run (requires admission)
- inspect: Inspect a staged run's budget and status

The live-run operation is NOT exposed via this CLI - it requires the
full launch gate which is not accessible from the CLI in this milestone.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from promptpilot_backend.benchmark import load_dataset

from .benchmark_call_ledger import (
    BenchmarkCallLedger,
    LedgerError,
)
from .benchmark_experiment_analysis import (
    plan_dry_run,
)
from .benchmark_experiment_authorization import (
    evaluate_launch_gate,
    parse_authorization,
)
from .benchmark_experiment_binding import (
    BindingError,
)
from .benchmark_fixtures import (
    load_fixture_manifest,
    manifest_sha256,
)
from .db import SessionLocal
from .production_benchmark_protocol import (
    LiveStudyProtocol,
    admit_protocol,
    protocol_sha256,
)


def load_protocol(path: Path | str) -> LiveStudyProtocol:
    """Load and validate a protocol file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return LiveStudyProtocol.model_validate(data)


def load_manifests(
    protocol: LiveStudyProtocol, fixtures_dir: Path, dataset: Any
) -> dict[str, tuple[Any, Path]]:
    """Load all fixture manifests referenced by the protocol."""
    manifests = {}
    for selection in protocol.selected_fixtures:
        manifest_path = fixtures_dir / selection.manifest_path
        if not manifest_path.exists():
            raise FileNotFoundError(f"Fixture manifest not found: {manifest_path}")
        manifest = load_fixture_manifest(manifest_path, dataset)
        if manifest.fixture_id != selection.fixture_id:
            raise BindingError(
                "fixture_id_mismatch",
                (
                    f"Fixture ID mismatch: manifest has {manifest.fixture_id}, "
                    f"protocol expects {selection.fixture_id}"
                ),
            )
        if manifest_sha256(manifest) != selection.manifest_sha256:
            raise BindingError(
                "manifest_hash_mismatch",
                f"Fixture manifest hash mismatch for {selection.fixture_id}",
            )
        manifests[selection.fixture_id] = (manifest, manifest_path)
    return manifests


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a protocol against the dataset."""
    try:
        protocol_path = Path(args.protocol)
        protocol = load_protocol(protocol_path)
        dataset = load_dataset(Path(args.dataset))
        report = admit_protocol(protocol, dataset, protocol_path)
        print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0 if report.ready else 1
    except Exception as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Run a complete dry-run simulation."""
    try:
        protocol_path = Path(args.protocol)
        protocol = load_protocol(protocol_path)
        dataset = load_dataset(Path(args.dataset))

        # Load manifests to get task_ids from fixture manifests
        fixtures_dir = protocol_path.parent
        manifests = load_manifests(protocol, fixtures_dir, dataset)
        task_ids = sorted({m.task_id for m, _ in manifests.values()})
        plan = plan_dry_run(
            task_ids=task_ids,
            repetitions=protocol.repetitions,
            question_cap=protocol.question_cap,
            judge_enabled=protocol.evaluation.primary == "llm_judge",
        )

        print("=== Dry Run Plan ===")
        print(f"Tasks: {plan.task_count}")
        print(f"Repetitions: {plan.repetitions}")
        print(f"Question Cap: {plan.question_cap}")
        print(f"Judge Enabled: {plan.judge_enabled}")
        print(f"Units: {plan.unit_count}")
        print("Calls by Role:")
        for role, count in plan.calls_by_role.model_dump().items():
            print(f"  {role}: {count}")
        print(f"Total Calls: {plan.total_calls}")
        print(f"Network Calls: {plan.network_calls}")
        print(f"Cost Estimate: {plan.cost_estimate}")

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(
                json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            print(f"Plan written to {output_path}")

        return 0
    except Exception as e:
        print(f"Dry run failed: {e}", file=sys.stderr)
        return 1


def cmd_stage(args: argparse.Namespace) -> int:
    """Stage an experiment run (requires admission)."""
    try:
        protocol_path = Path(args.protocol)
        protocol = load_protocol(protocol_path)
        dataset = load_dataset(Path(args.dataset))

        # Load manifests
        fixtures_dir = protocol_path.parent
        load_manifests(protocol, fixtures_dir, dataset)

        # Run admission
        report = admit_protocol(protocol, dataset, protocol_path)
        if not report.ready:
            print("Admission not ready:", file=sys.stderr)
            for blocker in report.blockers:
                print(f"  {blocker.code}: {blocker.message}", file=sys.stderr)
            return 1

        # Stage the run
        with SessionLocal() as db:
            UUID(args.owner)
            run = BenchmarkCallLedger.stage_run(
                db, UUID(args.owner), protocol, report, repository_commit_sha=args.commit
            )
            db.commit()
            print(f"Run staged successfully: {run.id}")
            print(f"Status: {run.status}")
            print(f"Total call ceiling: {run.total_call_ceiling}")
            if run.max_spend is not None:
                print(f"Max spend: {run.max_spend} {run.budget_currency}")

        return 0
    except LedgerError as e:
        print(f"Staging failed: {e.code}: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Staging failed: {e}", file=sys.stderr)
        return 1


def cmd_inspect(args: argparse.Namespace) -> int:
    """Inspect a staged run's budget and status."""
    try:
        with SessionLocal() as db:
            run_id = UUID(args.run_id)
            snapshot = BenchmarkCallLedger.budget_snapshot(db, run_id)
            print("=== Budget Snapshot ===")
            print(f"Run ID: {snapshot.run_id}")
            print(f"Status: {snapshot.status}")
            print(f"Total Ceiling: {snapshot.total_ceiling}")
            print(f"Reserved: {snapshot.reserved}")
            print(f"Succeeded: {snapshot.succeeded}")
            print(f"Failed: {snapshot.failed}")
            print(f"Cancelled: {snapshot.cancelled}")
            print(f"Remaining Total: {snapshot.remaining_total}")
            print("Calls by Role:")
            for role, count in snapshot.ceilings.model_dump().items():
                consumed = getattr(snapshot.consumed_by_role, role)
                remaining = getattr(snapshot.remaining_by_role, role)
                print(f"  {role}: ceiling={count}, consumed={consumed}, remaining={remaining}")

            if snapshot.max_spend is not None:
                print("\nMonetary Budget:")
                print(f"  Max Spend: {snapshot.max_spend} {snapshot.budget_currency}")
                print(f"  Spent: {snapshot.spent_amount} {snapshot.spent_currency}")
                print(f"  Remaining: {snapshot.remaining_spend} {snapshot.budget_currency}")

            return 0
    except Exception as e:
        print(f"Inspect failed: {e}", file=sys.stderr)
        return 1


def cmd_launch_gate(args: argparse.Namespace) -> int:
    """Evaluate the launch gate."""
    try:
        protocol_path = Path(args.protocol)
        protocol = load_protocol(protocol_path)
        dataset = load_dataset(Path(args.dataset))

        if args.authorization:
            auth = parse_authorization(json.loads(Path(args.authorization).read_text()))
        else:
            auth = None

        # Check admission before reporting launch readiness.
        admission = admit_protocol(protocol, dataset, protocol_path)
        if not admission.ready:
            print("Admission not ready:", file=sys.stderr)
            for admission_blocker in admission.blockers:
                print(
                    f"  {admission_blocker.code}: {admission_blocker.message}",
                    file=sys.stderr,
                )
            return 1
        manifests = load_manifests(protocol, protocol_path.parent, dataset)

        fixture_ids = list(manifests.keys())
        live_eligible = [fid for fid, (m, _) in manifests.items() if m.live_eligible]

        # Evaluate launch gate separately
        launch_report = evaluate_launch_gate(
            protocol_locked=(protocol.review is not None and protocol.review.status == "locked"),
            fixture_ids=fixture_ids,
            live_eligible_fixture_ids=live_eligible,
            protocol_sha256=protocol_sha256(protocol),
            authorization=auth,
            target_provider=protocol.providers.baseline_target.provider,
            target_model=protocol.providers.baseline_target.model,
        )

        print("=== Launch Gate Report ===")
        print(f"Ready: {launch_report.ready}")
        print(f"Protocol Locked: {launch_report.protocol_locked}")
        print(f"Fixtures Live Eligible: {launch_report.fixtures_live_eligible}")
        print(f"Authorization Present: {launch_report.authorization_present}")
        print(f"Provider Authorized: {launch_report.provider_authorized}")
        print(f"Spending Authorized: {launch_report.spending_authorized}")
        print(f"Provider/Model Authorized: {launch_report.provider_model_authorized}")

        if launch_report.blockers:
            print("Blockers:")
            for gate_blocker in launch_report.blockers:
                print(f"  {gate_blocker.code}: {gate_blocker.message}")

        print(f"\nSoftware Limitation: {launch_report.software_verification_limit}")

        return 0 if launch_report.ready else 1
    except Exception as e:
        print(f"Launch gate evaluation failed: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PromptPilot Guarded Live Runner CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate a protocol
  python -m promptpilot_backend.benchmark_live_runner_cli validate \\
    --protocol fixtures/production_pipeline/synthetic_protocol.json \\
    --dataset benchmark_dataset.json

  # Run a dry run simulation
  python -m promptpilot_backend.benchmark_live_runner_cli dry-run \\
    --protocol fixtures/production_pipeline/synthetic_protocol.json \\
    --dataset benchmark_dataset.json

  # Stage an experiment run (requires admission)
  python -m promptpilot_backend.benchmark_live_runner_cli stage \\
    --protocol fixtures/production_pipeline/synthetic_protocol.json \\
    --dataset benchmark_dataset.json \\
    --owner <owner-uuid>

  # Inspect a staged run
  python -m promptpilot_backend.benchmark_live_runner_cli inspect \\
    --run-id <run-uuid>

  # Evaluate launch gate
  python -m promptpilot_backend.benchmark_live_runner_cli launch-gate \\
    --protocol fixtures/production_pipeline/synthetic_protocol.json \\
    --dataset benchmark_dataset.json \\
    --authorization auth.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a protocol")
    validate_parser.add_argument("--protocol", required=True, help="Path to protocol JSON")
    validate_parser.add_argument("--dataset", required=True, help="Path to dataset JSON")
    validate_parser.set_defaults(func=cmd_validate)

    # Dry-run command
    dry_run_parser = subparsers.add_parser("dry-run", help="Run dry-run simulation")
    dry_run_parser.add_argument("--protocol", required=True, help="Path to protocol JSON")
    dry_run_parser.add_argument("--dataset", required=True, help="Path to dataset JSON")
    dry_run_parser.add_argument("--output", help="Output file for plan JSON")
    dry_run_parser.set_defaults(func=cmd_dry_run)

    # Stage command
    stage_parser = subparsers.add_parser("stage", help="Stage an experiment run")
    stage_parser.add_argument("--protocol", required=True, help="Path to protocol JSON")
    stage_parser.add_argument("--dataset", required=True, help="Path to dataset JSON")
    stage_parser.add_argument("--owner", required=True, help="Owner user UUID")
    stage_parser.add_argument("--commit", help="Repository commit SHA")
    stage_parser.set_defaults(func=cmd_stage)

    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a staged run")
    inspect_parser.add_argument("--run-id", required=True, help="Run UUID")
    inspect_parser.set_defaults(func=cmd_inspect)

    # Launch gate command
    launch_gate_parser = subparsers.add_parser("launch-gate", help="Evaluate launch gate")
    launch_gate_parser.add_argument("--protocol", required=True, help="Path to protocol JSON")
    launch_gate_parser.add_argument("--dataset", required=True, help="Path to dataset JSON")
    launch_gate_parser.add_argument("--authorization", help="Path to authorization JSON")
    launch_gate_parser.set_defaults(func=cmd_launch_gate)

    args = parser.parse_args()
    func: Callable[[argparse.Namespace], int] = args.func
    return func(args)


if __name__ == "__main__":
    sys.exit(main())