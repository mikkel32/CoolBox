import psutil

from src.utils.process_blocker import ProcessBlocker


class FakeProc:
    def __init__(self, pid: int, info: dict):
        self.info = info

    def name(self):
        return self.info.get("name")

    def exe(self):
        return self.info.get("exe")


def test_blocker_kills_matching(monkeypatch, tmp_path):
    killed = []
    processes = [
        FakeProc(1, {"pid": 1, "name": "evil", "exe": "/x"}),
        FakeProc(2, {"pid": 2, "name": "good", "exe": "/y"}),
    ]

    monkeypatch.setattr(psutil, "process_iter", lambda attrs: processes)
    monkeypatch.setattr(
        "src.utils.process_blocker.kill_process_tree",
        lambda pid: killed.append(pid) or True,
    )

    blocker = ProcessBlocker(path=tmp_path / "block.json")
    blocker.add("evil", "/x")
    blocker.check()
    assert killed == [1]


def test_blocker_add_by_pid(monkeypatch, tmp_path):
    proc = FakeProc(3, {"pid": 3, "name": "bad", "exe": "/z"})
    monkeypatch.setattr(psutil, "Process", lambda pid: proc)
    blocker = ProcessBlocker(path=tmp_path / "block.json")
    blocker.add_by_pid(3)

    killed = []
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: [proc])
    monkeypatch.setattr(
        "src.utils.process_blocker.kill_process_tree",
        lambda pid: killed.append(pid) or True,
    )
    blocker.check()
    assert killed == [3]


def test_blocker_name_matches_any_exe(monkeypatch, tmp_path):
    processes = [
        FakeProc(4, {"pid": 4, "name": "dup", "exe": "/a"}),
        FakeProc(5, {"pid": 5, "name": "dup", "exe": "/b"}),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs: processes)

    killed = []
    monkeypatch.setattr(
        "src.utils.process_blocker.kill_process_tree",
        lambda pid: killed.append(pid) or True,
    )

    blocker = ProcessBlocker(path=tmp_path / "block.json")
    blocker.add("dup")
    blocker.check()
    assert set(killed) == {4, 5}


def test_blocker_persistence(tmp_path):
    path = tmp_path / "block.json"
    blocker = ProcessBlocker(path=path)
    blocker.add("persist", "/x")
    assert path.is_file()

    new_blocker = ProcessBlocker(path=path)
    assert "persist" in new_blocker.targets
    assert "/x" in new_blocker.targets["persist"].exe_paths


def test_blocker_remove(monkeypatch, tmp_path):
    blocker = ProcessBlocker(path=tmp_path / "b.json")
    blocker.add("bad", "/a")
    blocker.add("bad", "/b")
    assert blocker.remove("bad", "/a") is True
    assert "bad" in blocker.targets
    assert "/a" not in blocker.targets["bad"].exe_paths
    assert blocker.remove("bad") is True
    assert "bad" not in blocker.targets


def test_blocker_clear(tmp_path):
    blocker = ProcessBlocker(path=tmp_path / "b.json")
    blocker.add("a")
    blocker.add("b", "/x")
    assert blocker.targets
    blocker.clear()
    assert blocker.targets == {}
    assert (tmp_path / "b.json").is_file()


def test_blocker_logging(monkeypatch, tmp_path):
    events = []
    monkeypatch.setattr(
        "src.utils.process_blocker.security_log.add_security_event",
        lambda c, m: events.append((c, m)),
    )
    proc = FakeProc(10, {"pid": 10, "name": "evil", "exe": "/e"})
    monkeypatch.setattr(psutil, "Process", lambda pid: proc)
    blocker = ProcessBlocker(path=tmp_path / "b.json")
    blocker.add_by_pid(10)
    blocker.add("evil", "/e")
    blocker.remove("evil", "/e")
    blocker.add("left")
    blocker.clear()
    assert ("block_process_pid", "pid 10") in events
    assert ("block_process", "evil /e") in events
    assert ("unblock_process", "evil /e") in events
    assert ("clear_processes", "all") in events
