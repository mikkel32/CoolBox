import importlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import setup
from src.setup.orchestrator import (
    SetupOrchestrator,
    SetupStage,
    SetupStatus,
    SetupTask,
    SetupResult,
)
from src.setup.plugins import PluginManager, ValidatorDecision
from src.setup.recipes import Recipe


def test_run_wrapper_records_diagnostics(monkeypatch):
    importlib.reload(setup)
    setup.SUMMARY.commands.clear()

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=1, stderr="connection refused")

    monkeypatch.setattr(setup.subprocess, "run", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        setup._run(["pip", "install", "pkg"])

    record = setup.SUMMARY.last_command()
    assert record is not None
    assert record.command[0] == "pip"
    assert record.exit_code == 1
    assert record.stderr == "connection refused"
    assert record.duration >= 0
    assert "connect" in (record.hint or "").lower()


def test_continuous_validator_triggers_repair(tmp_path):
    plugin_manager = PluginManager()
    orchestrator = SetupOrchestrator(root=tmp_path, plugin_manager=plugin_manager)

    state = {"attempts": 0}

    def failing_task(context):
        attempts = state["attempts"]
        state["attempts"] = attempts + 1
        if attempts == 0:
            raise RuntimeError("boom")
        return {"status": "ok"}

    def repair_action(context, result):
        context.set("repair", True)
        return SetupResult(
            task="repair.cache",
            stage=result.stage,
            status=SetupStatus.SUCCESS,
            payload={"repair": True},
        )

    def validator(result, context):
        if result.status is SetupStatus.FAILED:
            return ValidatorDecision(
                name="abi-check",
                reason="abi mismatch",
                repairs=[repair_action],
                retry=True,
            )
        return None

    plugin_manager.continuous_validators.append(validator)

    orchestrator.register_task(
        SetupTask(
            "preflight.fail",
            SetupStage.PREFLIGHT,
            failing_task,
            max_retries=2,
        )
    )

    recipe = Recipe(name="test", data={})

    results = orchestrator.run(recipe)

    statuses = {res.task: res.status for res in results}
    assert statuses["preflight.fail"] is SetupStatus.SUCCESS
    assert statuses["repair.cache"] is SetupStatus.SUCCESS
    assert state["attempts"] == 2
