#!/usr/bin/env python3
"""Test Step 7: Fast listing comparison in compare_sites.

Proves:
  (a) Object only on one side is detected.
  (b) Same key with different content is detected.
  (c) Same bytes with different ETags (single-part plain MD5 vs multipart -1)
      detects ETag mismatch and confirms match via SHA-256 fallback.
  (d) Delete an object on one side with versioning on: creates a delete marker,
      key disappears from standard listing on A while present on B, reported as only_b.
  (e) Timing: fast vs deep vs old (BEFORE baseline).
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE_REPO = Path("/home/cloud_automator/setu-starter")
MC = str(BASE_REPO / "scripts" / "mc.sh")
MC_CONFIG_DIR = Path(os.environ.get("HOME", "/home/cloud_automator")) / ".setu-mc"

sys.path.insert(0, str(BASE_REPO / "controller"))
from proof import compare_sites, list_objects_meta


def mc(*args, **kwargs):
    return subprocess.run([MC, *args], cwd=BASE_REPO,
                          capture_output=True, check=False, **kwargs)


def get_rule_ids():
    """Return (rule_id_a, rule_id_b) for both active-active replication rules."""
    res_a = mc("replicate", "ls", "--json", "site-a/demo")
    res_b = mc("replicate", "ls", "--json", "site-b/demo")
    rid_a = json.loads(res_a.stdout)["rule"]["ID"]
    rid_b = json.loads(res_b.stdout)["rule"]["ID"]
    return rid_a, rid_b


def disable_replication_both(rid_a, rid_b):
    mc("replicate", "update", "site-a/demo", "--id", rid_a, "--state", "disable")
    mc("replicate", "update", "site-b/demo", "--id", rid_b, "--state", "disable")
    print(f"  Replication DISABLED on BOTH sites")


def enable_replication_both(rid_a, rid_b):
    mc("replicate", "update", "site-a/demo", "--id", rid_a, "--state", "enable")
    mc("replicate", "update", "site-b/demo", "--id", rid_b, "--state", "enable")
    res_a = mc("replicate", "ls", "--json", "site-a/demo")
    res_b = mc("replicate", "ls", "--json", "site-b/demo")
    sa = json.loads(res_a.stdout)["rule"]["Status"]
    sb = json.loads(res_b.stdout)["rule"]["Status"]
    print(f"  Replication ENABLED on both sites (a={sa}, b={sb})")
    assert sa == "Enabled" and sb == "Enabled", "Replication rules not enabled!"


def test_a_only_on_one_side():
    """(a) Object only on site-a is detected."""
    print("\n=== TEST (a): Object only on one side ===")
    rid_a, rid_b = get_rule_ids()
    disable_replication_both(rid_a, rid_b)
    try:
        mc("pipe", "site-a/demo/step7-only-a.txt", input=b"only-on-a\n")
        print("  Wrote step7-only-a.txt to site-a only")

        t0 = time.monotonic()
        result = compare_sites(deep=False)
        elapsed = time.monotonic() - t0
        print(f"  compare_sites(fast): {elapsed:.1f}s")
        print(f"  Result: match={result['match']}, only_a={result['only_a']}, sha256_checked={result['sha256_checked']}")

        assert not result["match"], "Expected match=false!"
        assert "demo/step7-only-a.txt" in result["only_a"], "Missing key not in only_a!"
        print("  PASS: Object only on one side correctly detected.")
    finally:
        mc("rm", "--force", "site-a/demo/step7-only-a.txt")
        enable_replication_both(rid_a, rid_b)


def test_b_different_content():
    """(b) Same key with different content detected."""
    print("\n=== TEST (b): Same key with different content ===")
    rid_a, rid_b = get_rule_ids()
    disable_replication_both(rid_a, rid_b)
    try:
        mc("pipe", "site-a/demo/step7-diff.txt", input=b"content-A-version\n")
        mc("pipe", "site-b/demo/step7-diff.txt", input=b"content-B-version\n")
        print("  Wrote step7-diff.txt with different content to A and B")

        meta_a = list_objects_meta("site-a")
        meta_b = list_objects_meta("site-b")
        ea = meta_a.get("demo/step7-diff.txt", ("?", "?"))
        eb = meta_b.get("demo/step7-diff.txt", ("?", "?"))
        print(f"  site-a ETag: {ea}, site-b ETag: {eb}")

        t0 = time.monotonic()
        result = compare_sites(deep=False)
        elapsed = time.monotonic() - t0
        print(f"  compare_sites(fast): {elapsed:.1f}s")
        print(f"  Result: match={result['match']}, different={result['different']}, sha256_checked={result['sha256_checked']}")

        assert not result["match"], "Expected match=false!"
        assert "demo/step7-diff.txt" in result["different"], "Differing key not in different!"
        assert result["sha256_checked"] >= 1, "Should have fallen back to SHA-256!"
        print("  PASS: Different content correctly detected via SHA-256 fallback.")
    finally:
        mc("rm", "--force", "site-a/demo/step7-diff.txt")
        mc("rm", "--force", "site-b/demo/step7-diff.txt")
        enable_replication_both(rid_a, rid_b)


def test_c_different_etags_identical_content():
    """(c) Same bytes, different ETags (single-part plain MD5 vs multipart -1).

    Proves:
    - Differing ETags for identical bytes are detected by the fast path.
    - compare_sites falls back to SHA-256 on differing ETags.
    - Because SHA-256 matches, it confirms identical content and reports match=True.
    """
    print("\n=== TEST (c): Same bytes, different ETags (SHA-256 fallback match) ===")
    rid_a, rid_b = get_rule_ids()
    disable_replication_both(rid_a, rid_b)
    sample_file = MC_CONFIG_DIR / "sample_etag.txt"
    payload = b"identical-bytes-differing-etags-payload\n"

    try:
        sample_file.write_bytes(payload)

        # Upload to site-a with --disable-multipart (single-part upload -> plain MD5)
        mc("cp", "--disable-multipart", "/mc-config/sample_etag.txt", "site-a/demo/step7-diff-etag.txt")

        # Upload to site-b with mc pipe (multipart streaming upload -> ETag ends in -1)
        mc("pipe", "site-b/demo/step7-diff-etag.txt", input=payload)

        meta_a = list_objects_meta("site-a")
        meta_b = list_objects_meta("site-b")
        size_a, etag_a = meta_a.get("demo/step7-diff-etag.txt", (-1, ""))
        size_b, etag_b = meta_b.get("demo/step7-diff-etag.txt", (-1, ""))
        print(f"  site-a: size={size_a}, ETag={etag_a} (single-part plain MD5)")
        print(f"  site-b: size={size_b}, ETag={etag_b} (multipart upload ending in -1)")

        assert size_a == size_b, "Sizes must match!"
        assert etag_a != etag_b, f"ETags should differ! a={etag_a}, b={etag_b}"
        assert not etag_a.endswith("-1"), "site-a ETag should be a plain MD5 without -N suffix!"
        assert etag_b.endswith("-1"), "site-b ETag should have -1 multipart suffix!"

        # Run compare_sites in fast mode
        t0 = time.monotonic()
        result = compare_sites(deep=False)
        elapsed = time.monotonic() - t0

        print(f"  compare_sites(fast): {elapsed:.1f}s")
        print(f"  Result: match={result['match']}, sha256_checked={result['sha256_checked']}, different={result['different']}")

        assert result["match"], f"Expected match=true via SHA-256 fallback! Got {result}"
        assert result["sha256_checked"] >= 1, "Expected SHA-256 check fallback for differing ETag!"
        assert "demo/step7-diff-etag.txt" not in result["different"], "Object should not be in different!"
        print("  PASS: Differing ETags with identical content confirmed matching via SHA-256 fallback.")
    finally:
        if sample_file.exists():
            sample_file.unlink()
        mc("rm", "--force", "site-a/demo/step7-diff-etag.txt")
        mc("rm", "--force", "site-b/demo/step7-diff-etag.txt")
        enable_replication_both(rid_a, rid_b)


def test_d_delete_object_versioning():
    """(d) Delete an object on one side with versioning on.

    In S3 versioning, 'mc rm' places a delete marker as the latest version.
    Standard listing ('mc ls') hides objects whose latest version is a delete marker.
    Therefore:
    - Object is hidden from site-a listing.
    - Object remains present in site-b listing.
    - compare_sites detects the asymmetry and reports match=false, only_b=['demo/step7-del.txt'].
    """
    print("\n=== TEST (d): Delete object on one side with versioning on ===")
    rid_a, rid_b = get_rule_ids()
    disable_replication_both(rid_a, rid_b)
    key = "demo/step7-del.txt"

    try:
        # Write identical object to both sides
        mc("pipe", f"site-a/{key}", input=b"version-delete-marker-test\n")
        mc("pipe", f"site-b/{key}", input=b"version-delete-marker-test\n")

        # Verify initial match
        res_init = compare_sites(deep=False)
        assert res_init["match"], "Initial state must match!"

        # Delete object on site-a only (creates a delete marker)
        rm_res = mc("rm", f"site-a/{key}")
        print(f"  mc rm site-a output: {rm_res.stdout.decode().strip() or rm_res.stderr.decode().strip()}")

        # Run compare_sites
        result = compare_sites(deep=False)
        print(f"  compare_sites result after delete on A:")
        print(f"    match={result['match']}, only_a={result['only_a']}, only_b={result['only_b']}")

        assert not result["match"], "Expected match=false after soft-delete on A!"
        assert key in result["only_b"], f"Expected {key} in only_b, got {result['only_b']}"
        assert key not in result["only_a"], f"{key} should not be in only_a"

        print("  EXPLANATION:")
        print("    In MinIO with bucket versioning enabled, deleting an object inserts a delete marker.")
        print("    Standard S3 listings (mc ls --recursive) filter out keys whose current revision is a delete marker.")
        print("    Consequently, site-a omits the key while site-b still lists it.")
        print("    compare_sites() flags this divergence as only_b, safely preventing failback.")
        print("  PASS: Soft-deleted versioned object asymmetry correctly detected.")
    finally:
        mc("rm", "--force", f"site-a/{key}")
        mc("rm", "--force", f"site-b/{key}")
        enable_replication_both(rid_a, rid_b)


def test_e_timing():
    """(e) Timing: fast path vs deep path at current object count."""
    print("\n=== TEST (e): Timing comparison ===")

    # Fast path
    t0 = time.monotonic()
    result_fast = compare_sites(deep=False)
    elapsed_fast = time.monotonic() - t0
    print(f"  Fast path: {elapsed_fast:.1f}s, {result_fast['count_a']} objects per site, sha256_checked={result_fast['sha256_checked']}")
    assert result_fast["match"], f"Expected match=true on clean data! {result_fast}"

    # Deep path
    t0 = time.monotonic()
    result_deep = compare_sites(deep=True)
    elapsed_deep = time.monotonic() - t0
    print(f"  Deep path: {elapsed_deep:.1f}s, {result_deep['count_a']} objects per site, sha256_checked={result_deep['sha256_checked']}")
    assert result_deep["match"], f"Expected match=true on clean data! {result_deep}"
    assert result_deep["sha256_checked"] == result_deep["count_a"], "Deep should check all shared keys!"

    print(f"\n  TIMING SUMMARY:")
    print(f"    BEFORE optimization (old mc cat):  ~145.7s  (measured separately)")
    print(f"    AFTER  fast path (ETag):            {elapsed_fast:.1f}s  ({result_fast['sha256_checked']} SHA-256 checks)")
    print(f"    AFTER  deep path (all SHA-256):     {elapsed_deep:.1f}s  ({result_deep['sha256_checked']} SHA-256 checks)")
    speedup = 145.7 / max(elapsed_fast, 0.01)
    print(f"    Speedup (fast vs old):              {speedup:.0f}x")
    print("  PASS: Timing recorded.")


if __name__ == "__main__":
    test_a_only_on_one_side()
    test_b_different_content()
    test_c_different_etags_identical_content()
    test_d_delete_object_versioning()
    test_e_timing()
    print("\n=== STEP 7 ALL TESTS (a, b, c, d, e) PASSED ===")
