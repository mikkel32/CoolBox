"""CLI utilities for managing tool orchestration recipes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Mapping

from rich.console import Console
from rich.table import Table

from coolbox.tools import ToolRecipeLoader, ToolRecipeSigner

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage signed tool recipes")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List recipes in a directory")
    list_parser.add_argument("path", nargs="?", default=".", help="Directory to scan for recipes")

    inspect_parser = sub.add_parser("inspect", help="Show details for a recipe")
    inspect_parser.add_argument("recipe", help="Recipe file to inspect")
    inspect_parser.add_argument(
        "--key",
        action="append",
        default=[],
        metavar="KEYID=SECRET",
        help="Signing key used to verify the recipe",
    )

    verify_parser = sub.add_parser("verify", help="Verify recipe signatures")
    verify_parser.add_argument("recipe", help="Recipe file to verify")
    verify_parser.add_argument(
        "--key",
        action="append",
        required=True,
        metavar="KEYID=SECRET",
        help="Signing key material",
    )

    sign_parser = sub.add_parser("sign", help="Apply a signature to a recipe")
    sign_parser.add_argument("recipe", help="Recipe document to sign")
    sign_parser.add_argument("--output", "-o", help="Output path for the signed recipe")
    sign_parser.add_argument("--key", required=True, help="Secret used to sign the recipe")
    sign_parser.add_argument("--key-id", required=True, help="Identifier of the signing key")

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "list":
        return _cmd_list(Path(args.path))
    if args.command == "inspect":
        return _cmd_inspect(Path(args.recipe), args.key)
    if args.command == "verify":
        return _cmd_verify(Path(args.recipe), args.key)
    if args.command == "sign":
        return _cmd_sign(Path(args.recipe), args.key, args.key_id, args.output)
    parser.error(f"Unknown command: {args.command}")
    return 2


def _cmd_list(root: Path) -> int:
    directory = root.resolve()
    if not directory.exists():
        console.print(f"[red]Directory {directory} does not exist[/red]")
        return 1
    table = Table(title=f"Recipes in {directory}")
    table.add_column("Recipe")
    table.add_column("Size", justify="right")
    table.add_column("Modified")
    found = False
    for entry in sorted(directory.iterdir()):
        if entry.suffix.lower() != ".json":
            continue
        found = True
        stat = entry.stat()
        table.add_row(entry.name, f"{stat.st_size} B", _format_mtime(stat.st_mtime))
    if not found:
        console.print(f"[yellow]No recipes found in {directory}[/yellow]")
        return 0
    console.print(table)
    return 0


def _cmd_inspect(path: Path, key_entries: list[str]) -> int:
    signer = _build_signer(key_entries) if key_entries else None
    loader = ToolRecipeLoader(signer=signer, require_signature=False)
    recipe = loader.load(path)
    table = Table(title=f"Recipe: {recipe.name}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Version", str(recipe.version))
    table.add_row("Source", str(recipe.source) if recipe.source else "(unspecified)")
    table.add_row("Metadata", json.dumps(recipe.metadata, indent=2) if recipe.metadata else "{}")
    clause_table = Table(title="Clauses", show_header=True, header_style="bold magenta")
    clause_table.add_column("#")
    clause_table.add_column("Name")
    clause_table.add_column("When")
    clause_table.add_column("Map steps")
    clause_table.add_column("Guard")
    for index, clause in enumerate(recipe.clauses, start=1):
        clause_table.add_row(
            str(index),
            clause.name or "(anonymous)",
            json.dumps(clause.when, ensure_ascii=False) if clause.when is not None else "-",
            str(len(clause.map_steps)),
            json.dumps(clause.guard, ensure_ascii=False) if clause.guard is not None else "-",
        )
    console.print(table)
    console.print(clause_table)
    if signer is not None:
        console.print("[green]Signature verification succeeded[/green]")
    return 0


def _cmd_verify(path: Path, key_entries: list[str]) -> int:
    signer = _build_signer(key_entries)
    loader = ToolRecipeLoader(signer=signer, require_signature=True)
    loader.load(path)
    console.print(f"[green]Recipe {path} verified successfully[/green]")
    return 0


def _cmd_sign(path: Path, secret: str, key_id: str, output: str | None) -> int:
    signer = ToolRecipeSigner({key_id: secret})
    loader = ToolRecipeLoader(signer=signer, require_signature=False)
    recipe = loader.load(path)
    target = Path(output) if output else path
    loader.dump(recipe, target, key_id=key_id)
    console.print(f"[green]Recipe signed and written to {target}[/green]")
    return 0


def _build_signer(entries: Iterable[str]) -> ToolRecipeSigner:
    secrets: dict[str, bytes] = {}
    for entry in entries:
        if "=" not in entry:
            raise SystemExit(f"Invalid key specification: {entry}. Expected KEYID=SECRET")
        key_id, secret = entry.split("=", 1)
        secrets[key_id.strip()] = secret.encode("utf-8")
    return ToolRecipeSigner(secrets)


def _format_mtime(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).isoformat(sep=" ", timespec="seconds")


if __name__ == "__main__":  # pragma: no cover - CLI hook
    raise SystemExit(main())
