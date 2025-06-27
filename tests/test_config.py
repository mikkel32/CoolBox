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
