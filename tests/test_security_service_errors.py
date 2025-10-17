import platform

from coolbox.utils import firewall, defender


def test_firewall_service_error(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(firewall, "ensure_admin", lambda: True)
    monkeypatch.setattr(
        firewall, "_services_ok", lambda: (False, "BFE not running")
    )
    ok, err = firewall.set_firewall_enabled(True)
    assert ok is False
    assert isinstance(err, str)
    assert "BFE not running" in err


def test_defender_service_error(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(defender, "ensure_admin", lambda: True)
    monkeypatch.setattr(defender, "is_defender_supported", lambda: True)
    monkeypatch.setattr(
        defender, "_defender_services_ok", lambda: (False, "WinDefend not running")
    )
    monkeypatch.setattr(defender, "_third_party_av_present", lambda: False)
    ok, err = defender.set_defender_enabled(True)
    assert ok is False
    assert isinstance(err, str)
    assert "WinDefend not running" in err

