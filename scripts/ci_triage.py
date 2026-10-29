"""
scripts/ci_triage.py

Automated CI triage script:
1. Runs pytest with JSON reporting.
2. Identifies failing tests and reruns each 5 times in isolation.
3. Constructs structured failure payloads.
4. Serializes payload to bytes and signs with HMAC-SHA256 using WEBHOOK_SECRET.
5. Transmits payload to WEBHOOK_URL with 3 retries and exponential backoff.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests


def _run_pytest_initial(repo_root: Path, report_file: str) -> tuple[int, dict[str, Any]]:
    cmd = [
        sys.executable, "-m", "pytest",
        "tests",
        "--tb=short",
        "--json-report",
        f"--json-report-file={report_file}",
    ]
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    report: dict[str, Any] = {}
    if os.path.exists(report_file):
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception:
            pass
    return proc.returncode, report


def _rerun_test_in_isolation(repo_root: Path, nodeid: str, count: int = 5) -> list[str]:
    results = []
    for _ in range(count):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
        cmd = [
            sys.executable, "-m", "pytest",
            nodeid,
            "--tb=short",
            "--json-report",
            f"--json-report-file={tmp_path}",
        ]
        proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        results.append("fail" if proc.returncode != 0 else "pass")
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return results


def _extract_failures(report: dict[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for test in report.get("tests", []):
        if test.get("outcome") != "failed":
            continue
        call = test.get("call") or {}
        location = test.get("location") or {}
        nodeid = test.get("nodeid", "")
        stack_trace = call.get("longrepr", "")

        lines = stack_trace.splitlines() if isinstance(stack_trace, str) else []
        diff_lines = [l for l in lines if l.startswith(("+", "-", "E ", "AssertionError"))]
        assertion_diff = "\n".join(diff_lines[:20]) if diff_lines else ""

        failures.append({
            "nodeid": nodeid,
            "test_name": nodeid.split("::")[-1],
            "file": location.get("filename", ""),
            "line": location.get("lineno", 0),
            "stack_trace": stack_trace[:2000] if isinstance(stack_trace, str) else str(stack_trace)[:2000],
            "assertion_diff": assertion_diff[:500],
        })
    return failures


def _get_commit_sha(repo_root: Path) -> str:
    env_sha = os.getenv("GITHUB_SHA")
    if env_sha:
        return env_sha
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _get_ref() -> str:
    return os.getenv("GITHUB_REF", "refs/heads/main")


def _get_repo(repo_root: Path) -> str:
    env_repo = os.getenv("GITHUB_REPOSITORY")
    if env_repo:
        return env_repo
    try:
        proc = subprocess.run(["git", "config", "--get", "remote.origin.url"], cwd=str(repo_root), capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return "idt-target-repo"


def _get_run_id() -> str:
    gh_run_id = os.getenv("GITHUB_RUN_ID")
    gh_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    if gh_run_id:
        return f"{gh_run_id}-{gh_attempt}"
    return f"local-{int(time.time())}"


def main() -> None:
    webhook_url = os.getenv("WEBHOOK_URL")
    webhook_secret = os.getenv("WEBHOOK_SECRET")

    if not webhook_url:
        print("[ci_triage] ERROR: WEBHOOK_URL environment variable is not configured.", file=sys.stderr)
        sys.exit(1)

    if not webhook_secret:
        print("[ci_triage] ERROR: WEBHOOK_SECRET environment variable is not configured.", file=sys.stderr)
        sys.exit(1)

    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        initial_report_file = tmp.name

    try:
        print(f"[ci_triage] Executing test suite with JSON reporting in {repo_root}...")
        rc, report = _run_pytest_initial(repo_root, initial_report_file)
        failures = _extract_failures(report)
    finally:
        if os.path.exists(initial_report_file):
            try:
                os.unlink(initial_report_file)
            except OSError:
                pass

    if not failures:
        print("[ci_triage] All tests passed. No triage required.")
        return

    commit_sha = _get_commit_sha(repo_root)
    git_ref = _get_ref()
    repo_name = _get_repo(repo_root)
    run_id = _get_run_id()

    print(f"[ci_triage] Identified {len(failures)} failed test(s). Starting isolation reruns...")

    all_delivered = True

    for failure in failures:
        nodeid = failure["nodeid"]
        print(f"[ci_triage] Rerunning '{nodeid}' 5 times in isolation...")
        rerun_results = _rerun_test_in_isolation(repo_root, nodeid, count=5)
        print(f"[ci_triage] Rerun results: {rerun_results}")

        payload = {
            "run_id": run_id,
            "commit_sha": commit_sha,
            "ref": git_ref,
            "repo": repo_name,
            "failing_test": failure["test_name"],
            "stack_trace": failure["stack_trace"],
            "assertion_diff": failure["assertion_diff"],
            "rerun_results": rerun_results,
        }

        # Serialize payload once to bytes
        payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        # Sign exact bytes with HMAC-SHA256 using WEBHOOK_SECRET
        mac = hmac.new(webhook_secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        timestamp = str(int(time.time()))

        headers = {
            "Content-Type": "application/json",
            "X-Signature-256": f"sha256={mac}",
            "X-Timestamp": timestamp,
            "ngrok-skip-browser-warning": "1",
        }

        delivered = False
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[ci_triage] Posting failure payload to webhook (attempt {attempt}/{max_retries})...")
                resp = requests.post(
                    webhook_url,
                    data=payload_bytes,
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code in (200, 201, 202, 204):
                    print(f"[ci_triage] Triage payload delivered successfully (HTTP {resp.status_code}).")
                    delivered = True
                    break
                else:
                    print(f"[ci_triage] Delivery attempt {attempt} returned status HTTP {resp.status_code}.", file=sys.stderr)
            except requests.RequestException as exc:
                print(f"[ci_triage] Delivery attempt {attempt} encountered network error: {exc}", file=sys.stderr)

            if attempt < max_retries:
                delay = 2 ** attempt
                print(f"[ci_triage] Retrying in {delay}s...")
                time.sleep(delay)

        if not delivered:
            print(f"[ci_triage] ERROR: Failed to deliver payload for '{failure['test_name']}' after {max_retries} attempts.", file=sys.stderr)
            all_delivered = False

    if not all_delivered:
        sys.exit(1)


if __name__ == "__main__":
    main()

