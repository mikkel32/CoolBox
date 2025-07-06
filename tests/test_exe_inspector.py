import platform
from pathlib import Path
from types import SimpleNamespace

import scripts.exe_inspector as inspector


def test_gather_info_windows(monkeypatch, tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_text("hello")
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    called = []

    def fake_ps(cmd):
        called.append(cmd)
        return "val"

    monkeypatch.setattr(inspector, "_powershell", fake_ps)
    monkeypatch.setattr(inspector, "calc_hash", lambda p, algo="sha256": "hash")

    info = inspector.gather_info(exe)
    assert info["SHA256"] == "hash"
    assert info["Version"] == "val"
    assert called


def test_processes_for(monkeypatch, tmp_path):
    exe = tmp_path / "a.exe"
    exe.write_text("x")

    proc = SimpleNamespace(info={"pid": 1, "name": "a", "exe": str(exe)})

    monkeypatch.setattr(
        inspector.psutil,
        "process_iter",
        lambda attrs=None: [proc],
    )

    procs = inspector._processes_for(exe)
    assert len(procs) == 1


def test_hash_fallback(monkeypatch, tmp_path):
    exe = tmp_path / "stub.exe"
    exe.write_text("x")

    def fail_hash(path, algo="sha256"):
        raise PermissionError("denied")

    monkeypatch.setattr(inspector, "calc_hash", fail_hash)
    monkeypatch.setattr(
        inspector,
        "run_command",
        lambda cmd, capture=False: "abcd1234 efgh" if capture else "",
    )

    digest = inspector._calc_hash_smart(exe)
    assert digest == "abcd1234"


def test_gather_info_denied(monkeypatch, tmp_path):
    exe = tmp_path / "bad.exe"
    exe.write_text("x")

    orig_stat = Path.stat
    orig_exists = Path.exists

    def fake_stat(self, *a, **kw):
        if self == exe:
            raise PermissionError()
        return orig_stat(self, *a, **kw)

    def fake_exists(self):
        if self == exe:
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(Path, "exists", fake_exists)

    info = inspector.gather_info(exe)
    assert info.get("Access") == "Denied"


def test_extract_strings(tmp_path):
    exe = tmp_path / "bin"
    exe.write_bytes(b"\x00hello\x00world1234\x00")
    strings = inspector._extract_strings(exe, limit=5, min_len=4)
    assert "hello" in strings
    assert "world1234" in strings
