from types import SimpleNamespace

import pytest

from dashboard.hud import collectors


def test_collect_dashboard_procs_recognizes_repository_script_entrypoint(monkeypatch) -> None:
    """The VPS dashboard runs through ``.../hermes dashboard``, not -m hermes_cli.main."""
    process = SimpleNamespace(
        info={
            "pid": 4242,
            "name": "python",
            "cmdline": [
                "/home/hermes/.hermes/hermes-agent/venv/bin/python",
                "/home/hermes/.hermes/hermes-agent/hermes",
                "dashboard",
                "--host",
                "127.0.0.1",
                "--port",
                "9119",
            ],
            "create_time": 123.0,
            "memory_info": SimpleNamespace(rss=456),
        }
    )
    fake_psutil = SimpleNamespace(process_iter=lambda fields: [process])
    monkeypatch.setattr(collectors, "psutil", fake_psutil)

    result = collectors.collect_dashboard_procs()

    assert [item["pid"] for item in result["procs"]] == [4242]
    assert result["procs"][0]["rss"] == 456


def test_collect_dashboard_procs_finds_script_after_python_flags(monkeypatch) -> None:
    process = SimpleNamespace(
        info={
            "pid": 4343,
            "name": "python",
            "cmdline": [
                "/usr/bin/python3",
                "-u",
                "/home/hermes/.hermes/hermes-agent/hermes",
                "dashboard",
            ],
            "create_time": 124.0,
            "memory_info": SimpleNamespace(rss=457),
        }
    )
    monkeypatch.setattr(
        collectors,
        "psutil",
        SimpleNamespace(process_iter=lambda fields: [process]),
    )

    result = collectors.collect_dashboard_procs()

    assert [item["pid"] for item in result["procs"]] == [4343]


def test_collect_dashboard_procs_rejects_late_hermes_argument(monkeypatch) -> None:
    process = SimpleNamespace(
        info={
            "pid": 4444,
            "name": "python",
            "cmdline": [
                "/usr/bin/python3",
                "/tmp/worker.py",
                "/tmp/hermes",
                "dashboard",
            ],
            "create_time": 125.0,
            "memory_info": SimpleNamespace(rss=458),
        }
    )
    monkeypatch.setattr(
        collectors,
        "psutil",
        SimpleNamespace(process_iter=lambda fields: [process]),
    )

    result = collectors.collect_dashboard_procs()

    assert result["procs"] == []


@pytest.mark.parametrize("argv,expected", [
    (["hermes", "dashboard"], True),
    (["/venv/bin/hermes", "serve", "--port", "9119"], True),
    (["python3", "-m", "hermes_cli.main", "dashboard"], True),
    (["python3", "-mhermes_cli.main", "serve"], True),
    (["python3", "-um", "hermes_cli.main", "dashboard"], True),
    (["python3", "-Bumhermes_cli.main", "serve"], True),
    (["python3", "-uWignore", "-uXutf8", "-m", "hermes_cli.main", "dashboard"], True),
    (["python3", "-uW", "ignore", "-uX", "utf8", "/repo/hermes", "dashboard"], True),
    (["python3.11", "-u", "-W", "ignore", "-X", "utf8", "-m", "hermes_cli.main", "dashboard"], True),
    (["python3", "-Wignore", "-Xutf8", "-m", "hermes_cli.main", "dashboard"], True),
    (["python3", "-Bu", "--", "/repo/hermes", "dashboard"], True),
    (["Python", "/repo/hermes", "dashboard"], True),
    (["hermes", "--profile", "work", "dashboard"], True),
    (["hermes", "--profile=work", "serve"], True),
    (["hermes", "-p", "dashboard", "serve"], True),
    (["hermes", "--model", "test-model", "--safe-mode", "dashboard"], True),
    (["hermes", "--reasoning=high", "dashboard", "--host", "127.0.0.1"], True),
    (["python3", "worker.py", "hermes_cli.main", "dashboard"], False),
    (["python3", "-m", "worker", "hermes_cli.main", "dashboard"], False),
    (["python3", "-m", "not_hermes_cli.main", "dashboard"], False),
    (["python3", "-m", "hermes_cli.main_extra", "dashboard"], False),
    (["python3", "-c", "import hermes_cli.main", "dashboard"], False),
    (["python3", "-cimport hermes_cli.main", "serve"], False),
    (["python3", "-uc", "import hermes_cli.main", "dashboard"], False),
    (["python3", "-Bucimport hermes_cli.main", "serve"], False),
    (["python3", "-uWhermes_cli.main", "worker.py", "dashboard"], False),
    (["echo", "hermes_cli.main", "dashboard"], False),
    (["python3", "-W", "hermes_cli.main", "worker.py", "dashboard"], False),
    (["python3", "--", "-m", "hermes_cli.main", "dashboard"], False),
    (["hermes", "chat", "dashboard"], False),
    (["hermes", "--profile", "dashboard", "chat"], False),
    (["hermes", "--model", "dashboard", "chat"], False),
    (["hermes", "--continue", "dashboard"], False),
    (["hermes", "--oneshot", "dashboard"], False),
    (["hermes", "--profile=dashboard", "chat"], False),
    (["hermes", "--help", "dashboard"], False),
    (["hermes", "dashboard", "--help"], False),
    (["python3", "--version", "/repo/hermes", "dashboard"], False),
    (["python3", "-m"], False),
    (["python3", "-X"], False),
    (["hermes", "--unknown", "dashboard"], False),
    ([], False),
])
def test_dashboard_detection_uses_entrypoint_and_subcommand_boundaries(monkeypatch, argv, expected):
    """Only the program and its subcommand count, never text in another argv."""
    process = SimpleNamespace(info={
        "pid": 5252, "name": "python", "cmdline": argv,
        "create_time": 123.0, "memory_info": SimpleNamespace(rss=456),
    })
    monkeypatch.setattr(collectors, "psutil", SimpleNamespace(process_iter=lambda fields: [process]))
    result = collectors.collect_dashboard_procs()
    assert "error" not in result
    assert [row["pid"] for row in result["procs"]] == ([5252] if expected else [])


def test_unrelated_process_does_not_hide_stopped_dashboard_health(monkeypatch):
    from dashboard.hud import rules
    process = SimpleNamespace(info={
        "pid": 5353, "name": "python",
        "cmdline": ["python3", "worker.py", "hermes_cli.main", "dashboard"],
        "create_time": 123.0, "memory_info": SimpleNamespace(rss=456),
    })
    monkeypatch.setattr(collectors, "psutil", SimpleNamespace(process_iter=lambda fields: [process]))
    health = rules.evaluate_snapshot({"dashboard": collectors.collect_dashboard_procs()})
    assert any(i["fingerprint"] == "dashboard:not-running" for i in health["incidents"])
