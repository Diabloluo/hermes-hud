"""Accept only the observed Hermes managed-relaunch program, never arbitrary -c."""
from types import SimpleNamespace

import pytest

from dashboard.hud import collectors


def bootstrap(args=None, root="/example/hermes-agent"):
    argv = [root + "/hermes_cli/main.py", *(args if args is not None else ["dashboard", "--port", "9119"])]
    return (f"import sys, runpy; sys.path.insert(0, {root!r}); sys.argv = {argv!r}; "
            "sys._hermes_relaunched = True; "
            "runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)")


BASE = bootstrap()
CASES = [
    ("managed-dashboard", ["python3", "-I", "-c", BASE], True),
    ("managed-serve", ["python3.14", "-u", "-I", "-c", bootstrap(["serve"])], True),
    ("attached-code", ["python3", "-Ic" + BASE], True),
    ("clustered-options", ["python3", "-Iuc", BASE], True),
    ("warning-option", ["python3", "-I", "-Wignore", "-c", BASE], True),
    ("global-profile", ["python3", "-I", "-c", bootstrap(["--profile", "work", "dashboard"])], True),
    ("spaced-root", ["python3", "-I", "-c", bootstrap(root="/example/Hermes Work")], True),
    ("unicode-root", ["python3", "-I", "-c", bootstrap(root="/example/项目")], True),
    ("same-ast-newlines", ["python3", "-I", "-c", BASE.replace("; ", "\n")], True),
    ("same-ast-comment", ["python3", "-I", "-c", BASE + "\n# launch comment"], True),
    ("no-isolation", ["python3", "-c", BASE], False),
    ("isolation-is-option-value", ["python3", "-W", "-I", "-c", BASE], False),
    ("trailing-argv", ["python3", "-I", "-c", BASE, "dashboard"], False),
    ("ordinary-inline", ["python3", "-I", "-c", "import hermes_cli.main; print('dashboard')"], False),
    ("payload-is-data", ["python3", "worker.py", "-I", "-c", BASE], False),
    ("other-module", ["python3", "-I", "-c", BASE.replace("'hermes_cli.main'", "'other.main'")], False),
    ("marker-false", ["python3", "-I", "-c", BASE.replace("_hermes_relaunched = True", "_hermes_relaunched = False")], False),
    ("marker-missing", ["python3", "-I", "-c", BASE.replace("sys._hermes_relaunched = True; ", "")], False),
    ("extra-prefix", ["python3", "-I", "-c", "print('not the launcher'); " + BASE], False),
    ("extra-suffix", ["python3", "-I", "-c", BASE + "; print('not the launcher')"], False),
    ("extra-import", ["python3", "-I", "-c", BASE.replace("import sys, runpy", "import sys, runpy, os")], False),
    ("aliased-import", ["python3", "-I", "-c", BASE.replace("import sys, runpy", "import sys, runpy as other")], False),
    ("alter-sys-false", ["python3", "-I", "-c", BASE.replace("alter_sys=True", "alter_sys=False")], False),
    ("different-run-name", ["python3", "-I", "-c", BASE.replace("run_name='__main__'", "run_name='worker'")], False),
    ("extra-run-keyword", ["python3", "-I", "-c", BASE.replace("alter_sys=True)", "alter_sys=True, init_globals={})")], False),
    ("different-insert-index", ["python3", "-I", "-c", BASE.replace("insert(0,", "insert(1,")], False),
    ("relative-root", ["python3", "-I", "-c", bootstrap(root="relative/hermes-agent")], False),
    ("traversal-root", ["python3", "-I", "-c", bootstrap(root="/example/../hermes-agent")], False),
    ("wrong-argv-entry", ["python3", "-I", "-c", BASE.replace("/example/hermes-agent/hermes_cli/main.py", "/other/worker.py")], False),
    ("dynamic-root", ["python3", "-I", "-c", BASE.replace("insert(0, '/example/hermes-agent')", "insert(0, str('/example/hermes-agent'))")], False),
    ("dynamic-argv", ["python3", "-I", "-c", BASE.replace("sys.argv = [", "sys.argv = list([").replace("]; sys._", "]); sys._")], False),
    ("non-string-argv", ["python3", "-I", "-c", BASE.replace("'--port'", "123")], False),
    ("chat-not-dashboard", ["python3", "-I", "-c", bootstrap(["chat", "dashboard"])], False),
    ("profile-value-only", ["python3", "-I", "-c", bootstrap(["--profile", "dashboard", "chat"])], False),
    ("help-not-server", ["python3", "-I", "-c", bootstrap(["dashboard", "--help"])], False),
    ("exec-wrapper", ["python3", "-I", "-c", "exec(" + repr(BASE) + ")"], False),
    ("syntax-error", ["python3", "-I", "-c", BASE + " ("], False),
    ("oversized-source", ["python3", "-I", "-c", BASE + "\n#" + "x" * 16384], False),
    ("missing-code", ["python3", "-I", "-c"], False),
    ("run-path-not-observed", ["python3", "-I", "-c", BASE[:BASE.index("runpy.run_module")] + "runpy.run_path('/example/hermes', run_name='__main__')"], False),
]


@pytest.mark.parametrize("name,argv,expected", CASES, ids=[row[0] for row in CASES])
def test_managed_relaunch_has_strict_structure(monkeypatch, name, argv, expected):
    process = SimpleNamespace(info={
        "pid": 7474, "name": "python3.14", "cmdline": argv,
        "create_time": 1.0, "memory_info": None,
    })
    monkeypatch.setattr(collectors, "psutil", SimpleNamespace(process_iter=lambda fields: [process]))
    result = collectors.collect_dashboard_procs()
    assert "error" not in result
    assert [p["pid"] for p in result["procs"]] == ([7474] if expected else [])
