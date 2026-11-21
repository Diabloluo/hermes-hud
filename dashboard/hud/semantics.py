"""Pure classification of snapshot metadata, not service or scheduler control."""
import math


def cron_is_inactive(job: dict) -> bool:
    """Only explicit inactivity excludes a failure; missing metadata stays visible.

    Host cron/jobs.py gates pause markers separately from enabled. Completed
    jobs are terminal. Error states are deliberately NOT suppressed.
    """
    return (job.get("enabled") is False
            or job.get("state") in ("paused", "completed", "disabled")
            or bool(job.get("paused_at")))


def _identity_number(value) -> bool:
    return (type(value) in (int, float) and math.isfinite(value) and value > 0)


def platform_activity(platform: dict, gateway: dict) -> str:
    """Writer identity is provenance, not proof of operator configuration.

    A different complete writer identifies historical state, NOT a disabled
    platform or a healthy current connection. Missing identity is unknown.
    Do not parse config/credentials or infer disabled from needs_attention.
    """
    pid, start = gateway.get("pid"), gateway.get("start_time")
    writer, writer_start = platform.get("writer_pid"), platform.get("writer_start_time")
    if not all(_identity_number(x) for x in (pid, start, writer, writer_start)):
        return "unknown"
    if type(pid) is not int or type(writer) is not int:
        return "unknown"
    if (pid, start) != (writer, writer_start):
        return "historical"
    if platform.get("enabled") is False or platform.get("state") == "disabled":
        return "inactive"
    return "current"
