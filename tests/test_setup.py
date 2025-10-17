import importlib
import json
import os
import sys
import subprocess
import time
from pathlib import Path

import pytest

import setup
from src.setup import stages as setup_stages


def _prepare_smart_setup(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_ROOT", str(tmp_path))
    monkeypatch.setenv("COOLBOX_VENV", str(tmp_path / "venv"))
    monkeypatch.setenv("COOLBOX_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("COOLBOX_OFFLINE", raising=False)
    (tmp_path / "venv").mkdir(parents=True, exist_ok=True)
    importlib.reload(setup)
    setup.set_offline(False)
    setup.SUMMARY.warnings.clear()
    python_path = Path(setup._venv_python())
    python_path.parent.mkdir(parents=True, exist_ok=True)
    python_path.write_text("", encoding="utf-8")
    for candidate in setup_stages._candidate_site_packages(Path(setup.get_venv_dir())):
        candidate.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        setup,
        "_probe_connectivity",
        lambda timeout=setup.CONNECTIVITY_PROBE_TIMEOUT: setup.ConnectivityProbe(
            attempted=False,
            reachable=None,
            host=setup._connectivity_host(),
            latency_ms=None,
            error="probe skipped in tests",
        ),
    )


def test_get_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_ROOT", str(tmp_path))
    importlib.reload(setup)
    assert setup.get_root() == tmp_path


def test_locate_root_search(tmp_path):
    root = tmp_path / "project"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "requirements.txt").write_text("")
    assert setup.locate_root(sub) == root


def test_get_venv_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_VENV", str(tmp_path / "v"))
    importlib.reload(setup)
    assert setup.get_venv_dir() == tmp_path / "v"


def test_pip_invokes_run(monkeypatch):
    border_calls = []

    class DummyBorder:
        def __enter__(self):
            border_calls.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            border_calls.append("exit")

    run_calls = []

    def fake_run(cmd, **kw):
        run_calls.append(cmd)

    monkeypatch.setattr(setup, "NeonPulseBorder", DummyBorder)
    monkeypatch.setattr(setup, "_run", fake_run)
    setup.set_offline(False)

    setup._pip(["install", "pkg"], python=sys.executable)

    assert border_calls == []
    assert run_calls and run_calls[0][:4] == [sys.executable, "-m", "pip", "install"]


def test_pip_offline_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("COOLBOX_OFFLINE", "1")
    importlib.reload(setup)

    run_calls: list[list[str]] = []
    env_calls: list[dict | None] = []

    def fake_run(cmd, env=None, **kw):
        run_calls.append(cmd)
        env_calls.append(env)

    monkeypatch.setattr(setup, "_run", fake_run)
    monkeypatch.setattr(setup, "_available_wheel_links", lambda: [str(tmp_path)])

    setup._pip(["install", "pkg"], python=sys.executable)

    assert run_calls, "pip should still run in offline mode"
    assert "--no-index" in run_calls[0]
    assert env_calls[0] is not None
    assert env_calls[0]["PIP_NO_INDEX"] == "1"


def test_cli_offline_flag(monkeypatch):
    monkeypatch.delenv("COOLBOX_OFFLINE", raising=False)
    importlib.reload(setup)
    setup.set_offline(False)
    monkeypatch.setattr(setup, "show_info", lambda: None)

    with pytest.raises(SystemExit):
        setup.main(["--offline", "info"])
    assert setup.is_offline() is True


@pytest.mark.parametrize(
    "platform, expected",
    [
        ("linux", Path("venv") / "bin" / "python"),
        ("darwin", Path("venv") / "bin" / "python"),
        ("win32", Path("venv") / "Scripts" / "python.exe"),
    ],
)
def test_venv_python_platform(monkeypatch, tmp_path, platform, expected):
    monkeypatch.setenv("COOLBOX_VENV", str(tmp_path / "venv"))
    monkeypatch.setattr(sys, "platform", platform)
    path = Path(setup._venv_python())
    assert path == (tmp_path / expected).resolve()


def test_setup_run_speed():
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "setup.py", "--help"],
        check=True,
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=5,
    )
    duration = time.perf_counter() - start
    assert duration < 5


def test_run_timeout():
    with pytest.raises(RuntimeError):
        setup._run([sys.executable, "-c", "import time; time.sleep(1)"], timeout=0.1)


def test_config_file_overrides(monkeypatch, tmp_path):
    cfg = tmp_path / ".coolboxrc"
    cfg.write_text("{""no_anim"": true}")
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib
    importlib.reload(setup)
    assert setup.CONFIG.no_anim is True


def test_build_smart_plan_detects_new_requirements(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.should_install is True
    assert plan.steps
    assert plan.steps[0].title == "Bootstrap pip"
    assert plan.steps[0].pip_args[0] == "install"
    assert plan.steps[-1].title == "Validate environment"
    assert plan.steps[-1].pip_args == ("check",)
    assert any("-r" in step.pip_args for step in plan.steps)
    assert any("stamp" in reason or "requirement" in reason for reason in plan.context.reasons)
    assert any("Python runtime" in insight for insight in plan.insights)
    assert any("pip check" in insight for insight in plan.insights)


def test_smart_plan_records_connectivity_probe(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    probe = setup.ConnectivityProbe(
        attempted=True,
        reachable=False,
        host="pypi.org",
        latency_ms=None,
        error="timed out",
    )
    monkeypatch.setattr(setup, "_probe_connectivity", lambda timeout=0.1: probe)
    setup.SUMMARY.warnings.clear()
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert any("Network probe: unreachable" in insight for insight in plan.insights)
    assert "network unreachable" in plan.context.reasons
    assert any(
        "Network probe failed" in warning for warning in setup.SUMMARY.warnings
    )


def test_smart_plan_reports_missing_venv(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    venv_dir = Path(setup.get_venv_dir())
    python_path = Path(setup._venv_python())
    if python_path.exists():
        python_path.unlink()
    if venv_dir.exists():
        for child in sorted(
            venv_dir.glob("**/*"), key=lambda p: len(p.parts), reverse=True
        ):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        venv_dir.rmdir()
    setup.SUMMARY.warnings.clear()
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.venv.exists is False
    assert any("Virtualenv" in insight for insight in plan.insights)
    assert any(
        "virtualenv" in warning.lower() for warning in setup.SUMMARY.warnings
    )


def test_smart_plan_low_disk_warning(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    diag = setup.VenvDiagnostics(
        root=Path(setup.get_venv_dir()),
        exists=True,
        python_path=Path(setup._venv_python()),
        python_exists=True,
        site_packages=tuple(
            Path(p)
            for p in setup_stages._candidate_site_packages(Path(setup.get_venv_dir()))
        ),
        missing_site_packages=(),
        writable=True,
        disk_total_bytes=10_000,
        disk_free_bytes=200,
        disk_percent_free=2.0,
    )
    monkeypatch.setattr(setup, "_gather_venv_diagnostics", lambda: diag)
    setup.SUMMARY.warnings.clear()
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert any("storage" in insight.lower() for insight in plan.insights)
    assert any("disk space" in warning.lower() for warning in setup.SUMMARY.warnings)


def test_wheel_cache_staleness_warning(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    wheel_dir = setup.WHEEL_CACHE_ROOT
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = wheel_dir / "demo-0.1.0-py3-none-any.whl"
    wheel_path.write_bytes(b"wheel")
    stale_seconds = (setup.WHEEL_CACHE_STALE_AFTER_DAYS + 5) * 86_400
    stale_time = time.time() - stale_seconds
    os.utime(wheel_path, (stale_time, stale_time))
    setup.set_offline(True)
    setup.SUMMARY.warnings.clear()
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    setup.set_offline(False)
    assert any("Wheel cache freshness" in insight for insight in plan.insights)
    assert any("Wheel cache stale" in insight for insight in plan.insights)
    assert any("Wheel cache stale" in warning for warning in setup.SUMMARY.warnings)


def test_build_smart_plan_skips_when_stamp_matches(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    setup._write_req_stamp(req)
    monkeypatch.setattr(setup_stages, "_missing_requirements", lambda *a, **k: [])
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.should_install is False
    assert plan.steps == ()
    assert any("unchanged" in insight.lower() for insight in plan.insights)


def test_build_smart_plan_reports_missing(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("alpha==1.0\nbeta==2.0\n", encoding="utf-8")
    setup._write_req_stamp(req)
    site = (
        tmp_path
        / "venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    site.mkdir(parents=True, exist_ok=True)
    dist = site / "alpha-1.0.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "METADATA").write_text("Name: alpha\nVersion: 1.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.missing_requirements == ("beta==2.0",)
    assert any("missing" in reason for reason in plan.context.reasons)
    assert plan.context.partial_reinstall == ("beta==2.0",)
    assert plan.steps[0].title == "Bootstrap pip"
    targeted = [step for step in plan.steps if step.title.startswith("Install beta")]
    assert targeted, "Expected targeted install step for beta"
    assert targeted[0].pip_args == ("install", "beta==2.0")
    assert "not installed" in (targeted[0].reason or "")
    assert plan.steps[-1].title == "Validate environment"


def test_build_smart_plan_dev_fallback(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    setup._write_req_stamp(req)
    monkeypatch.setattr(setup_stages, "_missing_requirements", lambda *a, **k: [])
    plan = setup.build_smart_install_plan(req, dev=True, upgrade=False)
    fallback = [
        step
        for step in plan.steps
        if step.title.startswith("Install ")
        and step.title.split(" ", 1)[1] in setup.DEV_PACKAGES
    ]
    assert len(fallback) == len(setup.DEV_PACKAGES)
    assert all(step.optional for step in fallback)
    assert plan.steps[-1].title == "Validate environment"


def test_build_smart_plan_version_mismatch(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("alpha==2.0\n", encoding="utf-8")
    setup._write_req_stamp(req)
    site = (
        tmp_path
        / "venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    site.mkdir(parents=True, exist_ok=True)
    dist = site / "alpha-1.0.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "METADATA").write_text("Name: alpha\nVersion: 1.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.partial_reinstall == ("alpha==2.0",)
    mismatch = [issue for issue in plan.context.missing_details if issue.package == "alpha"]
    assert mismatch and mismatch[0].kind == "mismatch"
    reinstall = [step for step in plan.steps if step.title.startswith("Install alpha")]
    assert reinstall
    assert "does not satisfy" in (reinstall[0].reason or "")
    assert plan.steps[-1].title == "Validate environment"


def test_build_smart_plan_python_mismatch(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    monkeypatch.setattr(setup_stages, "_missing_requirements", lambda *a, **k: [])
    setup._write_req_stamp(req)
    stamp_path = setup._stamp_path()
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    payload["python"] = "0.0.0"
    stamp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.should_install is True
    assert any("python version changed" in reason for reason in plan.context.reasons)
    assert any(step.title == "Install requirements" for step in plan.steps)
    assert plan.steps[-1].title == "Validate environment"


def test_build_smart_plan_pip_reason(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(setup, "_current_pip_version", lambda: None)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.pip_version is None
    assert plan.context.pip_bootstrap_reason == "pip module unavailable"
    assert plan.steps[0].title == "Bootstrap pip"
    assert any("pip bootstrap reason" in insight for insight in plan.insights)
    assert plan.steps[-1].title == "Validate environment"


def test_smart_plan_reports_requirement_sources(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    editable_dir = tmp_path / "editable"
    editable_dir.mkdir(parents=True, exist_ok=True)
    local_wheel = tmp_path / "local.whl"
    local_wheel.write_bytes(b"wheel")
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "-r nested.txt",
                "git+https://example.com/pkg.git#egg=demo",
                "./local.whl",
                "../missing.whl",
                "-e ./editable",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    setup.set_offline(True)
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    setup.set_offline(False)
    sources = plan.context.requirement_sources
    assert sources.total == 4
    assert any("git+https://example.com" in entry for entry in sources.network)
    assert any(entry.endswith("local.whl") for entry in sources.local)
    assert any("missing.whl" in entry for entry in sources.missing_local)
    assert "nested.txt" in sources.nested
    assert "nested.txt" in sources.missing_nested
    assert any("Editable installs" in insight for insight in plan.insights)
    assert any("Requirement sources" in insight for insight in plan.insights)
    warnings = setup.SUMMARY.warnings
    assert any("network access" in warning for warning in warnings)
    assert any("Local requirement path missing" in warning for warning in warnings)
    assert any("Nested requirements missing" in warning for warning in warnings)


def test_smart_plan_reports_requirement_pinning(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "alpha==1.2.3",
                "beta>=2.0",
                "gamma",
                "delta==1.0.*",
                "epsilon==1.0; python_version < \"3.11\"",
                "zeta[extra]==2.0",
                "-c constraints.txt",
                "???",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    pinning = plan.context.requirement_pinning
    assert pinning.total == 6
    assert set(pinning.pinned) == {
        "alpha==1.2.3",
        "epsilon==1.0; python_version < \"3.11\"",
        "zeta[extra]==2.0",
    }
    assert pinning.unversioned == ("gamma",)
    assert pinning.ranged == ("beta>=2.0",)
    assert pinning.wildcard == ("delta==1.0.*",)
    assert pinning.constraints == ("constraints.txt",)
    assert pinning.invalid == ("???",)
    assert any("Requirement pinning" in insight for insight in plan.insights)
    assert any("Constraints referenced" in insight for insight in plan.insights)
    assert any("Unversioned requirements" in insight for insight in plan.insights)
    assert any("Version ranges" in insight for insight in plan.insights)
    assert any("Wildcard pins" in insight for insight in plan.insights)
    assert any("Requirements with markers" in insight for insight in plan.insights)
    assert any("Extras requested" in insight for insight in plan.insights)
    assert any("Invalid requirements skipped" in insight for insight in plan.insights)
    warnings = setup.SUMMARY.warnings
    assert any("Unversioned requirements" in warning for warning in warnings)
    assert any("Loose version ranges" in warning for warning in warnings)
    assert any("Wildcard pins" in warning for warning in warnings)
    assert any("Invalid requirement entries" in warning for warning in warnings)


def test_smart_plan_reports_requirement_duplicates(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "alpha==1.0.0",
                "alpha==2.0.0",
                "beta>=1.0",
                "beta>=2.0",
                "gamma; python_version < \"3.11\"",
                "gamma; python_version >= \"3.11\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    duplicates = plan.context.requirement_duplicates
    assert duplicates.total == 6
    assert "alpha (2 entries)" in duplicates.duplicates
    assert "beta (2 entries)" in duplicates.duplicates
    assert "gamma (2 entries)" in duplicates.marker_variants
    assert any("alpha" in entry for entry in duplicates.conflicting)
    assert any("Duplicate requirement entries" in warning for warning in setup.SUMMARY.warnings)
    assert any("Conflicting requirement pins" in warning for warning in setup.SUMMARY.warnings)
    assert any("Duplicate requirement entries" in insight for insight in plan.insights)
    assert any("Marker-specific requirement variants" in insight for insight in plan.insights)
    assert any("Conflicting requirement pins" in insight for insight in plan.insights)


def test_smart_plan_reports_requirement_markers(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "alpha==1.0; python_version < \"3.0\"",
                "beta==2.0; sys_platform == \"win32\"",
                "gamma==3.0; python_version >= \"3.11\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    markers = plan.context.requirement_markers
    assert markers.total == 3
    assert markers.with_markers == 3
    assert any("alpha" in entry for entry in markers.unsatisfied)
    assert any("beta" in entry for entry in markers.unsatisfied)
    assert any("gamma" in entry for entry in markers.satisfied)
    assert any("alpha" in entry for entry in markers.python_mismatch)
    assert any("beta" in entry for entry in markers.platform_mismatch)
    insights = plan.insights
    assert any("Requirement markers:" in insight for insight in insights)
    assert any("Markers not satisfied" in insight for insight in insights)
    assert any("Python marker mismatches" in insight for insight in insights)
    assert any("Platform marker mismatches" in insight for insight in insights)
    warnings = setup.SUMMARY.warnings
    assert any("Requirement markers unsatisfied" in warning for warning in warnings)
    assert any("Python version markers exclude current runtime" in warning for warning in warnings)
    assert any("Platform markers exclude current platform" in warning for warning in warnings)


def test_smart_plan_reports_requirement_indexes(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "--index-url http://insecure.example/simple",
                "--extra-index-url https://mirror.example/simple",
                "--extra-index-url http://extra.example/simple",
                "--find-links https://wheels.example/",
                "--find-links http://files.example/",
                "--trusted-host insecure.example",
                "alpha==1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    indexes = plan.context.requirement_indexes
    assert indexes.primary_index == "http://insecure.example/simple"
    assert indexes.extra_indexes == (
        "https://mirror.example/simple",
        "http://extra.example/simple",
    )
    assert indexes.find_links == (
        "https://wheels.example/",
        "http://files.example/",
    )
    assert indexes.trusted_hosts == ("insecure.example",)
    assert "http://insecure.example/simple" in indexes.insecure_indexes
    assert "http://files.example/" in indexes.insecure_links
    assert "http://insecure.example/simple" in indexes.network_indexes
    assert "http://files.example/" in indexes.network_find_links
    insights = plan.insights
    assert any("Requirement indexes" in insight for insight in insights)
    assert any("Find-links sources" in insight for insight in insights)
    assert any("Trusted hosts configured" in insight for insight in insights)
    warnings = setup.SUMMARY.warnings
    assert any("Insecure index URL" in warning for warning in warnings)
    assert any("Insecure find-links URL" in warning for warning in warnings)


def test_smart_plan_warns_offline_indexes(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "--index-url https://pypi.org/simple",
                "--find-links https://wheels.example/",
                "alpha==1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    setup.set_offline(True)
    try:
        plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    finally:
        setup.set_offline(False)
    warnings = setup.SUMMARY.warnings
    assert any("Offline mode but index URLs configured" in warning for warning in warnings)
    assert any(
        "Offline mode but find-links require network access" in warning
        for warning in warnings
    )
    insights = plan.insights
    assert any(
        "Analysis warning: Offline mode but index URLs configured" in insight
        for insight in insights
    )
    assert any(
        "Analysis warning: Offline mode but find-links require network access" in insight
        for insight in insights
    )


def test_smart_plan_reports_requirement_options(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "--require-hashes",
                "--prefer-binary",
                "--pre",
                "--no-build-isolation",
                "--no-deps",
                "--no-binary :all:",
                "--only-binary pandas,scipy",
                "--use-feature=in-tree-build,fast-deps",
                "--progress-bar off",
                "alpha==1.0 --hash=sha256:aaa",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    options = plan.context.requirement_options
    assert options.require_hashes is True
    assert options.prefer_binary is True
    assert options.pre is True
    assert options.no_build_isolation is True
    assert options.no_deps is True
    assert options.no_binary == (":all:",)
    assert options.only_binary == ("pandas", "scipy")
    assert options.use_features == ("in-tree-build", "fast-deps")
    assert "--progress-bar" in options.other_options
    insights = plan.insights
    assert any("Requirement options: " in insight for insight in insights)
    assert any("Binary wheels disabled for" in insight for insight in insights)
    assert any("Only binary wheels enforced" in insight for insight in insights)
    assert any("Experimental pip features" in insight for insight in insights)
    assert any("Additional pip options" in insight for insight in insights)
    warnings = setup.SUMMARY.warnings
    assert any("Binary wheels disabled via --no-binary" in warning for warning in warnings)
    assert any("Pre-release installs allowed" in warning for warning in warnings)
    assert any("Build isolation disabled" in warning for warning in warnings)
    assert any("Dependency resolution disabled" in warning for warning in warnings)
    assert any("Experimental pip features enabled" in warning for warning in warnings)
    assert any("Additional pip options encountered" in warning for warning in warnings)


def test_smart_plan_reports_requirement_hashing(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join(
            [
                "alpha==1.0 --hash=sha256:aaa",
                "beta==2.0 \\",
                "    --hash=sha256:bbb \\",
                "    --hash=sha256:ccc",
                "gamma>=1.0 --hash=sha256:ddd",
                "delta @ http://example.com/pkg.whl --hash=sha256:eee",
                "epsilon @ https://secure.example.com/pkg.whl",
                "zeta==3.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    setup.SUMMARY.warnings.clear()
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    hashing = plan.context.requirement_hashing
    assert hashing.total == 6
    assert hashing.hashed_total == 4
    assert hashing.unhashed_total == 2
    assert "alpha==1.0" in hashing.hashed
    assert "beta==2.0" in hashing.hashed
    assert "gamma>=1.0" in hashing.hashed
    assert "delta @ http://example.com/pkg.whl" in hashing.hashed
    assert "epsilon @ https://secure.example.com/pkg.whl" in hashing.unhashed
    assert "zeta==3.0" in hashing.unhashed
    assert "gamma>=1.0" in hashing.hashed_unpinned
    assert "delta @ http://example.com/pkg.whl" in hashing.hashed_unpinned
    assert "delta @ http://example.com/pkg.whl" in hashing.insecure_urls
    warnings = setup.SUMMARY.warnings
    assert any("Requirement hashes missing" in warning for warning in warnings)
    assert any("Hashed requirements lack strict pins" in warning for warning in warnings)
    assert any("Insecure requirement URLs" in warning for warning in warnings)
    assert any("Requirement hashes:" in insight for insight in plan.insights)
    assert any("Requirements without hashes" in insight for insight in plan.insights)
    assert any("Hashed requirements missing strict pins" in insight for insight in plan.insights)
    assert any("Insecure requirement URLs" in insight for insight in plan.insights)


def test_build_smart_plan_stamp_stale(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    setup._write_req_stamp(req)
    stamp_path = setup._stamp_path()
    payload = json.loads(stamp_path.read_text(encoding="utf-8"))
    payload["timestamp"] = time.time() - (60 * 60 * 24 * 45)
    stamp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.should_install is True
    assert any("stamp stale" in reason for reason in plan.context.reasons)
    assert any("stamp age" in insight.lower() for insight in plan.insights)
    assert plan.steps and plan.steps[-1].title == "Validate environment"


def test_build_smart_plan_reports_wheel_cache(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    cache_dir = setup._wheel_cache_dir()
    wheel = cache_dir / "demo-1.0-py3-none-any.whl"
    wheel.write_bytes(b"0" * 2048)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    assert plan.context.wheel_cache_files >= 1
    assert plan.context.wheel_cache_bytes >= 2048
    assert any("wheel cache" in insight.lower() for insight in plan.insights)


def test_build_smart_plan_offline_cache_warning(monkeypatch, tmp_path):
    _prepare_smart_setup(monkeypatch, tmp_path)
    req = tmp_path / "requirements.txt"
    req.write_text("rich==13.0.0\n", encoding="utf-8")
    setup.set_offline(True)
    plan = setup.build_smart_install_plan(req, dev=False, upgrade=False)
    setup.set_offline(False)
    assert plan.context.offline is True
    assert plan.context.wheel_cache_files == 0
    assert any("offline mode" in insight.lower() and "wheel cache" in insight.lower() for insight in plan.insights)
