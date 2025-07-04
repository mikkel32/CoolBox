import json
from src.utils.network_baseline import NetworkBaseline
from src.utils import security_log


def test_baseline_diff_and_update(tmp_path):
    path = tmp_path / "base.json"
    bl = NetworkBaseline(path=path)
    new_ports, new_hosts = bl.diff([1, 2], ["h1", "h2"])
    assert new_ports == {1, 2}
    assert new_hosts == {"h1", "h2"}
    assert not path.exists()

    new_ports, new_hosts = bl.diff([1], ["h1"], update=True)
    assert bl.ports == {1}
    assert bl.hosts == {"h1"}
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data["ports"] == [1]
    assert data["hosts"] == ["h1"]

    new_ports, new_hosts = bl.diff([1, 2], ["h1", "h3"])
    assert new_ports == {2}
    assert new_hosts == {"h3"}


def test_baseline_logging(tmp_path, monkeypatch):
    path = tmp_path / "log.json"
    events = []
    monkeypatch.setattr(
        security_log,
        "add_security_event",
        lambda c, m: events.append((c, m)),
    )
    bl = NetworkBaseline(path=path)
    bl.diff([5], ["h"], update=True)
    bl.clear()
    assert ("baseline_update", "ports:1 hosts:1") in events
    assert ("baseline_clear", "all") in events
