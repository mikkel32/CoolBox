import tempfile
import json
from pathlib import Path

from src.config import Config


def test_recent_files_limit(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    for i in range(15):
        cfg.add_recent_file(f"file{i}.txt")
    assert len(cfg.get("recent_files")) == cfg.get("max_recent_files")


def test_clear_cache(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (cfg.cache_dir / f"tmp{i}.txt").write_text("x")
    removed = cfg.clear_cache()
    assert removed == 3
    assert not any(cfg.cache_dir.iterdir())


def test_reset_to_defaults(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("font_size", 99)
    cfg.reset_to_defaults()
    assert cfg.get("font_size") == cfg.defaults["font_size"]
    assert cfg.get("ui_scale") == cfg.defaults["ui_scale"]
    assert cfg.get("font_family") == cfg.defaults["font_family"]


def test_default_scan_concurrency(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("scan_concurrency") == 100


def test_new_scan_defaults(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("scan_services") is False
    assert cfg.get("scan_banner") is False
    assert cfg.get("scan_latency") is False
    assert cfg.get("scan_ping") is False
    assert cfg.get("scan_ping_timeout") == 1.0
    assert cfg.get("scan_ping_concurrency") == 100


def test_add_recent_file_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = Config()
    cfg.add_recent_file("x.txt")
    assert "x.txt" in json.loads(cfg.config_file.read_text())["recent_files"]


def test_menu_default(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("show_menu") is True


def test_show_splash_default(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("show_splash") is True


def test_use_system_accent_default(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("use_system_accent") is False


def test_use_system_accent_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("use_system_accent", True)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("use_system_accent") is True


def test_force_quit_defaults(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("force_quit_cpu_alert") == 80.0
    assert cfg.get("force_quit_mem_alert") == 500.0
    assert cfg.get("force_quit_auto_kill") == "none"
    assert cfg.get("force_quit_sort") == "CPU"
    assert cfg.get("force_quit_sort_reverse") is True
    assert cfg.get("force_quit_on_top") is False
    assert cfg.get("force_quit_adaptive") is True
    assert cfg.get("force_quit_adaptive_detail") is True
    assert cfg.get("force_quit_conn_interval") == 2.0
    assert cfg.get("force_quit_file_interval") == 2.0
    assert cfg.get("force_quit_cache_ttl") == 30.0
    assert cfg.get("force_quit_conn_global") == 50
    assert cfg.get("force_quit_file_global") == 50
    assert cfg.get("force_quit_stable_cycles") == 10
    assert cfg.get("force_quit_stable_skip") == 3
    assert cfg.get("force_quit_change_window") == 3
    assert cfg.get("force_quit_change_cpu") == 0.5
    assert cfg.get("force_quit_change_mem") == 1.0
    assert cfg.get("force_quit_change_io") == 0.5
    assert cfg.get("force_quit_change_score") == 1.0
    assert cfg.get("force_quit_visible_cpu") == 0.5
    assert cfg.get("force_quit_visible_mem") == 10.0
    assert cfg.get("force_quit_visible_io") == 0.1
    assert cfg.get("force_quit_visible_auto") is False
    assert cfg.get("force_quit_warn_cpu") == 40.0
    assert cfg.get("force_quit_warn_mem") == 200.0
    assert cfg.get("force_quit_warn_io") == 1.0
    assert cfg.get("force_quit_hide_system") is False
    assert cfg.get("force_quit_slow_ratio") == 0.02
    assert cfg.get("force_quit_fast_ratio") == 0.2
    assert cfg.get("force_quit_ratio_window") == 5
    assert cfg.get("force_quit_trend_window") == 5
    assert cfg.get("force_quit_trend_cpu") == 5.0
    assert cfg.get("force_quit_trend_mem") == 50.0
    assert cfg.get("force_quit_trend_io") == 1.0
    assert cfg.get("force_quit_trend_io_window") == 5
    assert cfg.get("force_quit_trend_slow_ratio") == 0.05
    assert cfg.get("force_quit_trend_fast_ratio") == 0.25
    assert cfg.get("force_quit_show_trends") is True
    assert cfg.get("force_quit_show_stable") is False
    assert cfg.get("force_quit_show_deltas") is True
    assert cfg.get("force_quit_show_normal") is False
    assert cfg.get("force_quit_show_score") is False
    assert cfg.get("force_quit_ignore_age") == 1.0
    assert cfg.get("force_quit_change_agg") == 1
    assert cfg.get("force_quit_change_alpha") == 0.2
    assert cfg.get("force_quit_change_ratio") == 0.3
    assert cfg.get("force_quit_change_std_mult") == 2.0
    assert cfg.get("force_quit_change_mad_mult") == 3.0
    assert cfg.get("force_quit_change_decay") == 0.8
    assert cfg.get("force_quit_normal_window") == 3
    assert cfg.get("force_quit_exclude_users") == []


def test_force_quit_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("force_quit_cpu_alert", 90.0)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("force_quit_cpu_alert") == 90.0


def test_force_quit_sort_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("force_quit_sort", "Memory")
    cfg.set("force_quit_sort_reverse", False)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("force_quit_sort") == "Memory"
    assert cfg2.get("force_quit_sort_reverse") is False


def test_force_quit_window_size_defaults(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("force_quit_width") == 1000
    assert cfg.get("force_quit_height") == 650


def test_force_quit_window_size_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("force_quit_width", 1111)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("force_quit_width") == 1111


def test_ui_scale_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("ui_scale", 1.25)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("ui_scale") == 1.25


def test_font_family_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("font_family", "Courier")
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("font_family") == "Courier"


def test_show_splash_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("show_splash", False)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("show_splash") is False


def test_enable_animations_default(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    assert cfg.get("enable_animations") is True


def test_enable_animations_persist(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(Path, "home", lambda: tmp)
    cfg = Config()
    cfg.set("enable_animations", False)
    cfg.save()
    cfg2 = Config()
    assert cfg2.get("enable_animations") is False
