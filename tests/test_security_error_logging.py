import subprocess

import coolbox.utils.firewall as firewall
import coolbox.utils.defender as defender
from coolbox.utils.security import run_command_background
from coolbox.app import error_handler as eh


def _boom_run(*args, **kwargs):  # pragma: no cover - helper to force errors
    raise FileNotFoundError("nope")


def test_firewall_run_ex_records(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _boom_run)
    eh.RECENT_ERRORS.clear()
    out, rc = firewall._run_ex(["foo"])
    assert rc == -1 and "FileNotFoundError" in out
    assert any("FileNotFoundError" in e for e in eh.RECENT_ERRORS)


def test_defender_run_ex_records(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _boom_run)
    eh.RECENT_ERRORS.clear()
    out, rc = defender._run_ex(["foo"])
    assert rc == -1 and "FileNotFoundError" in out
    assert any("FileNotFoundError" in e for e in eh.RECENT_ERRORS)


def test_run_command_background_records(monkeypatch):
    def boom_popen(*args, **kwargs):  # pragma: no cover - helper
        raise OSError("fail")

    monkeypatch.setattr(subprocess, "Popen", boom_popen)
    eh.RECENT_ERRORS.clear()
    ok, proc = run_command_background(["foo"])
    assert ok is False and proc is None
    assert any("OSError" in e for e in eh.RECENT_ERRORS)


def test_run_ex_exit_code_message(monkeypatch):
    class CP:
        stdout = ""
        stderr = ""
        returncode = 7

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: CP())
    out, rc = firewall._run_ex(["foo", "bar"])
    assert rc == 7 and "exited with code 7" in out and "foo bar" in out


def test_ps_exit_code_message(monkeypatch):
    class CP:
        stdout = ""
        stderr = ""
        returncode = 3

    monkeypatch.setattr(defender.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: CP())
    out, rc = defender._ps("Get-Thing")
    assert rc == 3 and "exited with code 3" in out

