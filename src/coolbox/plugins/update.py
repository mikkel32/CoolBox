"""Channelised plugin updater with staged rollout support."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Mapping

from coolbox.paths import artifacts_dir, ensure_directory

from .manifest import PluginDefinition


class PluginChannel(str, Enum):
    """Supported release channels for plugins."""

    STABLE = "stable"
    BETA = "beta"
    CANARY = "canary"


@dataclass(slots=True)
class PluginRelease:
    """Concrete plugin release metadata used by the updater."""

    plugin_id: str
    version: str
    channel: PluginChannel
    definition: PluginDefinition
    rollout: float = 1.0
    staged: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


class PluginUpdateCache:
    """On-disk cache for staged and active plugin releases."""

    def __init__(self, root: Path | None = None) -> None:
        base = artifacts_dir() if root is None else root
        self._root = ensure_directory(base / "plugins")

    def store_release(self, release: PluginRelease) -> Path:
        directory = self._channel_dir(release.plugin_id, release.channel) / release.version
        ensure_directory(directory)
        payload = {
            "plugin": release.plugin_id,
            "version": release.version,
            "channel": release.channel.value,
            "rollout": release.rollout,
            "staged": release.staged,
            "metadata": dict(release.metadata),
            "definition": _jsonify(asdict(release.definition)),
        }
        target = directory / "metadata.json"
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return directory

    def record_staged(self, plugin_id: str, channel: PluginChannel, version: str) -> None:
        path = self._channel_dir(plugin_id, channel) / "staged.json"
        ensure_directory(path.parent)
        with path.open("w", encoding="utf-8") as handle:
            json.dump({"version": version}, handle, indent=2, sort_keys=True)

    def clear_staged(self, plugin_id: str, channel: PluginChannel) -> None:
        path = self._channel_dir(plugin_id, channel) / "staged.json"
        if path.exists():
            path.unlink()

    def mark_active(self, plugin_id: str, channel: PluginChannel, version: str, previous: str | None) -> None:
        payload = {"version": version}
        if previous:
            payload["previous"] = previous
        path = self._channel_dir(plugin_id, channel) / "active.json"
        ensure_directory(path.parent)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        if previous:
            rollback = self._channel_dir(plugin_id, channel) / "rollback.json"
            with rollback.open("w", encoding="utf-8") as handle:
                json.dump({"version": previous}, handle, indent=2, sort_keys=True)

    def channel_root(self, plugin_id: str, channel: PluginChannel) -> Path:
        return self._channel_dir(plugin_id, channel)

    def _channel_dir(self, plugin_id: str, channel: PluginChannel) -> Path:
        return ensure_directory(self._root / plugin_id / "updates" / channel.value)


class PluginChannelUpdater:
    """Manage plugin releases across stable/beta/canary channels."""

    def __init__(self, *, cache_root: Path | None = None) -> None:
        self._cache = PluginUpdateCache(cache_root)
        self._channels: Dict[str, PluginChannel] = {}
        self._history: Dict[str, Dict[PluginChannel, list[PluginRelease]]] = {}
        self._active: Dict[str, Dict[PluginChannel, PluginRelease]] = {}
        self._staged: Dict[str, Dict[PluginChannel, PluginRelease]] = {}

    def bootstrap(self, definition: PluginDefinition) -> None:
        """Ensure the baseline stable release exists for ``definition``."""

        channel = PluginChannel.STABLE
        version = definition.version or "0.0.0"
        release = PluginRelease(
            plugin_id=definition.identifier,
            version=version,
            channel=channel,
            definition=definition,
            staged=False,
        )
        if self._has_release(release):
            return
        self._register_release(release, staged=False)
        self._channels.setdefault(definition.identifier, PluginChannel.STABLE)

    def set_channel(self, plugin_id: str, channel: PluginChannel) -> None:
        self._channels[plugin_id] = channel

    def stage_release(
        self,
        definition: PluginDefinition,
        *,
        channel: PluginChannel,
        version: str,
        rollout: float = 1.0,
        metadata: Mapping[str, object] | None = None,
    ) -> PluginRelease:
        """Stage ``definition`` for later promotion on ``channel``."""

        release = PluginRelease(
            plugin_id=definition.identifier,
            version=version,
            channel=channel,
            definition=definition,
            rollout=rollout,
            staged=True,
            metadata=dict(metadata or {}),
        )
        staged = self._staged.setdefault(definition.identifier, {})
        staged[channel] = release
        self._cache.store_release(release)
        self._cache.record_staged(definition.identifier, channel, version)
        return release

    def promote(self, plugin_id: str, channel: PluginChannel) -> PluginRelease:
        """Promote the staged release for ``plugin_id`` on ``channel``."""

        staged = self._staged.get(plugin_id, {}).get(channel)
        if staged is None:
            raise RuntimeError(f"No staged release for {plugin_id} on {channel.value}")
        staged.staged = False
        previous = self._active.get(plugin_id, {}).get(channel)
        if previous is None and channel is not PluginChannel.STABLE:
            stable_release = self._active.get(plugin_id, {}).get(PluginChannel.STABLE)
            if stable_release is not None:
                baseline = PluginRelease(
                    plugin_id=stable_release.plugin_id,
                    version=stable_release.version,
                    channel=channel,
                    definition=stable_release.definition,
                    rollout=stable_release.rollout,
                    staged=False,
                    metadata=dict(stable_release.metadata),
                )
                self._register_release(baseline, staged=False)
                previous = baseline
        self._register_release(staged, staged=False)
        self._cache.mark_active(plugin_id, channel, staged.version, previous.version if previous else None)
        self._cache.clear_staged(plugin_id, channel)
        self._staged.setdefault(plugin_id, {}).pop(channel, None)
        return staged

    def rollback(self, plugin_id: str, channel: PluginChannel) -> PluginRelease:
        """Rollback ``plugin_id`` to the previous release for ``channel``."""

        history = self._history.get(plugin_id, {}).get(channel)
        if not history or len(history) < 2:
            raise RuntimeError(f"No rollback candidate for {plugin_id} on {channel.value}")
        current = history.pop()
        previous = history[-1]
        active_map = self._active.setdefault(plugin_id, {})
        active_map[channel] = previous
        self._cache.mark_active(plugin_id, channel, previous.version, None)
        return previous

    def resolve_definition(self, plugin_id: str, default: PluginDefinition) -> PluginDefinition:
        """Return the definition for the active channel or ``default``."""

        channel = self._channels.get(plugin_id, PluginChannel.STABLE)
        release = self._active.get(plugin_id, {}).get(channel)
        return release.definition if release else default

    def staged_release(self, plugin_id: str, channel: PluginChannel) -> PluginRelease | None:
        return self._staged.get(plugin_id, {}).get(channel)

    def active_release(self, plugin_id: str, channel: PluginChannel) -> PluginRelease | None:
        return self._active.get(plugin_id, {}).get(channel)

    def _register_release(self, release: PluginRelease, staged: bool) -> None:
        history = self._history.setdefault(release.plugin_id, {})
        channel_history = history.setdefault(release.channel, [])
        if channel_history and channel_history[-1].version == release.version:
            channel_history[-1] = release
        else:
            channel_history.append(release)
        active = self._active.setdefault(release.plugin_id, {})
        active[release.channel] = release
        release.staged = staged
        self._cache.store_release(release)
        self._cache.mark_active(
            release.plugin_id,
            release.channel,
            release.version,
            channel_history[-2].version if len(channel_history) > 1 else None,
        )

    def _has_release(self, release: PluginRelease) -> bool:
        history = self._history.get(release.plugin_id, {}).get(release.channel)
        if history:
            return any(entry.version == release.version for entry in history)
        return False


def _jsonify(data: object) -> object:
    if isinstance(data, dict):
        return {key: _jsonify(value) for key, value in data.items()}
    if isinstance(data, list):
        return [_jsonify(value) for value in data]
    if isinstance(data, tuple):
        return [_jsonify(value) for value in data]
    if isinstance(data, Path):
        return str(data)
    return data


__all__ = [
    "PluginChannel",
    "PluginChannelUpdater",
    "PluginRelease",
]

