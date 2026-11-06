"""Checksums, RPO, and the HAProxy admin commands.

The controller imports this file. No third-party packages.

ETag trust assumption (documented in D7):
In S3/MinIO, single-part uploads produce a plain hex MD5 with no suffix.
The "-N" suffix indicates a multipart upload where N is the number of parts.
Because `mc pipe` streams without knowing total length upfront, it uploads
via the S3 multipart API, producing an ETag ending in "-1".

Matching size and ETag is strong evidence of identical content, not proof.
Different part sizes (or single-part vs multipart) can produce different
ETags for identical bytes; `compare_sites()` handles this by falling back
to SHA-256 to confirm whether content matches.

Crucially, the fast path does NOT detect silent corruption (bit rot) of
stored data if metadata on disk is unchanged. Full periodic integrity audits
must use `make audit` (`compare_sites --deep`), which hashes every object.
"""

import hashlib
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MC = ROOT / "scripts" / "mc.sh"
HAPROXY_ADMIN = ("127.0.0.1", 9999)
A_HEALTH = "http://127.0.0.1:9100/minio/health/live"


def run_mc(args, data=None, timeout=60):
    """Run the existing MinIO client. data is the object body for `mc pipe`."""
    return subprocess.run(
        [str(MC), *args],
        input=data,
        cwd=ROOT,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def haproxy_command(command):
    """Send one admin command. Returns the text HAProxy sends back."""
    with socket.create_connection(HAPROXY_ADMIN, timeout=3) as sock:
        sock.sendall((command.strip() + "\n").encode())
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            chunks.append(piece)
    return b"".join(chunks).decode(errors="replace").strip()


def list_objects(alias):
    """Every file name under an mc alias. Folder rows are skipped."""
    completed = run_mc(["ls", "--recursive", "--json", alias])
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode(errors="replace")[-400:])
    names = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") == "file" and item.get("key"):
            names.append(item["key"])
    return names


def list_objects_meta(alias):
    """Return {key: (size, etag)} for every file under an mc alias.

    Uses a single `mc ls --recursive --json` call -- one Docker container
    invocation regardless of object count.
    """
    completed = run_mc(["ls", "--recursive", "--json", alias])
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode(errors="replace")[-400:])
    meta = {}
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("type") == "file" and item.get("key"):
            meta[item["key"]] = (item.get("size", -1), item.get("etag", ""))
    return meta


def sha256_of(alias, key):
    """SHA-256 of one object. None if the read fails."""
    completed = run_mc(["cat", f"{alias}/{key}"])
    if completed.returncode != 0:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def compare_sites(deep=False):
    """Compare every object on site-a with the same key on site-b.

    Fast path (default, deep=False):
      1. List both sites with `mc ls --recursive --json` (2 containers).
      2. Compare key sets. Keys only on one side -> mismatch.
      3. For shared keys: if size and ETag match -> identical, skip SHA-256.
      4. If size or ETag differ -> fall back to SHA-256 on both sides.
         If SHA-256 matches, treat as match (ETag difference was cosmetic).
         If SHA-256 differs, record in `different`.

    Deep path (deep=True):
      SHA-256 every object on both sides regardless of ETag. Slower but
      guarantees byte-level verification to catch silent storage corruption.

    Fail safe: any mismatch (only_a, only_b, different) -> match=False,
    which blocks failback in the controller.
    """
    meta_a = list_objects_meta("site-a")
    meta_b = list_objects_meta("site-b")

    keys_a = set(meta_a)
    keys_b = set(meta_b)
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    shared = sorted(keys_a & keys_b)

    different = []
    sha256_checked = 0

    if deep:
        # Full SHA-256 on every shared key
        for key in shared:
            ha = sha256_of("site-a", key)
            hb = sha256_of("site-b", key)
            sha256_checked += 1
            if ha != hb:
                different.append(key)
    else:
        # Fast path: only SHA-256 on metadata mismatches
        for key in shared:
            size_a, etag_a = meta_a[key]
            size_b, etag_b = meta_b[key]
            if size_a == size_b and etag_a == etag_b:
                continue  # identical by metadata
            # Metadata mismatch -> verify with SHA-256
            ha = sha256_of("site-a", key)
            hb = sha256_of("site-b", key)
            sha256_checked += 1
            if ha != hb:
                different.append(key)

    return {
        "match": not only_a and not only_b and not different,
        "count_a": len(meta_a),
        "count_b": len(meta_b),
        "only_a": only_a,
        "only_b": only_b,
        "different": different,
        "sha256_checked": sha256_checked,
        "mode": "deep" if deep else "fast",
    }


def docker_bin():
    """Prefer the Linux docker client. A Windows docker.exe on PATH cannot see this engine."""
    linux_docker = Path("/usr/bin/docker")
    if linux_docker.exists():
        return str(linux_docker)
    return "docker"


def wait_for_a(timeout=30):
    """Wait until minio-a health check returns HTTP 200."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            req = urllib.request.Request(A_HEALTH, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(1)
    return False


def measure_rpo(stop_after=12, max_writes=30, kill=False, tag=None):
    """Write numbered objects to Region A and stop/kill A in the middle.

    RPO is how many of those acknowledged objects are missing on Region B.
    Writes that happen after A is dead do not count: they are not acknowledged.
    """
    if tag is None:
        tag = f"{'kill' if kill else 'stop'}-{int(time.time())}"
    acked = []
    stopped = False
    stop_ms = None
    started = time.monotonic()
    bucket = f"site-a/rpo-{tag}"
    created = run_mc(["mb", "--ignore-existing", bucket])
    if created.returncode != 0:
        raise RuntimeError(created.stderr.decode(errors="replace")[-400:])
    action = ["kill", "minio-a"] if kill else ["stop", "minio-a"]
    for number in range(1, max_writes + 1):
        key = f"rpo-{tag}/{number:05d}.txt"
        body = f"{number:05d}\n".encode()
        completed = run_mc(["pipe", f"site-a/{key}"], data=body)
        if completed.returncode != 0:
            break
        acked.append((key, body))
        if len(acked) >= stop_after and not stopped:
            subprocess.run(
                [docker_bin(), "compose", *action],
                cwd=ROOT,
                check=False,
            )
            stopped = True
            stop_ms = int((time.monotonic() - started) * 1000)
    # Give copies that were already queued a moment to land on B.
    time.sleep(2)
    missing = []
    for key, body in acked:
        completed = run_mc(["cat", f"site-b/{key}"])
        if completed.returncode != 0 or completed.stdout != body:
            missing.append(key)
    return {
        "mode": "kill" if kill else "graceful_stop",
        "tag": tag,
        "acked": len(acked),
        "missing": missing,
        "rpo_objects": len(missing),
        "stopped_region_a": stopped,
        "stop_ms": stop_ms,
    }


if __name__ == "__main__":
    if "compare" in sys.argv or "--compare" in sys.argv:
        deep = "--deep" in sys.argv
        res = compare_sites(deep=deep)
        print(json.dumps(res, indent=2))
    else:
        results = {}
        run_all = len(sys.argv) == 1 or "--both" in sys.argv
        run_kill = "--kill" in sys.argv or run_all
        run_graceful = "--graceful" in sys.argv or run_all

        try:
            if run_graceful:
                res_graceful = measure_rpo(kill=False)
                results["graceful_stop"] = res_graceful
                subprocess.run([docker_bin(), "compose", "start", "minio-a"], cwd=ROOT, check=False)
                wait_for_a()

            if run_kill:
                res_kill = measure_rpo(kill=True)
                results["kill"] = res_kill
        finally:
            subprocess.run([docker_bin(), "compose", "start", "minio-a"], cwd=ROOT, check=False)
            wait_for_a()

        print(json.dumps(results if len(results) > 1 else list(results.values())[0], indent=2))
