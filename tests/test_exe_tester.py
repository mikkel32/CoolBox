from io import StringIO
import sys
from pathlib import Path
import argparse

import scripts.exe_tester as et
from rich.console import Console


class DummyBorder:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        pass


def test_exe_tester_run_cli(monkeypatch):
    monkeypatch.setattr(et, "MatrixBorder", lambda console=None: DummyBorder())
    args = et.parse_args([sys.executable, "--iterations", "1", "--runtime", "0.1"])
    buf = StringIO()
    console = Console(file=buf)
    et.run_cli(args, console=console)
    out = buf.getvalue()
    assert "Iteration | Ports" in out
    assert "EXECUTABLE  STRESS  TESTER" in out
    assert "___  __" in out
    assert out.count("Iteration | Usage") >= 2


def test_smart_launch_exe_fallback(monkeypatch):
    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))

    created = {}

    def dummy_popen(args, **kwargs):
        created["args"] = args
        class Dummy:
            def poll(self):
                return None
        return Dummy()

    monkeypatch.setattr(et, "Popen", dummy_popen)
    monkeypatch.setattr(et.platform, "system", lambda: "Windows")

    proc = et.smart_launch_exe(Path(sys.executable))
    assert proc is not None
    assert created["args"][0] != str(Path(sys.executable))


def test_run_powershell_fallback(monkeypatch):
    calls = []
    def fake_run(cmd, capture=False):
        calls.append(cmd)
        if len(calls) < 3:
            return None
        return "ok"

    monkeypatch.setattr(et.platform, "system", lambda: "Windows")
    monkeypatch.setattr(et.security, "_run", fake_run)
    monkeypatch.setattr(et.Path, "is_file", lambda self: True)
    out = et.run_powershell("echo 1", capture=True)
    assert out == "ok"
    assert len(calls) >= 3


def test_smart_terminate(monkeypatch):
    killed = {}
    monkeypatch.setattr(et.security, "kill_process", lambda pid: killed.setdefault("kill", []).append(pid) or True)
    monkeypatch.setattr(et.security, "kill_process_tree", lambda pid: killed.setdefault("tree", []).append(pid) or True)

    class Dummy:
        def __init__(self):
            self.pid = 123
        def terminate(self):
            raise OSError("nope")
        def wait(self, timeout=None):
            raise OSError

    proc = Dummy()
    assert et.smart_terminate(proc) is True
    assert killed["kill"] == [123]


def test_smart_launch_exe_background(monkeypatch):
    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))

    called = []
    monkeypatch.setattr(et.security, "run_command_background", lambda cmd: called.append(cmd) or True)

    proc = et.smart_launch_exe(Path(sys.executable))
    assert proc is not None
    assert called


def test_run_powershell_wsl(monkeypatch):
    calls = []

    def fake_run(cmd, capture=False):
        calls.append(cmd)
        if cmd and cmd[0] == "wsl":
            return "ok"
        return None

    monkeypatch.setattr(et.platform, "system", lambda: "Windows")
    monkeypatch.setattr(et.security, "_run", fake_run)
    monkeypatch.setattr(et.Path, "is_file", lambda self: False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(et.shutil, "which", lambda name: "/bin/wsl" if name == "wsl" else None)
    out = et.run_powershell("echo 1", capture=True)
    assert out == "ok"
    assert any(call[0] == "wsl" for call in calls)


def test_run_powershell_pshome(monkeypatch, tmp_path):
    exe = tmp_path / "powershell.exe"
    exe.write_text("")

    calls = []

    def fake_run(cmd, capture=False):
        calls.append(cmd)
        if exe in map(Path, cmd):
            return "ok"
        return None

    monkeypatch.setattr(et.platform, "system", lambda: "Windows")
    monkeypatch.setattr(et.security, "_run", fake_run)
    monkeypatch.setenv("PSHOME", str(tmp_path))
    out = et.run_powershell("echo 1", capture=True)
    assert out == "ok"
    assert any(str(exe) in cmd for cmd in calls)


def test_run_powershell_env(monkeypatch, tmp_path):
    exe = tmp_path / "pwsh.exe"
    exe.write_text("")

    calls = []

    def fake_run(cmd, capture=False):
        calls.append(cmd)
        if exe in map(Path, cmd):
            return "ok"
        return None

    monkeypatch.setattr(et.platform, "system", lambda: "Windows")
    monkeypatch.setattr(et.security, "_run", fake_run)
    monkeypatch.setenv("POWERSHELL_EXE", str(exe))
    out = et.run_powershell("echo 1", capture=True)
    assert out == "ok"
    assert calls[0][0] == str(exe)


def test_js_fallback(monkeypatch, tmp_path):
    script = tmp_path / "test.js"
    script.write_text("")
    called = []

    def fake_popen(args, **kwargs):
        called.append(args)
        if args[0] in {"wscript", "cscript"}:
            raise OSError("fail")
        class Dummy:
            def poll(self):
                return None
        return Dummy()

    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", fake_popen)
    monkeypatch.setattr(et.platform, "system", lambda: "Windows")

    proc = et.smart_launch_exe(script)
    assert proc is not None
    assert any(args[0] in {"wscript", "cscript"} for args in called)


def test_js_node_fallback(monkeypatch, tmp_path):
    script = tmp_path / "node_test.js"
    script.write_text("")
    called = []

    def fake_popen(args, **kwargs):
        called.append(args)
        if args[0] in {"wscript", "cscript"}:
            raise OSError("fail")
        class Dummy:
            def poll(self):
                return None
        return Dummy()

    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", fake_popen)
    monkeypatch.setattr(et.platform, "system", lambda: "Linux")
    monkeypatch.setattr(et.shutil, "which", lambda name: "/usr/bin/node" if name in {"node", "nodejs"} else None)

    proc = et.smart_launch_exe(script)
    assert proc is not None
    assert any(args[0] == "/usr/bin/node" for args in called)


def test_startfile_fallback(monkeypatch):
    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et.platform, "system", lambda: "Windows")

    started = {}

    def fake_startfile(p):
        started["path"] = p

    monkeypatch.setattr(et.os, "startfile", fake_startfile, raising=False)

    proc = et.smart_launch_exe(Path(sys.executable))
    assert proc is not None
    assert started["path"]


def test_spawn_detached_fallback(monkeypatch):
    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et.security, "run_command_background", lambda *_a, **_k: False)

    spawned = []

    def fake_spawn(args):
        spawned.append(args)

    monkeypatch.setattr(et, "spawn_detached", fake_spawn)

    proc = et.smart_launch_exe(Path(sys.executable))
    assert proc is not None
    assert spawned


def test_chmod_retry(monkeypatch):
    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))

    calls = []

    def fake_run(cmd, capture=False):
        calls.append(cmd)
        return True

    monkeypatch.setattr(et.security, "_run", fake_run)
    monkeypatch.setattr(et.platform, "system", lambda: "Linux")
    monkeypatch.setattr(et.os, "access", lambda *a, **k: False)

    monkeypatch.setattr(et, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))

    proc = et.smart_launch_exe(Path("/tmp/foo"))
    assert proc is not None
    assert any(c[0] == "chmod" for c in calls)


def test_run_powershell_non_windows(monkeypatch):
    ran = {}

    def fake_run(cmd, capture=False):
        ran["cmd"] = cmd
        return "ok"

    monkeypatch.setattr(et.platform, "system", lambda: "Linux")
    monkeypatch.setattr(et.shutil, "which", lambda name: "/bin/pwsh" if name == "pwsh" else None)
    monkeypatch.setattr(et.subprocess, "run", lambda *a, **k: argparse.Namespace(returncode=0, stdout="ok"))
    out = et.run_powershell("echo 1", capture=True)
    assert out == "ok"


def test_msi_fallback(monkeypatch, tmp_path):
    msi = tmp_path / "test.msi"
    msi.write_text("")

    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))

    called = {}

    def fake_popen(args, **kwargs):
        called["args"] = args
        class Dummy:
            def poll(self):
                return None
        return Dummy()

    monkeypatch.setattr(et, "Popen", fake_popen)
    monkeypatch.setattr(et.platform, "system", lambda: "Windows")

    proc = et.smart_launch_exe(msi)
    assert proc is not None
    assert called["args"][0] == "msiexec"


def test_wsf_fallback(monkeypatch, tmp_path):
    script = tmp_path / "test.wsf"
    script.write_text("")

    called = []

    popen_calls = 0

    def fake_popen(args, **kwargs):
        nonlocal popen_calls
        called.append(args)
        popen_calls += 1
        if popen_calls == 1:
            raise OSError("fail")
        class Dummy:
            def poll(self):
                return None
        return Dummy()

    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", fake_popen)
    monkeypatch.setattr(et.platform, "system", lambda: "Windows")

    proc = et.smart_launch_exe(script)
    assert proc is not None
    assert any(args[0] in {"wscript", "cscript"} for args in called)


def test_appimage_fallback(monkeypatch, tmp_path):
    exe = tmp_path / "app.AppImage"
    exe.write_text("")

    called = []

    popen_calls = 0

    def fake_popen(args, **kwargs):
        nonlocal popen_calls
        called.append(args)
        popen_calls += 1
        if popen_calls == 1:
            raise OSError("fail")
        class Dummy:
            def poll(self):
                return None
        return Dummy()

    run_calls = []
    monkeypatch.setattr(et, "launch_exe", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    monkeypatch.setattr(et, "Popen", fake_popen)
    monkeypatch.setattr(et.platform, "system", lambda: "Linux")
    monkeypatch.setattr(et.security, "_run", lambda cmd, capture=False: run_calls.append(cmd) or True)

    proc = et.smart_launch_exe(exe)
    assert proc is not None
    assert any(args[0] == str(exe) for args in called)
    assert any(c[0] == "chmod" for c in run_calls)
