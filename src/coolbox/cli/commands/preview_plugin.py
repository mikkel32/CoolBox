"""Launch a plugin preview sandbox inside the VM/debug tooling."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace

from coolbox.utils import launch_vm_debug


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = ArgumentParser(description="Launch a plugin preview sandbox")
    parser.add_argument("plugin", help="Plugin identifier to preview")
    parser.add_argument(
        "--manifest",
        help="Optional path to the manifest containing the plugin",
    )
    parser.add_argument(
        "--profile",
        help="Profile name within the manifest to boot",
    )
    parser.add_argument(
        "--prefer",
        choices=["docker", "vagrant", "auto"],
        default="auto",
        help="Preferred backend (docker or vagrant)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5678,
        help="Debug port to use when launching the preview",
    )
    parser.add_argument(
        "--open-code",
        dest="open_code",
        action="store_true",
        help="Open VS Code once the environment starts",
    )
    parser.add_argument(
        "--skip-deps",
        dest="skip_deps",
        action="store_true",
        help="Skip installing dependencies in the debug environment",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    launch_vm_debug(
        prefer=args.prefer if args.prefer != "auto" else None,
        open_code=args.open_code,
        port=args.port,
        skip_deps=args.skip_deps,
        preview_plugin=args.plugin,
        preview_manifest=args.manifest,
        preview_profile=args.profile,
    )


if __name__ == "__main__":
    main()

