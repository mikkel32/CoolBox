import platform
import shutil
from pathlib import Path
from types import SimpleNamespace
import hashlib
import datetime
import stat
import os
import pytest
import sys
import types

src = types.ModuleType("src")
utils = types.ModuleType("src.utils")
hash_utils = types.ModuleType("src.utils.hash_utils")
process_utils = types.ModuleType("src.utils.process_utils")
security = types.ModuleType("src.utils.security")
hash_utils.calc_hash = lambda p, algo="sha256": hashlib.sha256(
    Path(p).read_bytes()
).hexdigest()
process_utils.run_command = lambda *a, **kw: ("", None)
process_utils.run_command_ex = lambda *a, **kw: ("", 0)
security.ensure_admin = lambda *a, **kw: True
security.is_admin = lambda: True
security.list_open_ports = lambda: {}
utils.hash_utils = hash_utils
utils.process_utils = process_utils
utils.security = security
src.utils = utils
sys.modules.setdefault("src", src)
sys.modules.setdefault("src.utils", utils)
sys.modules.setdefault("src.utils.hash_utils", hash_utils)
sys.modules.setdefault("src.utils.process_utils", process_utils)
sys.modules.setdefault("src.utils.security", security)

import scripts.exe_inspector as inspector


def test_gather_info_windows(monkeypatch, tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_text("hello")
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    called = []

    def fake_ps(cmd):
        called.append(cmd)
        return "val"

    monkeypatch.setattr(inspector, "_powershell", fake_ps)
    monkeypatch.setattr(inspector, "calc_hash", lambda p, algo="sha256": "hash")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)

    info = inspector.gather_info(exe)
    assert info["SHA256"] == "hash"
    assert info["Version"] == "val"
    assert called


def test_processes_for(monkeypatch, tmp_path):
    exe = tmp_path / "a.exe"
    exe.write_text("x")

    proc = SimpleNamespace(info={"pid": 1, "name": "a", "exe": str(exe)})

    monkeypatch.setattr(
        inspector.psutil,
        "process_iter",
        lambda attrs=None: [proc],
    )

    procs = inspector._processes_for(exe)
    assert len(procs) == 1


def test_hash_fallback(monkeypatch, tmp_path):
    exe = tmp_path / "stub.exe"
    exe.write_text("x")

    def fail_hash(path, algo="sha256"):
        raise PermissionError("denied")

    monkeypatch.setattr(inspector, "calc_hash", fail_hash)
    monkeypatch.setattr(
        inspector,
        "run_command",
        lambda cmd, capture=False: "abcd1234 efgh" if capture else "",
    )
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)

    digest = inspector._calc_hash_smart(exe, "sha256")
    assert digest == "abcd1234"


def test_cpp_hash(tmp_path):
    exe = tmp_path / "bin"
    exe.write_bytes(b"data")
    if not inspector._compile_hash_calc():
        pytest.skip("compiler unavailable")
    inspector._load_hash_lib()
    digest = inspector._calc_hash_cpp(exe, "sha256")
    assert digest == hashlib.sha256(b"data").hexdigest()


def test_cpp_used(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    called = []
    monkeypatch.setattr(
        inspector, "_calc_hash_cpp", lambda p, a: called.append(a) or "ok"
    )
    digest = inspector._calc_hash_smart(exe, "sha256")
    assert digest == "ok"
    assert called == ["sha256"]


def test_compile_uses_pkgconfig(monkeypatch, tmp_path):
    src = tmp_path / "hash_calc.cpp"
    src.write_text("int x;")
    bin_path = tmp_path / "hash_calc"
    lib_path = tmp_path / "hash_calc.so"
    calls = []

    def fake_run(cmd, capture=False, check=True):
        calls.append(cmd)
        if cmd[0] == "pkg-config":
            return "-I/ssl/include" if "--cflags" in cmd else "-L/ssl/lib -lcrypto"
        if Path(cmd[0]).name == "g++":
            out = lib_path if "-shared" in cmd else bin_path
            out.touch()
            return ""
        return ""

    monkeypatch.setattr(inspector, "run_command", fake_run)
    monkeypatch.setattr(inspector, "HASHCALC_SRC", src)
    monkeypatch.setenv("EXE_HASH_BIN", str(bin_path))
    monkeypatch.setenv("EXE_HASH_LIB", str(lib_path))
    monkeypatch.setattr(
        inspector.shutil, "which", lambda x: "/usr/bin/g++" if x == "g++" else None
    )

    assert inspector._compile_hash_calc()
    assert any(cmd[0] == "pkg-config" for cmd in calls)
    assert any("-I/ssl/include" in cmd for cmd in calls if Path(cmd[0]).name == "g++")


def test_compile_respects_cxx_env(monkeypatch, tmp_path):
    src = tmp_path / "hash_calc.cpp"
    src.write_text("int x;")
    bin_path = tmp_path / "hash_calc"
    lib_path = tmp_path / "hash_calc.so"
    calls = []

    def fake_run(cmd, capture=False, check=True):
        calls.append(cmd)
        if cmd[0] == "pkg-config":
            return ""
        if cmd[0] == "mycxx":
            out = lib_path if "-shared" in cmd else bin_path
            out.touch()
            return ""
        return ""

    monkeypatch.setattr(inspector, "run_command", fake_run)
    monkeypatch.setattr(inspector, "HASHCALC_SRC", src)
    monkeypatch.setenv("EXE_HASH_BIN", str(bin_path))
    monkeypatch.setenv("EXE_HASH_LIB", str(lib_path))
    monkeypatch.setenv("CXX", "mycxx")
    monkeypatch.setattr(inspector.shutil, "which", lambda x: None)

    assert inspector._compile_hash_calc()
    assert any(cmd[0] == "mycxx" for cmd in calls)


def test_compile_extra_flags(monkeypatch, tmp_path):
    src = tmp_path / "hash_calc.cpp"
    src.write_text("int x;")
    bin_path = tmp_path / "hash_calc"
    lib_path = tmp_path / "hash_calc.so"
    calls = []

    def fake_run(cmd, capture=False, check=True):
        calls.append(cmd)
        if cmd[0] == "pkg-config":
            return ""
        if Path(cmd[0]).name == "g++":
            out = lib_path if "-shared" in cmd else bin_path
            out.touch()
            return ""
        return ""

    monkeypatch.setattr(inspector, "run_command", fake_run)
    monkeypatch.setattr(inspector, "HASHCALC_SRC", src)
    monkeypatch.setenv("EXE_HASH_BIN", str(bin_path))
    monkeypatch.setenv("EXE_HASH_LIB", str(lib_path))
    monkeypatch.setenv("EXE_HASH_CXXFLAGS", "-O3 -march=native")
    monkeypatch.setattr(
        inspector.shutil, "which", lambda x: "/usr/bin/g++" if x == "g++" else None
    )

    assert inspector._compile_hash_calc()
    gxx_calls = [c for c in calls if Path(c[0]).name == "g++"]
    assert any("-O3" in c for c in gxx_calls)
    assert any("-march=native" in c for c in gxx_calls)


def test_openssl_flags_fallback(monkeypatch):
    calls = []

    def fake_run(cmd, capture=True, check=False):
        calls.append(cmd)
        if cmd[0] == "pkg-config":
            return ""
        if cmd[0] == "openssl":
            return 'OPENSSLDIR: "/opt/ssl"'
        return ""

    monkeypatch.setattr(inspector, "run_command", fake_run)
    monkeypatch.setattr(
        inspector.ctypes.util, "find_library", lambda x: "/opt/ssl/lib/libcrypto.so"
    )

    flags = inspector._openssl_flags()
    assert "-I/opt/ssl/include" in flags
    assert "-L/opt/ssl/lib" in flags
    assert "-lcrypto" in flags


def test_load_hash_lib_env(monkeypatch, tmp_path):
    lib = tmp_path / "libhash.so"
    lib.touch()
    monkeypatch.setenv("EXE_HASH_LIB", str(lib))
    called = []

    class Dummy:
        def __init__(self):
            self.hash_file = lambda *a: 0

    def fake_cdll(path):
        called.append(path)
        return Dummy()

    monkeypatch.setattr(inspector.ctypes, "CDLL", fake_cdll)
    monkeypatch.setattr(inspector, "_HASH_LIB", None)
    monkeypatch.setattr(inspector, "_compile_hash_calc", lambda: False)

    lib_obj = inspector._load_hash_lib()
    assert isinstance(lib_obj, Dummy)
    assert called[0] == str(lib)


def test_load_hash_lib_find(monkeypatch, tmp_path):
    lib = tmp_path / "libhash_calc.so"
    lib.touch()
    called = []

    class Dummy:
        def __init__(self):
            self.hash_file = lambda *a: 0

    monkeypatch.setattr(inspector.ctypes.util, "find_library", lambda n: str(lib))

    def fake_cdll(path):
        called.append(path)
        return Dummy()

    monkeypatch.setattr(inspector.ctypes, "CDLL", fake_cdll)
    monkeypatch.setattr(inspector, "_HASH_LIB", None)
    monkeypatch.setattr(inspector, "_compile_hash_calc", lambda: False)
    monkeypatch.setattr(inspector, "HASHCALC_LIB_DEFAULT", tmp_path / "missing.so")

    lib_obj = inspector._load_hash_lib()
    assert isinstance(lib_obj, Dummy)
    assert called[0] == str(lib)


def test_gather_info_algos(monkeypatch, tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(inspector, "_powershell", lambda cmd: None)
    monkeypatch.setattr(inspector, "calc_hash", lambda p, algo="sha256": algo)
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe, algos=["md5", "sha1"])
    assert info["MD5"] == "md5"
    assert info["SHA1"] == "sha1"


def test_gather_info_permissions(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe)
    assert info["Permissions"].startswith("0o")


def test_gather_info_mode(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    exe.chmod(0o754)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe)
    assert info["Mode"] == stat.filemode(exe.stat().st_mode)
    assert info["Executable"] == "True"


def test_gather_info_accessed(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe)
    expected = datetime.datetime.fromtimestamp(exe.stat().st_atime).isoformat()
    assert info["Accessed"] == expected


def test_gather_info_symlink(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    link = tmp_path / "lnk"
    link.symlink_to(exe)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(link)
    assert info["IsSymlink"] == "True"
    assert info["Target"].endswith("bin")


def test_gather_info_interpreter(monkeypatch, tmp_path):
    script = tmp_path / "tool"
    script.write_text("#!/bin/bash\necho hi\n")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(script)
    assert info["Interpreter"] == "/bin/bash"


def test_gather_info_interpreter_env(monkeypatch, tmp_path):
    script = tmp_path / "tool_env"
    script.write_text("#!/usr/bin/env python\nprint('hi')\n")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(script)
    expected = shutil.which("python") or "python"
    assert info["Interpreter"] == expected


def _write_pe(path: Path, machine: int) -> None:
    data = bytearray(256)
    data[0:2] = b"MZ"
    data[0x3C:0x40] = (0x80).to_bytes(4, "little")
    data.extend(b"\x00" * (0x80 - len(data)))
    data[0x80:0x84] = b"PE\0\0"
    data[0x84:0x86] = machine.to_bytes(2, "little")
    path.write_bytes(data)


def test_detect_architecture_pe(tmp_path):
    exe = tmp_path / "app.exe"
    _write_pe(exe, 0x8664)
    assert inspector._detect_architecture(exe) == "64-bit"


def test_detect_architecture_elf(tmp_path):
    exe = tmp_path / "app"
    exe.write_bytes(b"\x7fELF\x02" + b"\x00" * 10)
    assert inspector._detect_architecture(exe) == "64-bit"


def test_gather_info_arch(monkeypatch, tmp_path):
    exe = tmp_path / "app"
    exe.write_bytes(b"\x7fELF\x02" + b"\x00" * 10)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe)
    assert info["Architecture"] == "64-bit"


def test_gather_info_denied(monkeypatch, tmp_path):
    exe = tmp_path / "bad.exe"
    exe.write_text("x")

    orig_stat = Path.stat
    orig_exists = Path.exists

    def fake_stat(self, *a, **kw):
        if self == exe:
            raise PermissionError()
        return orig_stat(self, *a, **kw)

    def fake_exists(self):
        if self == exe:
            return True
        return orig_exists(self)

    monkeypatch.setattr(Path, "stat", fake_stat)
    monkeypatch.setattr(Path, "exists", fake_exists)

    info = inspector.gather_info(exe)
    assert info.get("Access") == "Denied"


def test_extract_strings(tmp_path):
    exe = tmp_path / "bin"
    exe.write_bytes(b"\x00hello\x00world1234\x00")
    strings = inspector._extract_strings(exe, limit=5, min_len=4)
    assert "hello" in strings
    assert "world1234" in strings


def test_tui_app_init() -> None:
    info = {"Path": "x"}
    app = inspector.InspectorApp(info, [], {}, None)
    assert app.info == info


def test_tui_refresh(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "bin"
    exe.write_text("x")
    info = {"Path": str(exe)}
    app = inspector.InspectorApp(info, [], {}, None)
    dummy = SimpleNamespace(clear=lambda: None, add_row=lambda *a, **k: None)
    app.info_table = dummy
    app.procs_table = dummy
    app.port_table = dummy
    app.strings_table = dummy
    monkeypatch.setattr(
        inspector,
        "_processes_for",
        lambda path: [SimpleNamespace(pid=2, name=lambda: "proc")],
    )
    monkeypatch.setattr(inspector, "_ports_for", lambda pids: {1234: ["proc"]})
    app.action_refresh()
    assert app.ports == {1234: ["proc"]}
    assert app.procs[0].pid == 2


def test_tui_filter() -> None:
    app = inspector.InspectorApp({"Path": "x"}, [], {}, ["abc", "def", "ghi"])
    app.strings_filter = "d"
    assert app.filter_strings() == ["def"]


def test_tui_command(monkeypatch) -> None:
    called = []
    app = inspector.InspectorApp({"Path": "x"}, [], {}, None)
    app.cmd_table = SimpleNamespace(add_row=lambda text: called.append(text))
    app.cmd_input = SimpleNamespace(value="", display=False)
    dummy_event = SimpleNamespace(input=SimpleNamespace(id="cmd-input"), value="cmd")
    monkeypatch.setattr(
        inspector,
        "run_command_ex",
        lambda cmd, capture=False, check=False: ("out", 0),
    )
    app.on_input_submitted(dummy_event)
    assert called[0].endswith("$ cmd")
    assert called[1:] == ["out", "[exit 0]"]


def test_tui_command_no_output(monkeypatch) -> None:
    called = []
    app = inspector.InspectorApp({"Path": "x"}, [], {}, None)
    app.cmd_table = SimpleNamespace(add_row=lambda text: called.append(text))
    app.cmd_input = SimpleNamespace(value="", display=False)
    dummy_event = SimpleNamespace(input=SimpleNamespace(id="cmd-input"), value="cmd")
    monkeypatch.setattr(
        inspector,
        "run_command_ex",
        lambda cmd, capture=False, check=False: ("", 0),
    )
    app.on_input_submitted(dummy_event)
    assert called[0].endswith("$ cmd")
    assert called[1:] == ["<no output>", "[exit 0]"]


def test_tui_command_error(monkeypatch) -> None:
    called = []
    app = inspector.InspectorApp({"Path": "x"}, [], {}, None)
    app.cmd_table = SimpleNamespace(add_row=lambda text: called.append(text))
    app.cmd_input = SimpleNamespace(value="", display=False)
    dummy_event = SimpleNamespace(input=SimpleNamespace(id="cmd-input"), value="cmd")
    monkeypatch.setattr(
        inspector,
        "run_command_ex",
        lambda cmd, capture=False, check=False: (None, None),
    )
    app.on_input_submitted(dummy_event)
    assert called[0].endswith("$ cmd")
    assert called[1:] == ["<error>"]


def test_tui_command_clear(monkeypatch) -> None:
    events = []
    app = inspector.InspectorApp({"Path": "x"}, [], {}, None)
    app.cmd_table = SimpleNamespace(
        add_row=lambda text: events.append(text), clear=lambda: events.append("CLEAR")
    )
    app.cmd_input = SimpleNamespace(value="", display=False)
    dummy_event = SimpleNamespace(input=SimpleNamespace(id="cmd-input"), value="clear")

    def fail(*args, **kwargs):
        raise AssertionError("command should not run")

    monkeypatch.setattr(inspector, "run_command_ex", fail)
    app.on_input_submitted(dummy_event)
    assert events == ["CLEAR"]


def test_linked_libraries(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        inspector,
        "run_command",
        lambda cmd, capture=False, check=True: "libc.so => /lib/libc.so\n" if capture else "",
    )
    libs = inspector._linked_libraries(exe)
    assert libs == ["libc.so"]


def test_gather_info_libraries(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "run_command", lambda *a, **k: "libc.so => /lib/libc.so\n")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe)
    assert "libc.so" in info.get("Libraries", "")


def test_rpath_entries(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def fake_run(cmd, capture=False, check=True):
        if cmd[0] == "readelf":
            return "0x000000000000001d (RUNPATH)            Library runpath: [/opt/lib]"
        return ""

    monkeypatch.setattr(inspector, "run_command", fake_run)
    rpaths = inspector._rpath_entries(exe)
    assert rpaths == ["/opt/lib"]


def test_gather_info_rpath(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    def fake_run(cmd, capture=False, check=True):
        if cmd[0] == "readelf":
            return "0x000000000000001d (RPATH)            Library rpath: [/opt/lib]"
        if cmd[0] == "ldd":
            return ""
        if cmd[0] == "file":
            return ""
        return ""

    monkeypatch.setattr(inspector, "run_command", fake_run)
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)
    info = inspector.gather_info(exe)
    assert info.get("RPATH") == "/opt/lib"


def test_gather_info_extra(monkeypatch, tmp_path):
    exe = tmp_path / "note.txt"
    exe.write_text("hello world")
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)

    class DummyProc:
        pid = 1
    monkeypatch.setattr(inspector, "_processes_for", lambda p: [DummyProc()])

    info = inspector.gather_info(exe)
    assert info["MIME"] == "text/plain"
    assert float(info["Entropy"]) > 0
    assert info["EntropyRating"] == "low"
    assert info["ProcessCount"] == "1"


def test_entropy_empty(tmp_path):
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert inspector._file_entropy(f) == 0.0


def test_format_bytes() -> None:
    assert inspector._format_bytes(500) == "500 bytes"
    assert inspector._format_bytes(2048) == "2.0 KB"


def test_entropy_rating() -> None:
    assert inspector._entropy_rating(8.0) == "high"
    assert inspector._entropy_rating(6.0) == "medium"
    assert inspector._entropy_rating(3.0) == "low"


def test_format_duration() -> None:
    assert inspector._format_duration(45) == "45 seconds"
    assert inspector._format_duration(3661) == "1 hour, 1 minute"


def test_age_rating() -> None:
    assert inspector._age_rating(60) == "new"
    assert inspector._age_rating(86400 * 5) == "recent"
    assert inspector._age_rating(86400 * 60) == "old"


def test_gather_info_age(monkeypatch, tmp_path):
    exe = tmp_path / "bin"
    exe.write_text("x")
    fixed_now = datetime.datetime(2024, 1, 10, 12, 0, 0)
    mtime = (fixed_now - datetime.timedelta(days=3)).timestamp()
    os.utime(exe, (mtime, mtime))

    class DummyDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed_now

    dummy_module = types.SimpleNamespace(datetime=DummyDT)
    monkeypatch.setattr(inspector, "datetime", dummy_module)
    monkeypatch.setattr(inspector, "_calc_hash_cpp", lambda p, a: None)

    info = inspector.gather_info(exe)
    assert info["AgeRating"] == "recent"
    assert info["Age"].startswith("3 day")
