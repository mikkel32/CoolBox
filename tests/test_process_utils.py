import subprocess
import asyncio
from src.utils.process_utils import (
    run_command,
    run_command_async,
    run_command_ex,
    run_command_async_ex,
    run_command_background,
)


def test_run_command_capture(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "ok")
    assert run_command(["cmd"], capture=True) == "ok"


def test_run_command_no_check(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1)
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_command(["fail"], check=False) == ""


def test_run_command_failure(monkeypatch):
    def fake_run(*a, **k):
        raise RuntimeError("bad")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_command(["oops"], check=False) is None


def test_run_command_async_capture(monkeypatch):
    class DummyProc:
        returncode = 0

        async def communicate(self):
            return b"ok", b""

    async def fake_exec(*args, **kwargs):
        return DummyProc()

    async def fake_wait_for(coro, timeout):
        return await coro

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    assert asyncio.run(run_command_async(["cmd"], capture=True)) == "ok"


def test_run_command_async_no_check(monkeypatch):
    class DummyProc:
        returncode = 1

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        return DummyProc()

    async def fake_wait_for(coro, timeout):
        return await coro

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    assert asyncio.run(run_command_async(["fail"], check=False)) == ""


def test_run_command_async_failure(monkeypatch):
    async def fake_exec(*a, **k):
        raise RuntimeError("bad")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(run_command_async(["oops"], check=False)) is None


def test_run_command_ex(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="done")

    monkeypatch.setattr(subprocess, "run", fake_run)

    out, code = run_command_ex(["cmd"], capture=True)
    assert out == "done"
    assert code == 0


def test_run_command_ex_failure(monkeypatch):
    def fake_run(*a, **k):
        raise OSError("fail")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out, code = run_command_ex(["cmd"])  # pragma: no cover - handles failure
    assert out is None and code is None


def test_run_command_async_ex(monkeypatch):
    class DummyProc:
        returncode = 0

        async def communicate(self):
            return b"done", b""

    async def fake_exec(*a, **k):
        return DummyProc()

    async def fake_wait_for(coro, timeout):
        return await coro

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    out, code = asyncio.run(run_command_async_ex(["cmd"], capture=True))
    assert out == "done" and code == 0


def test_run_command_background(monkeypatch):
    captured = {}

    def fake_popen(
        args,
        stdout=None,
        stderr=None,
        creationflags=0,
        start_new_session=False,
        cwd=None,
        env=None,
    ):
        captured["args"] = args
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["flags"] = creationflags
        captured["session"] = start_new_session
        captured["cwd"] = cwd
        captured["env"] = env

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    assert run_command_background(["cmd"]) is True
    assert captured["args"] == ["cmd"]
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert captured["session"] is False


def test_run_command_background_env_cwd(monkeypatch, tmp_path):
    captured = {}

    def fake_popen(args, stdout=None, stderr=None, creationflags=0,
                   start_new_session=False, cwd=None, env=None):
        captured.update({"cwd": cwd, "env": env})

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    env = {"FOO": "BAR"}
    cwd = tmp_path
    assert run_command_background(["cmd"], cwd=str(cwd), env=env)
    assert captured["cwd"] == str(cwd)
    assert captured["env"] == env


def test_run_command_custom_env_cwd(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    env = {"FOO": "BAR"}
    cwd = tmp_path
    run_command(["echo"], cwd=str(cwd), env=env)
    assert captured.get("cwd") == str(cwd)
    assert captured.get("env") == env
