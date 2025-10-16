from __future__ import annotations

import sys
from pathlib import Path

from src.setup import stages


def _write_requirement_file(tmp_path: Path, lines: list[str]) -> Path:
    req = tmp_path / "requirements.txt"
    req.write_text("\n".join(lines), encoding="utf-8")
    return req


def _create_dist(site: Path, name: str, version: str) -> None:
    dist = site / f"{name}-{version}.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    metadata = dist / "METADATA"
    metadata.write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")


def test_missing_requirements_uses_metadata_paths(tmp_path: Path) -> None:
    site = tmp_path / "venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site.mkdir(parents=True)
    _create_dist(site, "customtkinter", "5.2.2")

    req_path = _write_requirement_file(
        tmp_path,
        [
            "customtkinter>=5.2.1",
            "rich>=13.0.0",
        ],
    )

    missing = stages._missing_requirements(req_path, metadata_paths=[site])
    assert missing == ["rich>=13.0.0"]


def test_missing_requirements_skips_unmatched_markers(tmp_path: Path) -> None:
    site = tmp_path / "venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    site.mkdir(parents=True)
    _create_dist(site, "requests", "2.31.0")

    req_path = _write_requirement_file(
        tmp_path,
        [
            "requests>=2.0",
            "python-xlib>=0.33; platform_system=='Linux'",
            "pyobjc>=8.0; sys_platform=='darwin'",
        ],
    )

    missing = stages._missing_requirements(req_path, metadata_paths=[site])
    assert missing == ["python-xlib>=0.33; platform_system=='Linux'"]
