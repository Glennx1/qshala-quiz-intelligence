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
    configured_limit = float(os.getenv("SERVER_MEMORY_LIMIT_MB", "2048"))
    effective_limit = round(limit) if limit else configured_limit
    return {"memory_mb": r(cur), "peak_memory_mb": r(peak), "memory_limit_mb": effective_limit}


# A safety margin for the activity log, not a hard limit: Cloud Run gives this worker 2048 MB,
# and crossing this threshold logs one warning so a deck getting close to that real ceiling is
# visible before it ever gets there. Deliberately NOT used to throttle or abort ingestion --
# only to warn. 1792 MB = 1.75 GB, leaving ~256 MB of headroom below the container's actual limit.
MEMORY_WARN_THRESHOLD_MB = float(os.getenv("MEMORY_WARN_THRESHOLD_MB", "1792"))


def maybe_warn_memory(reg: Optional[Dict[str, Any]], mem: Optional[Dict[str, Optional[float]]] = None) -> None:
    """Logs one activity-log warning the first time this document's memory usage crosses
    MEMORY_WARN_THRESHOLD_MB. Never aborts, cancels, or throttles ingestion -- it only makes a
    deck that's getting close to the container's real memory ceiling visible in the UI's
    activity log before it actually gets there, instead of the first sign of trouble being an
    OOM kill with no warning at all.
    """
    if reg is None or reg.get("_memory_warned"):
        return
    mem = mem or memory_mb()
    cur = mem.get("memory_mb")
    limit = mem.get("memory_limit_mb")
    if cur is None or cur < MEMORY_WARN_THRESHOLD_MB:
        return
    reg["_memory_warned"] = True
    limit_desc = f"{limit:.0f}" if limit is not None else "?"
    event(reg, f"Memory usage is high ({cur:.0f} of {limit_desc} MB) -- still processing, but an "
               f"even larger or more image-heavy deck could approach the container's limit.")


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
