"""
scripts/calibrate.py

Runs calibration for tests listed in scripts/calibrate_targets.txt:
- 100 iterations in isolation per test.
- 20 iterations as part of the full test suite in standard suite order.
Prints failure counts and failure rates per test.
Does not send or post network payloads anywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _run_cmd(cmd: list[str], cwd: Path) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    targets_file = repo_root / "scripts" / "calibrate_targets.txt"

    if not targets_file.is_file():
        print(f"[calibrate] ERROR: Targets file not found: {targets_file}", file=sys.stderr)
        sys.exit(1)

    targets = [
        line.strip()
        for line in targets_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not targets:
        print("[calibrate] No target tests found in calibrate_targets.txt", file=sys.stderr)
        sys.exit(1)

    print(f"[calibrate] Calibrating {len(targets)} target test(s)...")
    print("[calibrate] Protocol: 100 runs in isolation, 20 runs within full test suite in standard suite order.\n")

    results = []

    for target in targets:
        print(f"--- Calibrating: {target} ---")

        # 1. 100 runs in isolation
        isolation_failures = 0
        isolation_runs = 100
        for _ in range(isolation_runs):
            cmd = [sys.executable, "-m", "pytest", target, "-q", "--tb=no"]
            rc = _run_cmd(cmd, repo_root)
            if rc != 0:
                isolation_failures += 1

        isolation_rate = (isolation_failures / isolation_runs) * 100.0
        print(f"  Isolation:  {isolation_failures}/{isolation_runs} failures ({isolation_rate:.1f}%)")

        # 2. 20 runs within full test suite in standard suite order
        suite_failures = 0
        suite_runs = 20
        for _ in range(suite_runs):
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = tmp.name
            cmd = [
                sys.executable, "-m", "pytest", "tests",
                "-q", "--tb=no",
                "--json-report", f"--json-report-file={tmp_path}",
            ]
            _run_cmd(cmd, repo_root)
            failed_in_suite = False
            if os.path.exists(tmp_path):
                try:
                    with open(tmp_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for t in data.get("tests", []):
                        if t.get("nodeid") == target and t.get("outcome") == "failed":
                            failed_in_suite = True
                            break
                except Exception:
                    pass
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            if failed_in_suite:
                suite_failures += 1

        suite_rate = (suite_failures / suite_runs) * 100.0
        print(f"  Full Suite: {suite_failures}/{suite_runs} failures ({suite_rate:.1f}%)\n")

        results.append({
            "target": target,
            "isolation_failures": isolation_failures,
            "isolation_runs": isolation_runs,
            "isolation_rate": isolation_rate,
            "suite_failures": suite_failures,
            "suite_runs": suite_runs,
            "suite_rate": suite_rate,
        })

    print("================================================================================")
    print("CALIBRATION SUMMARY")
    print("================================================================================")
    print(f"{'Test Node ID':<75} | {'Isolation Failures':<18} | {'Suite Failures':<15}")
    print("-" * 115)
    for r in results:
        iso_str = f"{r['isolation_failures']}/{r['isolation_runs']} ({r['isolation_rate']:.1f}%)"
        suite_str = f"{r['suite_failures']}/{r['suite_runs']} ({r['suite_rate']:.1f}%)"
        print(f"{r['target']:<75} | {iso_str:<18} | {suite_str:<15}")
    print("================================================================================")


if __name__ == "__main__":
    main()
