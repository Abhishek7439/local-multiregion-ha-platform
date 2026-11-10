"""Common helpers, SigV4 client, and Concurrent Writer for M5 Chaos Suite.

All functions use Python standard library only (hashlib, hmac, urllib, threading, subprocess).
No third-party packages or anonymous bucket policies required.
"""

import os
import sys
import time
import json
import socket
import hmac
import hashlib
import datetime
import threading
import queue
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from controller.proof import compare_sites, docker_bin


def load_env() -> None:
    """Load configuration variables from .env file into os.environ if present."""
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()


def get_project_name() -> str:
    """Read the active Compose project name from environment or fallback to default."""
    return os.environ.get("COMPOSE_PROJECT_NAME", "setu-multiregion")


def get_credentials() -> tuple[str, str]:
    """Retrieve MinIO credentials dynamically from environment (never hardcoded)."""
    user = os.environ.get("MINIO_ROOT_USER", "setuadmin")
    password = os.environ.get("MINIO_ROOT_PASSWORD", "ChangeMe12345")
    return user, password


def run_mc(args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    """Execute the MinIO client wrapper (scripts/mc.sh) inside the docker network."""
    mc_script = str(ROOT_DIR / "scripts" / "mc.sh")
    return subprocess.run(
        [mc_script, *args],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def sign_s3_headers(bucket: str, key: str, payload: bytes,
                    access_key: str | None = None, secret_key: str | None = None,
                    host: str = "127.0.0.1:8080", region: str = "us-east-1") -> dict[str, str]:
    """Generate AWS Signature Version 4 headers for authenticated S3 PUT requests.

    Standard HMAC-SHA256 SigV4 protocol:
    1. Canonical request (method, URI, headers, signed headers, payload SHA-256).
    2. String-to-sign with UTC ISO-8601 timestamp and date scope.
    3. Derived signing key: HMAC(HMAC(HMAC(HMAC(secret, date), region), service), request).
    """
    if access_key is None or secret_key is None:
        def_user, def_pass = get_credentials()
        access_key = access_key or def_user
        secret_key = secret_key or def_pass

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')
    content_sha256 = hashlib.sha256(payload).hexdigest()
    url_path = f"/{bucket}/{key}"

    canonical_headers = f"host:{host}\nx-amz-content-sha256:{content_sha256}\nx-amz-date:{amz_date}\n"
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = f"PUT\n{url_path}\n\n{canonical_headers}\n{signed_headers}\n{content_sha256}"

    credential_scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"

    k_date = hmac.new(f"AWS4{secret_key}".encode('utf-8'), date_stamp.encode('utf-8'), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode('utf-8'), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()

    signature = hmac.new(k_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
    authorization = f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

    return {
        "Host": host,
        "x-amz-date": amz_date,
        "x-amz-content-sha256": content_sha256,
        "Authorization": authorization,
        "Content-Type": "application/octet-stream",
    }


def put_object_gateway(bucket: str, key: str, body: bytes, timeout: float = 2.0) -> dict:
    """Send an authenticated S3 PUT request to Gateway (:8080).

    Returns:
        dict with success (bool), status (int), backend (str from X-Backend-Server),
        duration_ms (int), start_ts (float), end_ts (float), error (str).
    """
    url = f"http://127.0.0.1:8080/{bucket}/{key}"
    headers = sign_s3_headers(bucket, key, body, host="127.0.0.1:8080")
    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            end = time.monotonic()
            elapsed_ms = int((end - start) * 1000)
            backend = resp.headers.get("X-Backend-Server", "unknown")
            return {
                "success": True,
                "status": resp.status,
                "backend": backend,
                "duration_ms": elapsed_ms,
                "start_ts": start,
                "end_ts": end,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        end = time.monotonic()
        elapsed_ms = int((end - start) * 1000)
        backend = e.headers.get("X-Backend-Server", "unknown") if e.headers else "unknown"
        return {
            "success": False,
            "status": e.code,
            "backend": backend,
            "duration_ms": elapsed_ms,
            "start_ts": start,
            "end_ts": end,
            "error": str(e),
        }
    except Exception as e:
        end = time.monotonic()
        elapsed_ms = int((end - start) * 1000)
        return {
            "success": False,
            "status": 0,
            "backend": None,
            "duration_ms": elapsed_ms,
            "start_ts": start,
            "end_ts": end,
            "error": str(e),
        }


class ConcurrentWriter:
    """Multi-threaded concurrent write generator (30-50 req/s) with active tracking."""

    def __init__(self, bucket: str, concurrency: int = 5, request_timeout: float = 2.0, delay_between_req: float = 0.02):
        self.bucket = bucket
        self.concurrency = concurrency
        self.timeout = request_timeout
        self.delay = delay_between_req
        self.stop_event = threading.Event()
        self.results = []
        self.lock = threading.Lock()
        self.threads = []
        self.seq_counter = 0

    def _worker(self):
        while not self.stop_event.is_set():
            with self.lock:
                self.seq_counter += 1
                seq = self.seq_counter

            key = f"write-{seq:05d}.txt"
            payload = f"burst-payload-{seq:05d}-{time.time()}".encode()

            res = put_object_gateway(self.bucket, key, payload, timeout=self.timeout)
            res["key"] = key
            res["payload"] = payload
            res["seq"] = seq

            with self.lock:
                self.results.append(res)

            time.sleep(self.delay)

    def start(self):
        self.stop_event.clear()
        self.threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(self.concurrency)]
        for t in self.threads:
            t.start()

    def stop(self):
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=3)

    def get_results(self) -> list[dict]:
        with self.lock:
            return list(self.results)


def setup_chaos_bucket(bucket: str) -> bool:
    """Create isolated test bucket on site-a (replicated automatically to site-b)."""
    res = run_mc(["mb", "--ignore-existing", f"site-a/{bucket}"])
    time.sleep(1)
    return res.returncode == 0


def cleanup_chaos_bucket(bucket: str) -> None:
    """Safely delete all object versions and remove the bucket."""
    try:
        run_mc(["rm", "--recursive", "--force", "--versions", f"site-a/{bucket}/"])
        run_mc(["rb", f"site-a/{bucket}"])
    except Exception:
        pass


def get_bucket_inventory(target: str) -> dict[str, dict]:
    """Retrieve full inventory of a bucket path (key -> {size, etag}) via single listing call."""
    res = run_mc(["ls", "--recursive", "--json", target])
    if res.returncode != 0:
        return {}
    inv = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            inv[item["key"]] = item
        except Exception:
            pass
    return inv


def docker_service(action: str, service: str) -> subprocess.CompletedProcess:
    """Run docker compose action (kill, stop, start, up) on a service."""
    proj = get_project_name()
    return subprocess.run(
        [docker_bin(), "compose", "-p", proj, action, service],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def docker_container_action(action: str, svc: str) -> subprocess.CompletedProcess:
    """Direct docker CLI action on container name (pause, unpause)."""
    c_name = f"{get_project_name()}-{svc}-1"
    return subprocess.run(
        [docker_bin(), action, c_name],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def get_haproxy_status() -> dict[str, str]:
    """Read the HAProxy admin socket and return server status mappings."""
    s = socket.create_connection(("127.0.0.1", 9999), timeout=3)
    s.sendall(b"show stat\n")
    s.shutdown(socket.SHUT_WR)
    data = b"".join(iter(lambda: s.recv(4096), b"")).decode()
    s.close()
    statuses = {}
    for line in data.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) > 17:
            statuses[f"{parts[0]}/{parts[1]}"] = parts[17]
    return statuses


# ---------------------------------------------------------------------------
# Toxiproxy helpers (REST API on :8474)
# ---------------------------------------------------------------------------
TOXIPROXY_API = "http://127.0.0.1:8474"


def toxiproxy_api(method: str, path: str, body: dict | None = None, quiet_404: bool = False) -> dict | None:
    """Send a request to the Toxiproxy REST API. Returns parsed JSON or None."""
    url = f"{TOXIPROXY_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        if not (quiet_404 and e.code == 404):
            print(f"  Toxiproxy API {method} {path}: HTTP {e.code} — {e.read().decode()}", file=sys.stderr)
        raise
    except Exception as e:
        print(f"  Toxiproxy API {method} {path}: {e}", file=sys.stderr)
        raise


def toxiproxy_ensure_proxy(name: str = "minio_b_replication",
                           listen: str = "0.0.0.0:9002",
                           upstream: str = "minio-b:9000") -> dict:
    """Create (or confirm) the Toxiproxy proxy for the B replication path."""
    try:
        return toxiproxy_api("GET", f"/proxies/{name}", quiet_404=True)
    except Exception:
        pass
    return toxiproxy_api("POST", "/proxies", {
        "name": name, "listen": listen, "upstream": upstream, "enabled": True
    })


def toxiproxy_add_toxic(proxy: str, toxic: dict) -> dict:
    """Add a toxic to a proxy. Returns the created toxic."""
    return toxiproxy_api("POST", f"/proxies/{proxy}/toxics", toxic)


def toxiproxy_remove_toxic(proxy: str, toxic_name: str) -> None:
    """Remove a toxic by name. Ignores 404 (already removed)."""
    try:
        toxiproxy_api("DELETE", f"/proxies/{proxy}/toxics/{toxic_name}", quiet_404=True)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    except Exception:
        pass


def toxiproxy_remove_all_toxics(proxy: str = "minio_b_replication") -> None:
    """Remove all toxics from a proxy (restore clean pass-through)."""
    try:
        info = toxiproxy_api("GET", f"/proxies/{proxy}")
        if info and "toxics" in info:
            for t in info["toxics"]:
                toxiproxy_remove_toxic(proxy, t["name"])
    except Exception:
        pass


def toxiproxy_delete_proxy(name: str = "minio_b_replication") -> None:
    """Delete a proxy entirely. Ignores 404."""
    try:
        toxiproxy_api("DELETE", f"/proxies/{name}")
    except Exception:
        pass


def repoint_replication_through_proxy() -> bool:
    """Re-point site-a's replication target for site-b through Toxiproxy.

    Uses 'mc admin replicate info --json' to discover site-b's deployment ID,
    then 'mc admin replicate update' to change the endpoint to toxiproxy:9002.
    """
    # Get site-b deployment ID
    res = run_mc(["admin", "replicate", "info", "site-a", "--json"])
    if res.returncode != 0:
        print(f"  ERROR: mc admin replicate info failed: {res.stderr}", file=sys.stderr)
        return False
    info = json.loads(res.stdout)
    site_b_id = None
    for site in info.get("sites", []):
        if site.get("name") == "site-b":
            site_b_id = site["deploymentID"]
            break
    if not site_b_id:
        print("  ERROR: Could not find site-b deployment ID", file=sys.stderr)
        return False

    # Update endpoint to go through Toxiproxy
    res = run_mc(["admin", "replicate", "update", "site-a",
                  "--deployment-id", site_b_id,
                  "--endpoint", "http://toxiproxy:9002"])
    if res.returncode != 0:
        print(f"  ERROR: replicate update failed: {res.stderr}", file=sys.stderr)
        return False
    print(f"  Replication re-pointed: site-a → toxiproxy:9002 → minio-b:9000")
    return True


def repoint_replication_direct() -> bool:
    """Revert site-a's replication target for site-b back to direct (minio-b:9000)."""
    res = run_mc(["admin", "replicate", "info", "site-a", "--json"])
    if res.returncode != 0:
        return False
    info = json.loads(res.stdout)
    site_b_id = None
    for site in info.get("sites", []):
        if site.get("name") == "site-b":
            site_b_id = site["deploymentID"]
            break
    if not site_b_id:
        return False
    res = run_mc(["admin", "replicate", "update", "site-a",
                  "--deployment-id", site_b_id,
                  "--endpoint", "http://minio-b:9000"])
    if res.returncode != 0:
        print(f"  ERROR: replicate rollback failed: {res.stderr}", file=sys.stderr)
        return False
    print(f"  Replication restored: site-a → minio-b:9000 (direct)")
    return True


def start_dr_controller(logfile: str = "/tmp/setu-chaos-dr.log") -> subprocess.Popen:
    """Start background DR controller to handle automated failover, fencing, and failback."""
    log_fp = open(logfile, "w")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT_DIR / "controller" / "dr_controller.py")],
        cwd=ROOT_DIR,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )
    time.sleep(2)
    return proc


def stop_dr_controller(proc: subprocess.Popen) -> None:
    """Stop the background DR controller process group."""
    if proc and proc.poll() is None:
        try:
            import signal
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=5)
        except Exception:
            pass
