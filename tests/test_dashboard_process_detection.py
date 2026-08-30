from types import SimpleNamespace

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
