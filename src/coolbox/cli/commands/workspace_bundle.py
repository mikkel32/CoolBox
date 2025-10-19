"""Export and import workspace bundles for reproducible bug reports."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Sequence

from coolbox.catalog import get_catalog
from coolbox.paths import artifacts_dir, ensure_directory


def _export_bundle(output: Path) -> Path:
    catalog = get_catalog()
    payload = catalog.export_bundle()
    ensure_directory(output.parent)
    root = artifacts_dir()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("catalog.json", json.dumps(payload, indent=2, sort_keys=True))
        if root.exists():
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(root)
                archive.write(path, f"artifacts/{relative.as_posix()}")
    return output


def _import_bundle(bundle: Path) -> None:
    catalog = get_catalog()
    root = artifacts_dir()
    with zipfile.ZipFile(bundle, "r") as archive:
        try:
            catalog_data = json.loads(archive.read("catalog.json").decode("utf-8"))
        except KeyError as exc:
            raise ValueError("Bundle is missing catalog.json") from exc
        catalog.import_bundle(catalog_data)
        for name in archive.namelist():
            if name.endswith("/") or not name.startswith("artifacts/"):
                continue
            target = root / Path(name).relative_to("artifacts")
            ensure_directory(target.parent)
            with archive.open(name) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage CoolBox workspace bundles")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Create a workspace bundle")
    export_parser.add_argument("output", type=Path, help="Target bundle path")

    import_parser = subparsers.add_parser("import", help="Restore a workspace bundle")
    import_parser.add_argument("bundle", type=Path, help="Bundle archive to import")

    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "export":
        path = Path(args.output)
        _export_bundle(path)
        print(f"Bundle written to {path}")
        return 0
    if args.command == "import":
        _import_bundle(Path(args.bundle))
        print(f"Bundle {args.bundle} imported")
        return 0
    raise ValueError(f"Unsupported command: {args.command}")


__all__ = ["main"]

