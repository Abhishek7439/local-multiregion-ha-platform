#!/usr/bin/env python3
"""DR controller.

Watches Region A. After a short grace period it disables A on the gateway,
writes one object through the gateway, and records RTO. When A is back it
compares SHA-256 checksums and enables A only if every object matches.

RTO starts when Region A first fails the health check and ends when the
gateway write succeeds. The grace wait is included on purpose.
"""

import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from proof import compare_sites, haproxy_command

ROOT = Path(__file__).resolve().parent.parent
GRACE_SECONDS = 3
POLL_SECONDS = 1
A_HEALTH = "http://127.0.0.1:9100/minio/health/live"
B_HEALTH = "http://127.0.0.1:9200/minio/health/live"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_event(event):
    """Print one JSON object per line so the demo log is easy to read."""
    event["ts"] = utc_now()
    print(json.dumps(event), flush=True)


def is_live(url):
    """True only when the health URL returns HTTP 200 within 2 seconds."""
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def prove_write():
    """Put one small object through the gateway. Returns (ok, object_name, ms, error)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"rto-{stamp}.txt"
    started = time.monotonic()
    completed = subprocess.run(
        [str(ROOT / "scripts" / "mc.sh"), "pipe", f"gw/demo/{name}"],
        input=b"m2-rto-proof\n",
        cwd=ROOT,
        capture_output=True,
        timeout=40,
        check=False,
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    error = completed.stderr.decode(errors="replace")[-300:]
    return completed.returncode == 0, name, elapsed_ms, error


def main():
    state = "HEALTHY"
    down_at = None
    log_event({"event": "start", "state": state, "grace_seconds": GRACE_SECONDS})

    while True:
        a_up = is_live(A_HEALTH)
        b_up = is_live(B_HEALTH)
        now = time.monotonic()
        region_b = "UP" if b_up else "DOWN"

        if state == "HEALTHY" and not a_up:
            down_at = now
            state = "DEGRADED"
            log_event({
                "event": "transition",
                "from": "HEALTHY",
                "to": "DEGRADED",
                "region_a": "DOWN",
                "region_b": region_b,
                "reason": "region A health failed",
            })
        elif state == "DEGRADED" and a_up:
            down_at = None
            state = "HEALTHY"
            log_event({
                "event": "transition",
                "from": "DEGRADED",
                "to": "HEALTHY",
                "reason": "region A recovered inside the grace window",
            })
        elif state == "DEGRADED" and down_at is not None and (now - down_at) >= GRACE_SECONDS:
            state = "FAILOVER"
            log_event({
                "event": "transition",
                "from": "DEGRADED",
                "to": "FAILOVER",
                "reason": "region A still down after the grace window",
            })
            try:
                reply = haproxy_command("disable server minio_api/minio-a")
                log_event({"event": "fence", "server": "minio-a", "action": "disable", "reply": reply})
            except OSError as error:
                log_event({"event": "fence_failed", "action": "disable", "detail": str(error)})
            wrote = False
            for attempt in range(1, 6):
                ok, name, write_ms, error = prove_write()
                if ok:
                    rto_ms = int((time.monotonic() - down_at) * 1000)
                    log_event({
                        "event": "rto",
                        "milliseconds": rto_ms,
                        "write_attempt": attempt,
                        "write_ms": write_ms,
                        "object": f"gw/demo/{name}",
                        "region_b": region_b,
                    })
                    wrote = True
                    break
                log_event({"event": "write_failed", "attempt": attempt, "detail": error})
            if not wrote:
                log_event({"event": "rto_failed", "reason": "gateway write did not succeed"})
        elif state == "FAILOVER" and a_up:
            state = "RECOVERING"
            log_event({
                "event": "transition",
                "from": "FAILOVER",
                "to": "RECOVERING",
                "reason": "region A is live again; checksums must match before FAILBACK",
            })
        elif state == "RECOVERING" and a_up:
            try:
                report = compare_sites()
            except (RuntimeError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as error:
                log_event({"event": "checksum_error", "detail": str(error)[-300:]})
                report = None
            if report is not None:
                log_event({
                    "event": "checksum",
                    "match": report["match"],
                    "count_a": report["count_a"],
                    "count_b": report["count_b"],
                    "only_a": report["only_a"],
                    "only_b": report["only_b"],
                    "different": report["different"],
                })
                if report["match"]:
                    try:
                        reply = haproxy_command("enable server minio_api/minio-a")
                    except OSError as error:
                        log_event({"event": "fence_failed", "action": "enable", "detail": str(error)})
                    else:
                        state = "FAILBACK"
                        log_event({
                            "event": "transition",
                            "from": "RECOVERING",
                            "to": "FAILBACK",
                            "reason": "checksums match, so Region A may take traffic again",
                            "reply": reply,
                        })
                        state = "HEALTHY"
                        log_event({
                            "event": "transition",
                            "from": "FAILBACK",
                            "to": "HEALTHY",
                            "reason": "failback complete",
                        })
        elif state == "RECOVERING" and not a_up:
            down_at = now
            state = "DEGRADED"
            log_event({
                "event": "transition",
                "from": "RECOVERING",
                "to": "DEGRADED",
                "reason": "region A failed again during recovery",
            })

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_event({"event": "stop", "reason": "keyboard interrupt"})
