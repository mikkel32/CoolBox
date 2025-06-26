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
