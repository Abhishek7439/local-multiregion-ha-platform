import subprocess
import sys
import re

print("=== Running Comprehensive Secret & Credential Scan ===")

# 1. Check tracked files for .env
tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
env_tracked = [f for f in tracked if f == ".env" or f.endswith("/.env")]
print(f"Tracked .env files: {env_tracked}")
if env_tracked:
    print("ERROR: .env is tracked in git!")
    sys.exit(1)

# 2. Check for private keys and tokens in tracked files
patterns = [
    r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY",
    r"ghp_[A-Za-z0-9_]{36}",
    r"github_pat_[A-Za-z0-9_]{82}",
    r"AKIA[0-9A-Z]{16}",
]

violations = []
for f in tracked:
    # Skip binary files like pdf
    if f.endswith((".pdf", ".png", ".jpg", ".zip", ".ico")):
        continue
    try:
        with open(f, "r", encoding="utf-8", errors="ignore") as fp:
            content = fp.read()
            for p in patterns:
                matches = re.findall(p, content)
                if matches:
                    violations.append((f, p, len(matches)))
    except Exception as e:
        print(f"Could not read {f}: {e}")

print(f"Secret pattern violations in working tree: {violations}")
if violations:
    print("ERROR: Secrets found in working tree files!")
    sys.exit(1)

# 3. Check entire git log
print("Checking entire git commit history (git log -p)...")
git_log = subprocess.check_output(["git", "log", "-p"], text=True, errors="ignore")
history_violations = []
for p in patterns:
    matches = re.findall(p, git_log)
    if matches:
        history_violations.append((p, len(matches)))

print(f"Secret pattern violations in git history: {history_violations}")
if history_violations:
    print("ERROR: Secrets found in git history!")
    sys.exit(1)

print("=== SAFETY CHECK 1 PASSED: 0 secrets found, .env is untracked ===")

