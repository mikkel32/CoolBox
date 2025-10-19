import coolbox.utils.vm as vm
from coolbox.cli.commands import preview_plugin as previewcli
from coolbox.cli.commands import run_vm_debug as vmcli


def test_launch_vm_debug_wrapper(monkeypatch):
    calls: list[str] = []

    def wrapper(port, open_code=False, env=None):
        calls.append("wrapper")
        return True

    def docker(port, env=None):
        calls.append("docker")
        return False

    def vagrant(port, env=None):
        calls.append("vagrant")
        return False

    def local(port, env=None):
        calls.append("local")

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", wrapper)
    monkeypatch.setattr(vm, "_launch_docker", docker)
    monkeypatch.setattr(vm, "_launch_vagrant", vagrant)
    monkeypatch.setattr(vm, "_launch_local_debug", local)

    vm.launch_vm_debug()
    assert calls == ["wrapper"]


def test_launch_vm_debug_docker_windows(monkeypatch):
    cmds: list[list[str]] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False, env=None: False)
    monkeypatch.setattr(vm, "_is_windows", lambda: True)
    monkeypatch.setattr(vm, "_wsl_available", lambda: True)
    monkeypatch.setattr(vm, "_exists", lambda p: True)
    monkeypatch.setattr(vm, "_which", lambda name: "docker" if name == "docker" else None)

    def fake_spawn(cmd, **kwargs):
        cmds.append(list(cmd))

    monkeypatch.setattr(vm, "_spawn", fake_spawn)

    vm.launch_vm_debug(prefer="docker")
    assert cmds and cmds[0][0] == "wsl.exe"


def test_launch_vm_debug_vagrant(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False, env=None: False)
    monkeypatch.setattr(vm, "_launch_docker", lambda p, env=None: calls.append("docker") or False)
    monkeypatch.setattr(vm, "_launch_vagrant", lambda p, env=None: calls.append("vagrant") or True)

    vm.launch_vm_debug()
    assert calls == ["docker", "vagrant"]


def test_launch_vm_debug_local_fallback(monkeypatch):
    cmds: list[list[str]] = []
    envs: list[dict[str, str]] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False, env=None: False)
    monkeypatch.setattr(vm, "_launch_docker", lambda p, env=None: False)
    monkeypatch.setattr(vm, "_launch_vagrant", lambda p, env=None: False)

    def fake_spawn(cmd, *, env=None, cwd=None):
        cmds.append(list(cmd))
        envs.append(dict(env or {}))

    monkeypatch.setattr(vm, "_spawn", fake_spawn)

    vm.launch_vm_debug(port=9999)
    assert any("debugpy" in part for part in cmds[0])
    assert envs[0]["DEBUG_PORT"] == "9999"


def test_launch_vm_debug_preview_env(monkeypatch):
    captured_env: list[dict[str, str]] = []

    monkeypatch.setattr(vm, "_launch_vm_debug_wrapper", lambda p, open_code=False, env=None: False)
    monkeypatch.setattr(vm, "_launch_docker", lambda p, env=None: False)
    monkeypatch.setattr(vm, "_launch_vagrant", lambda p, env=None: False)

    def fake_spawn(cmd, *, env=None, cwd=None):
        captured_env.append(dict(env or {}))

    monkeypatch.setattr(vm, "_spawn", fake_spawn)

    vm.launch_vm_debug(preview_plugin="sample", preview_manifest="manifest.yaml", preview_profile="dev")
    assert captured_env
    env = captured_env[0]
    assert env["COOLBOX_PLUGIN_PREVIEW"] == "sample"
    assert env["COOLBOX_PLUGIN_PREVIEW_MANIFEST"] == "manifest.yaml"
    assert env["COOLBOX_PLUGIN_PREVIEW_PROFILE"] == "dev"


def test_vm_cli_parse_defaults():
    args = vmcli.parse_args([])
    assert args.prefer == "auto"
    assert args.code is False
    assert args.port == 5678
    assert args.list is False
    assert args.preview_plugin is None
    assert args.preview_manifest is None
    assert args.preview_profile is None


def test_vm_cli_main_launch(monkeypatch):
    calls = []

    def fake_launch(
        prefer=None,
        open_code=False,
        port=5678,
        skip_deps=False,
        preview_plugin=None,
        preview_manifest=None,
        preview_profile=None,
    ):
        calls.append((prefer, open_code, port, skip_deps, preview_plugin, preview_manifest, preview_profile))

    monkeypatch.setattr(vmcli, "_load_launch", lambda: fake_launch)
    vmcli.main(
        [
            "--prefer",
            "docker",
            "--code",
            "--port",
            "1234",
            "--preview-plugin",
            "sample",
            "--preview-manifest",
            "manifest.yaml",
            "--preview-profile",
            "dev",
        ]
    )
    assert calls == [("docker", True, 1234, False, "sample", "manifest.yaml", "dev")]


def test_vm_cli_main_list(monkeypatch, capsys):
    monkeypatch.setattr(vmcli, "available_backends", lambda: ["docker"])
    vmcli.main(["--list"])
    out = capsys.readouterr().out
    assert "docker" in out


def test_preview_plugin_cli(monkeypatch):
    calls = []

    def fake_launch(
        *,
        prefer=None,
        open_code=False,
        port=5678,
        skip_deps=False,
        preview_plugin=None,
        preview_manifest=None,
        preview_profile=None,
    ):
        calls.append(
            (
                prefer,
                open_code,
                port,
                skip_deps,
                preview_plugin,
                preview_manifest,
                preview_profile,
            )
        )

    monkeypatch.setattr(previewcli, "launch_vm_debug", fake_launch)
    previewcli.main(
        [
            "sample",
            "--manifest",
            "preview.yaml",
            "--profile",
            "test",
            "--prefer",
            "docker",
            "--port",
            "7777",
            "--open-code",
        ]
    )
    assert calls == [("docker", True, 7777, False, "sample", "preview.yaml", "test")]

