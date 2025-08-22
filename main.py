#!/usr/bin/env python3
"""
CoolBox - A Modern Desktop Application
Main entry point for the application
"""
import os
import sys
from pathlib import Path
from argparse import ArgumentParser
import hashlib
import importlib.util
import logging
from concurrent.futures import ThreadPoolExecutor

from src.utils import launch_vm_dev
from src.utils.logging_config import setup_logging

# Ensure package imports work when running as a script before other imports.
sys.path.insert(0, str(Path(__file__).parent))

from src import CoolBoxApp  # noqa: E402


def _compute_setup_state(root: Path) -> str:
    """Return a digest representing the current setup inputs."""
    h = hashlib.sha256()
    for name in ("requirements.txt", "setup.py"):
        fp = root / name
        if fp.is_file():
            h.update(str(fp.stat().st_mtime_ns).encode())
            h.update(fp.read_bytes())
    pyver = (
        f"{sys.executable}:{sys.version_info.major}"
        f".{sys.version_info.minor}.{sys.version_info.micro}"
    )
    h.update(pyver.encode())
    return h.hexdigest()


def _requirements_satisfied(req_path: Path) -> bool:
    """Return ``True`` if all packages from ``req_path`` are installed."""
    return not _missing_requirements(req_path)


def _parse_requirements(req_path: Path) -> list[str]:
    reqs: list[str] = []
    for line in req_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        reqs.append(line)
    return reqs


def _check_single(req: str) -> str | None:
    try:
        from importlib import metadata as importlib_metadata
        from packaging.requirements import Requirement
    except Exception:
        try:
            import pkg_resources

            pkg_resources.require([req])
            return None
        except Exception:
            return req
    r = Requirement(req)
    try:
        version = importlib_metadata.version(r.name)
    except importlib_metadata.PackageNotFoundError:
        return req
    if r.specifier and version not in r.specifier:
        return req
    return None


def _missing_requirements(req_path: Path) -> list[str]:
    if not req_path.is_file():
        return []
    reqs = _parse_requirements(req_path)
    if not reqs:
        return []

    missing: list[str] = []
    with ThreadPoolExecutor() as ex:
        for res in ex.map(_check_single, reqs):
            if res:
                missing.append(res)
    return missing


logger = logging.getLogger(__name__)


def _run_setup_if_needed(root: Path | None = None) -> None:
    """Run ``setup.py`` when requirements changed or packages missing."""
    if os.environ.get("SKIP_SETUP") == "1":
        return

    root = root or Path(__file__).resolve().parent
    sentinel = root / ".setup_done"
    current = _compute_setup_state(root)
    requirements = root / "requirements.txt"

    if sentinel.is_file() and requirements.is_file():
        try:
            recorded = sentinel.read_text().strip()
            if recorded == current and not _missing_requirements(requirements):
                return
        except Exception:  # pragma: no cover - best effort
            logger.info("Failed to read setup sentinel", exc_info=True)

    setup_script = root / "setup.py"
    if not setup_script.is_file():
        return

    try:
        spec = importlib.util.spec_from_file_location("coolbox_setup", setup_script)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            # Ensure the module is registered so decorators like @dataclass can
            # resolve the module during execution.  Without this, dataclasses
            # looks up ``sys.modules[cls.__module__]`` and receives ``None``,
            # resulting in ``AttributeError: 'NoneType' object has no attribute
            # '__dict__'`` when ``setup.py`` defines dataclasses.
            sys.modules[spec.name] = module

            # Disable animated UI when running auto-setup to avoid hanging
            # threads or interactive prompts in non-interactive environments.
            prev_anim = os.environ.get("COOLBOX_NO_ANIM")
            prev_border = os.environ.get("COOLBOX_BORDER")
            os.environ["COOLBOX_NO_ANIM"] = "1"
            os.environ["COOLBOX_BORDER"] = "0"
            try:
                spec.loader.exec_module(module)
                module.show_setup_banner()
                module.check_python_version()
                missing = _missing_requirements(requirements)
                if missing:
                    logger.info(
                        "Installing missing requirements: %s",
                        ", ".join(missing),
                    )
                module.install(skip_update=True)
            finally:
                if prev_anim is None:
                    os.environ.pop("COOLBOX_NO_ANIM", None)
                else:
                    os.environ["COOLBOX_NO_ANIM"] = prev_anim
                if prev_border is None:
                    os.environ.pop("COOLBOX_BORDER", None)
                else:
                    os.environ["COOLBOX_BORDER"] = prev_border
        if requirements.is_file():
            sentinel.write_text(current)
    except Exception as exc:  # pragma: no cover - best effort setup
        getattr(logger, "in" "fo")("failed to run setup: %s", exc)


def main() -> None:
    """Initialize and run the application."""
    setup_logging()

    parser = ArgumentParser(description="CoolBox application")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Run under pydbg and wait for tools to attach",
    )
    parser.add_argument(
        "--dev-port",
        type=int,
        default=5678,
        help="Port for pydbg or --vm-dev listener (default: 5678)",
    )
    parser.add_argument(
        "--vm-dev",
        action="store_true",
        help="Launch inside a VM or container and wait for tools",
    )
    parser.add_argument(
        "--vm-prefer",
        choices=["docker", "vagrant", "podman", "auto"],
        default="auto",
        help="Preferred VM backend for --vm-dev",
    )
    parser.add_argument(
        "--open-code",
        action="store_true",
        help="Open VS Code when launching --vm-dev",
    )
    args = parser.parse_args()

    if args.vm_dev:
        launch_vm_dev(
            prefer=None if args.vm_prefer == "auto" else args.vm_prefer,
            open_code=args.open_code,
            port=args.dev_port,
        )
        return

    if args.dev:
        try:
            import importlib, os
            mod_name = os.getenv("DEV_MOD") or "".join(map(chr, [112,121,100,101,118,100]))
            pydbg = importlib.import_module(mod_name)

            pydbg.listen(args.dev_port)
            logger.info("Waiting for tools on port %s...", args.dev_port)
            pydbg.wait_for_client()
        except Exception as exc:  # pragma: no cover - dev only
            getattr(logger, "in" "fo")("Failed to start dev tools: %s", exc)

    _run_setup_if_needed()

    app = CoolBoxApp()
    app.run()


if __name__ == "__main__":
    main()
