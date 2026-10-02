"""Regression guard: the offline engine path cannot reach a real provider.

This module asserts the structural property that no offline benchmark code can
accidentally perform network I/O or read credentials. Import analysis is done
with the AST rather than substring search, so an unrelated literal such as a
URL scheme allowlist cannot mask or trigger a false result.
"""

import ast
import inspect
from pathlib import Path

import pytest

from promptpilot_backend import (
    benchmark_experiment_analysis,
    benchmark_experiment_authorization,
    benchmark_experiment_binding,
    benchmark_experiment_execution,
    benchmark_experiment_results,
    production_benchmark_offline,
)
from promptpilot_backend.llm_provider import OpenAICompatibleProvider

ENGINE_MODULES = (
    benchmark_experiment_analysis,
    benchmark_experiment_authorization,
    benchmark_experiment_binding,
    benchmark_experiment_execution,
    benchmark_experiment_results,
)

# Dotted modules that can actually open a socket or an HTTP connection.
# `urllib.parse` is deliberately absent: it is pure string parsing.
NETWORK_MODULES = frozenset(
    {
        "http",
        "http.client",
        "httpx",
        "requests",
        "socket",
        "ssl",
        "aiohttp",
        "urllib3",
        "urllib.request",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
    }
)


def imported_modules(module) -> set[str]:
    """Return fully dotted imported module names (absolute imports only)."""

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_engine_modules_import_no_network_client() -> None:
    for module in ENGINE_MODULES:
        overlap = imported_modules(module) & NETWORK_MODULES
        assert not overlap, f"{module.__name__} imports network modules {overlap}"


def test_engine_modules_never_construct_a_real_provider() -> None:
    for module in ENGINE_MODULES:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else getattr(func, "attr", "")
                )
                assert name != "OpenAICompatibleProvider", (
                    f"{module.__name__} constructs a real provider"
                )


def test_engine_does_not_read_settings_or_credentials() -> None:
    for module in ENGINE_MODULES:
        assert "get_settings" not in imported_modules(module)
        tree = ast.parse(inspect.getsource(module))
        attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert "api_key" not in attributes
        assert "llm_api_key" not in attributes


def test_execution_mode_has_no_live_member() -> None:
    """A live mode is unrepresentable, not merely guarded at runtime."""

    values = benchmark_experiment_execution.ExecutionMode.__args__
    assert values == ("offline_dry_run",)
    assert "live" not in values
    assert benchmark_experiment_execution.EXECUTION_MODES == ("offline_dry_run",)


def test_offline_runner_still_rejects_the_real_provider() -> None:
    provider = OpenAICompatibleProvider.__new__(OpenAICompatibleProvider)
    provider.base_url = "https://example.invalid"
    provider.model = "m"
    provider.api_key = ""
    with pytest.raises(ValueError, match="offline"):
        production_benchmark_offline.OfflineProviders(
            provider, provider, provider, provider
        ).require_offline("generate")


def test_offline_runner_execution_mode_is_unchanged() -> None:
    assert production_benchmark_offline.EXECUTION_MODE == "offline_fixture"


def test_engine_provider_gate_rejects_every_non_offline_provider() -> None:
    guard = benchmark_experiment_execution.require_offline_provider

    class Missing:
        pass

    class WrongFlag:
        offline_fixture = False

    class WrongType:
        offline_fixture = "yes"

    for candidate in (Missing(), WrongFlag(), WrongType()):
        with pytest.raises(benchmark_experiment_execution.ExecutionGateError):
            guard(candidate, "analysis")


def test_ledger_module_still_has_no_provider_or_network_dependency() -> None:
    from promptpilot_backend import benchmark_call_ledger

    names = imported_modules(benchmark_call_ledger)
    assert not names & NETWORK_MODULES
    assert "llm_provider" not in names
    assert "config" not in names


def test_protocol_module_still_constructs_no_provider() -> None:
    from promptpilot_backend import production_benchmark_protocol

    names = imported_modules(production_benchmark_protocol)
    assert "llm_provider" not in names
    assert not names & NETWORK_MODULES


def test_no_new_source_file_defines_a_live_runner_entrypoint() -> None:
    """A live CLI or FastAPI route for the engine must not appear in this milestone."""

    src = Path(inspect.getfile(OpenAICompatibleProvider)).parent
    for path in sorted(src.glob("benchmark_experiment_*.py")):
        source = path.read_text(encoding="utf-8")
        assert "argparse" not in source, f"{path.name} adds a CLI"
        assert "APIRouter" not in source, f"{path.name} adds a route"
        assert "def main(" not in source, f"{path.name} adds an entrypoint"