from coolbox.plugins.manifest import (
    PluginCapabilities,
    PluginDefinition,
    PluginDevSettings,
    PluginIOSchema,
    ResourceBudget,
    RuntimeConfiguration,
    StartupHooks,
)
from coolbox.plugins.update import PluginChannel, PluginChannelUpdater


def _definition(identifier: str, version: str) -> PluginDefinition:
    runtime = RuntimeConfiguration(kind="native", entrypoint="tests.sample_plugin:Plugin")
    capabilities = PluginCapabilities(provides=(), requires=(), sandbox=())
    io = PluginIOSchema(inputs={}, outputs={})
    resources = ResourceBudget(cpu=None, memory=None, disk=None, gpu=None, timeout=None)
    hooks = StartupHooks(before=(), after=(), on_failure=())
    dev = PluginDevSettings(hot_reload=False, watch_paths=(), locales=())
    return PluginDefinition(
        identifier=identifier,
        version=version,
        runtime=runtime,
        capabilities=capabilities,
        io=io,
        resources=resources,
        hooks=hooks,
        dev=dev,
        description=None,
        toolbus=None,
    )


def test_plugin_channel_updater(tmp_path):
    updater = PluginChannelUpdater(cache_root=tmp_path)
    base = _definition("sample", "1.0.0")
    updater.bootstrap(base)

    resolved = updater.resolve_definition("sample", base)
    assert resolved.version == "1.0.0"

    beta_def = _definition("sample", "1.1.0")
    updater.stage_release(beta_def, channel=PluginChannel.BETA, version="1.1.0")
    assert updater.staged_release("sample", PluginChannel.BETA) is not None

    promoted = updater.promote("sample", PluginChannel.BETA)
    updater.set_channel("sample", PluginChannel.BETA)
    assert promoted.version == "1.1.0"
    resolved_beta = updater.resolve_definition("sample", base)
    assert resolved_beta.version == "1.1.0"

    rollback = updater.rollback("sample", PluginChannel.BETA)
    assert rollback.version == "1.0.0"
    updater.set_channel("sample", PluginChannel.STABLE)
    assert updater.resolve_definition("sample", base).version == "1.0.0"

    cache_root = tmp_path / "plugins" / "sample" / "updates" / "beta"
    assert (cache_root / "active.json").exists()
