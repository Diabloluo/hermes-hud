"""Gate-less audit adapter definition, NOT a launcher or native authorization."""
import os
from pathlib import Path
import sys
from boundary_policy import BoundaryRefused


class OpenAuditAdapter:
    def __init__(self, policy, frames):
        self.policy, self.frames = policy, frames

    def __call__(self, event, args):
        if event != 'open':
            return  # Not a standalone sandbox: original network/SQL/exec guards required.
        if not (type(args) is tuple and len(args) == 3):
            self.policy.check(None, None, None, None,
                              {'frames': [], 'unknown_frames': 0, 'truncated': True}, None)
        requested, mode, flags = args
        if type(requested) is int and requested >= 0:
            return  # Inherited fd restriction is unchanged; this does not prove fd containment.
        frame = sys._getframe(1)
        caller = self.frames.collect(frame)
        immediate = self.frames.immediate(frame)
        try:
            if type(requested) not in (str, bytes):
                raise BoundaryRefused('file_boundary')
            raw = os.fsdecode(requested)
            canonical = str(Path(raw).resolve())
        except Exception:
            raw, canonical = None, None
        finally:
            del frame
        self.policy.check(raw, canonical, mode, flags, caller, immediate)


def checkpoint_before_success(adapter):
    """Future observer/parent must invoke this before readiness and every PASS seal."""
    adapter.policy.ensure_clean()
    return adapter.policy.state()

