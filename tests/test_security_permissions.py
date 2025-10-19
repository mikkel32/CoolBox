from __future__ import annotations

from datetime import datetime, timedelta, timezone

from coolbox.utils import security


class DummySupervisor:
    def __init__(self) -> None:
        self.applied: dict[str, dict[str, str]] = {}

    def security_runtime_snapshot(self) -> dict[str, dict[str, object]]:
        return {
            "worker": {
                "pid": 1234,
                "status": "running",
                "open_ports": ("127.0.0.1:8000 (LISTEN)",),
                "process_tree": ("Worker 1234: demo",),
            }
        }

    def apply_permission_update(self, plugin_id: str, grants: dict[str, str]) -> None:
        self.applied[plugin_id] = dict(grants)


def test_permission_manager_snapshot_and_updates() -> None:
    security.reset_permission_manager()
    manager = security.get_permission_manager()
    supervisor = DummySupervisor()
    manager.bind_supervisor(supervisor)
    manager.register_worker(
        "worker",
        display_name="Worker",
        provides=("logging",),
        requires=("network",),
        sandbox=("fs",),
    )

    snapshot = manager.snapshot()
    worker = snapshot.workers[0]
    assert worker.plugin_id == "worker"
    assert worker.grants[0].capability == "network"
    assert worker.grants[0].state == "allowed"
    assert worker.open_ports == ("127.0.0.1:8000 (LISTEN)",)
    assert worker.process_tree == ("Worker 1234: demo",)

    grant = manager.request_capability("worker", "filesystem", reason="needs access")
    assert grant.pending is True
    assert manager.pending_count() == 1

    snapshot = manager.snapshot()
    assert any(entry.pending for entry in snapshot.pending_requests)

    manager.allow_once("worker", "filesystem")
    assert manager.pending_count() == 0

    manager.record_activity("worker", "filesystem")
    snapshot = manager.snapshot()
    worker = snapshot.workers[0]
    fs_grant = next(item for item in worker.grants if item.capability == "filesystem")
    assert fs_grant.state == "revoked"
    assert supervisor.applied["worker"]["filesystem"] == "revoked"

    manager.allow_always("worker", "network")
    manager.record_activity("worker", "network")
    grant_record = manager._grants["worker"]["network"]  # type: ignore[attr-defined]
    grant_record.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    snapshot = manager.snapshot()
    worker = snapshot.workers[0]
    net_grant = next(item for item in worker.grants if item.capability == "network")
    assert net_grant.state == "downgraded"

    manager.record_syscall_summary("worker", "custom event")
    snapshot = manager.snapshot()
    worker = snapshot.workers[0]
    assert any("custom event" in line for line in worker.recent_syscalls)
