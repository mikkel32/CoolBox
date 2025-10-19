# Plugin Packaging, Preview, and Update Workflows

This guide describes the developer tooling that accompanies the plugin
runtime. It covers how per-plugin virtual environments and WASM artefacts are
prepared, how to launch preview sandboxes, and how channelled updates are
managed.

## Runtime packaging and manifests

Plugin manifests (`profiles[].plugins[]`) now accept additional metadata that
controls packaging:

* `runtime.interpreter` declares interpreter constraints. Use it to pin Python
  versions (`python`), runtimes (`implementation`), and deployment platforms.
* `runtime.build` contains declarative steps that prepare dependencies. Each
  step specifies `command`, optional `cwd`, `environment`, and whether it
  should run inside a shell (`shell`).
* `runtime.lockfile` points at an optional dependency lock. When supplied the
  contents are mirrored into `artifacts/plugins/<plugin>/`.
* `runtime.runtimes` lists additional runtime dependencies (for example host
  runtimes required by a polyglot plugin).
* `runtime.wasm` documents WASM artefacts. Provide at least `module`, and
  optionally `entrypoint`, `runtimes`, and a dedicated `build` plan.

When a manifest is loaded the runtime manager provisions a virtual environment
under `artifacts/plugins/<plugin>/venv`, writes a `lock.json` file containing
the resolved metadata, and executes any declared build steps. WASM modules are
prepared by running the associated build plan if the expected artefact is
missing.

## Launching preview sandboxes

For rapid iteration you can start a preview sandbox that boots a single plugin
in isolation. Two entry points are provided:

```bash
scripts/dev/preview_plugin.sh <plugin-id> --manifest path/to/manifest.yaml \
    --profile dev --prefer docker --port 7777 --open-code
```

On Windows the matching `scripts/dev/preview_plugin.ps1` wrapper forwards all
parameters to the Python helper.

Under the hood both wrappers execute the CLI at
`python scripts/python/run_plugin_preview.py`, which delegates to the
`coolbox.cli.commands.preview_plugin` module. The command simply forwards the
plugin identifier, manifest path, and profile name to `launch_vm_debug`. The
VM/debug launcher now understands three preview-specific environment
variables:

* `COOLBOX_PLUGIN_PREVIEW`
* `COOLBOX_PLUGIN_PREVIEW_MANIFEST`
* `COOLBOX_PLUGIN_PREVIEW_PROFILE`

Any backend (Docker/Podman, Vagrant, or the local fallback) receives the same
environment, making it easy to script repeated preview sessions.

## Channelised updates and governance

The plugin supervisor ships with a `PluginChannelUpdater` that records releases
for three channels: **stable**, **beta**, and **canary**. Releases are stored
under `artifacts/plugins/<plugin>/updates/<channel>/` with metadata, the active
pointer, staged updates, and rollback history.

Typical governance flow:

1. **Bootstrap:** When a manifest is loaded the current definition is recorded
   as the stable release.
2. **Stage:** Use `PluginChannelUpdater.stage_release()` to register a new
   definition on a channel. Metadata can include rollout notes.
3. **Promote:** Call `promote()` to mark the staged release active. The cache
   records previous versions for rollback.
4. **Select channel:** Consumers choose a channel via `PluginChannelUpdater.set_channel()`;
   `resolve_definition()` returns the definition for the currently selected
   channel.
5. **Rollback:** If necessary invoke `rollback()` to revert to the previously
   active release. Cache files maintain a persistent audit trail.

Because channels are persisted alongside manifests, staged updates survive
process restarts and can be orchestrated across environments. Integration with
the `WorkerSupervisor` ensures that resolved definitions (including preview or
beta builds) are loaded into the appropriate runtime.

