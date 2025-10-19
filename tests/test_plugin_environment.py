import os
import sys
from pathlib import Path

from coolbox.plugins.manifest import (
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ResourceBudget,
    RuntimeBuild,
    RuntimeConfiguration,
    RuntimeInterpreter,
    StartupHooks,
)
from coolbox.plugins.runtime.environment import ensure_runtime_environment


def _make_definition(tmp_path: Path) -> PluginDefinition:
    runtime = RuntimeConfiguration(
        kind="native",
        entrypoint="tests.sample_plugin:Plugin",
        environment={"SAMPLE_ENV": "1"},
        interpreter=RuntimeInterpreter(
            python=("3.11",),
            implementation="cpython",
            platforms=("linux",),
            extras={},
        ),
        build=RuntimeBuild(steps=(), lockfile=None),
    )
    capabilities = PluginCapabilities(provides=(), requires=(), sandbox=())
    io = PluginIOSchema(inputs={}, outputs={})
    resources = ResourceBudget(cpu=None, memory=None, disk=None, gpu=None, timeout=None)
    hooks = StartupHooks(before=(), after=(), on_failure=())
    dev = PluginDevSettings(hot_reload=False, watch_paths=(), locales=())
    return PluginDefinition(
        identifier="sample",
        version="1.0.0",
        runtime=runtime,
        capabilities=capabilities,
        io=io,
        resources=resources,
        hooks=hooks,
        dev=dev,
        description="Sample",
        toolbus=None,
    )


def test_ensure_runtime_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("COOLBOX_PROJECT_ROOT", str(tmp_path))
    from coolbox import paths

    paths.project_root.cache_clear()
    paths.artifacts_dir.cache_clear()

    definition = _make_definition(tmp_path)
    env = ensure_runtime_environment(definition)

    assert env.venv_dir.exists()
    assert env.lock_path.exists()
    assert env.activation is not None

    with env.activation.temporary():
        assert os.environ.get("VIRTUAL_ENV") == str(env.venv_dir)
        assert any(str(env.venv_dir) in entry for entry in os.environ.get("PATH", "").split(os.pathsep))
        assert any(str(path) in sys.path for path in env.activation.site_packages)
