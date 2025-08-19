import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "security", Path(__file__).resolve().parents[1] / "src/utils/security.py"
)
security = importlib.util.module_from_spec(spec)
import sys
sys.modules["security"] = security
spec.loader.exec_module(security)


def test_is_firewall_enabled_true(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(security.os.path, "exists", lambda p: True)
    def fake_run(cmd, timeout=30):
        return security.RunResult(0, "State ON\nState ON", "")
    monkeypatch.setattr(security, "_run", fake_run)
    assert security.is_firewall_enabled() is True


def test_set_firewall_enabled_calls_netsh(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_NETSH_EXE", "netsh")
    monkeypatch.setattr(security, "is_admin", lambda: True)
    monkeypatch.setattr(security.os.path, "exists", lambda p: True)
    sent = {}
    def fake_run(cmd, timeout=30):
        sent["cmd"] = cmd
        return security.RunResult(0, "", "")
    monkeypatch.setattr(security, "_run", fake_run)
    monkeypatch.setattr(security, "is_firewall_enabled", lambda: True)
    assert security.set_firewall_enabled(True) is True
    assert sent["cmd"][:5] == ["netsh", "advfirewall", "set", "allprofiles", "state"]


def test_get_defender_status(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "_run_ps", lambda s, timeout=30: security.RunResult(0, '{"Realtime":true,"AS":true,"AV":true,"Tamper":false}', ""))
    monkeypatch.setattr(security, "defender_service_status", lambda: "RUNNING")
    st = security.get_defender_status()
    assert st.realtime_enabled is True
    assert st.tamper_protection is False


def test_set_defender_realtime(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    cmds = {}
    def fake_run_ps(script, timeout=30):
        cmds["script"] = script
        return security.RunResult(0, "", "")
    monkeypatch.setattr(security, "_run_ps", fake_run_ps)
    monkeypatch.setattr(security, "get_defender_status", lambda: security.DefenderStatus("RUNNING", True, True, True, True))
    assert security.set_defender_realtime(True) is True
    assert "DisableRealtimeMonitoring False" in cmds["script"]


def test_set_defender_enabled(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    called = {}
    monkeypatch.setattr(security, "ensure_defender_autostart", lambda: called.setdefault("auto", True))
    monkeypatch.setattr(security, "start_defender_service", lambda: called.setdefault("start", True))
    monkeypatch.setattr(security, "set_defender_realtime", lambda v: called.setdefault("rt", v))
    assert security.set_defender_enabled(True) is True
    assert called == {"auto": True, "start": True, "rt": True}


def test_set_defender_enabled_disable(monkeypatch):
    monkeypatch.setattr(security, "_IS_WINDOWS", True)
    monkeypatch.setattr(security, "is_admin", lambda: True)
    called = {}
    monkeypatch.setattr(security, "stop_defender_service", lambda: called.setdefault("stop", True))
    assert security.set_defender_enabled(False) is True
    assert called["stop"] is True
