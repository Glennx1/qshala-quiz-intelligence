"""Live progress details for an upload: what is happening now, a short activity log, and server memory.

The upload page polls the status endpoint and shows these, so a slow or stuck job can be understood
without opening the server logs.
"""
import os
import time
from typing import Any, Dict, Optional

MAX_EVENTS = 60


def _read_kb(path: str, key: str) -> Optional[float]:
    try:
        with open(path) as f:
            for line in f:
                if line.startswith(key):
                    return float(line.split()[1])
    except Exception:
        pass
    return None


def memory_mb() -> Dict[str, Optional[float]]:
    """Current and peak memory of this server process, and the container limit when it is known."""
    cur = _read_kb("/proc/self/status", "VmRSS:")
    peak = _read_kb("/proc/self/status", "VmHWM:")
    limit = None
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = open(p).read().strip()
            if raw.isdigit() and int(raw) < 1 << 50:
                limit = int(raw) / 1048576.0
                break
        except Exception:
            continue
    r = lambda v: round(v / 1024.0, 0) if v is not None else None
    return {"memory_mb": r(cur), "peak_memory_mb": r(peak), "memory_limit_mb": round(limit) if limit else None}


def update(reg: Dict[str, Any], detail: Optional[str] = None, pct: Optional[float] = None,
           step: Optional[str] = None) -> None:
    if detail is not None:
        reg["detail"] = detail
    if pct is not None:
        reg["progress_percentage"] = max(int(reg.get("progress_percentage", 0)), int(pct))
    if step is not None:
        reg["current_step"] = step
    reg.update(memory_mb())


def event(reg: Dict[str, Any], msg: str, detail: Optional[str] = None) -> None:
    events = reg.setdefault("events", [])
    events.append({"ts": time.time(), "msg": msg})
    if len(events) > MAX_EVENTS:
        del events[: len(events) - MAX_EVENTS]
    update(reg, detail=detail if detail is not None else msg)
