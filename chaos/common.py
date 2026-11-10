"""Common helpers and SigV4 client for M5 Chaos Engineering Suite.

All functions use Python standard library only (hashlib, hmac, urllib, subprocess).
No third-party packages or anonymous bucket policies required.
"""

import os
import sys
import time
import socket
import hmac
import hashlib
import datetime
import urllib.request
import urllib.error
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from controller.proof import compare_sites, docker_bin


def get_project_name() -> str:
    """Read the active Compose project name from environment or fallback to default."""
    return os.environ.get("COMPOSE_PROJECT_NAME", "setu-multiregion")


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
                    access_key: str = "setuadmin", secret_key: str = "ChangeMe12345",
                    host: str = "127.0.0.1:8080", region: str = "us-east-1") -> dict[str, str]:
    """Generate AWS Signature Version 4 headers for authenticated S3 PUT requests.

    Standard HMAC-SHA256 SigV4 protocol:
    1. Canonical request (method, URI, headers, signed headers, payload SHA-256).
    2. String-to-sign with UTC ISO-8601 timestamp and date scope.
    3. Derived signing key: HMAC(HMAC(HMAC(HMAC(secret, date), region), service), request).
    """
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


def put_object_gateway(bucket: str, key: str, body: bytes, timeout: float = 2.5) -> dict:
    """Send an authenticated S3 PUT request to the Gateway (:8080).

    Captures the response status code, elapsed roundtrip time, and the
    X-Backend-Server header injected by HAProxy to track which backend handled it.
    """
    url = f"http://127.0.0.1:8080/{bucket}/{key}"
    headers = sign_s3_headers(bucket, key, body, host="127.0.0.1:8080")
    req = urllib.request.Request(url, data=body, headers=headers, method="PUT")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            backend = resp.headers.get("X-Backend-Server", "unknown")
            return {
                "success": True,
                "status": resp.status,
                "backend": backend,
                "duration_ms": elapsed_ms,
                "error": None,
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        backend = e.headers.get("X-Backend-Server", "unknown") if e.headers else "unknown"
        return {
            "success": False,
            "status": e.code,
            "backend": backend,
            "duration_ms": elapsed_ms,
            "error": str(e),
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return {
            "success": False,
            "status": 0,
            "backend": None,
            "duration_ms": elapsed_ms,
            "error": str(e),
        }


def setup_chaos_bucket(bucket: str) -> bool:
    """Create an isolated bucket on site-a (which MinIO automatically replicates to site-b)."""
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


def docker_service(action: str, service: str) -> subprocess.CompletedProcess:
    """Run docker compose action (e.g. kill, stop, pause, unpause, start) on a service."""
    proj = get_project_name()
    return subprocess.run(
        [docker_bin(), "compose", "-p", proj, action, service],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


def docker_container_action(action: str, svc: str) -> subprocess.CompletedProcess:
    """Direct docker CLI action on container name (useful for docker pause / unpause)."""
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
