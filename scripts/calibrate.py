"""
scripts/calibrate.py

Runs calibration for tests listed in scripts/calibrate_targets.txt.
Supports two execution modes:
- mode=calibrate:
  Runs 100 iterations in isolation per test, and 20 iterations within the
  full test suite in standard suite order. Prints counts k/n with 95% Wilson
  confidence intervals.
- mode=triage-sim:
  Measures isolation rate per target (100 iterations), then repeats 300
  times running the suite in standard suite order. For each failing target,
  reruns 5 times in isolation and classifies via the observations rule.
  Prints triggers, labeled intermittent, labeled deterministic, intervals,
  and theoretical p^5 lower bounds.

Does not send or post network payloads anywhere.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Calculate the Wilson score confidence interval for a binomial proportion."""
    if n <= 0:
        return (0.0, 0.0)
    z = 1.959963984540054  # 95% confidence z-value
    p_hat = k / n
    denominator = 1.0 + (z ** 2) / n
    center = (p_hat + (z ** 2) / (2 * n)) / denominator
    margin = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / n) + ((z ** 2) / (4 * (n ** 2))))
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return (lower, upper)


def _fmt_interval(k: int, n: int) -> str:
    """Format k/n count with percentage and 95% Wilson interval."""
    if n <= 0:
        return f"{k}/{n} (0.0%) [95% CI 0.0%, 0.0%]"
    pct = (k / n) * 100.0
    low, high = _wilson_score_interval(k, n)
    return f"{k}/{n} ({pct:.1f}%) [95% CI {low * 100.0:.1f}%, {high * 100.0:.1f}%]"


def _run_cmd(cmd: list[str], cwd: Path) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return proc.returncode


def _run_suite_and_get_failures(repo_root: Path) -> set[str]:
    """Execute full test suite in standard suite order and return failing nodeids."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name
    cmd = [
        sys.executable, "-m", "pytest", "tests",
        "-q", "--tb=no",
        "--json-report", f"--json-report-file={tmp_path}",
    ]
    _run_cmd(cmd, repo_root)

    failed_nodeids: set[str] = set()
    if os.path.exists(tmp_path):
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for t in data.get("tests", []):
                if t.get("outcome") == "failed":
                    failed_nodeids.add(t.get("nodeid", ""))
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return failed_nodeids


def _run_isolation_reruns(repo_root: Path, target: str, count: int = 5) -> list[str]:
    """Rerun a single test in isolation and return list of outcomes ('pass' or 'fail')."""
    outcomes: list[str] = []
    for _ in range(count):
        cmd = [sys.executable, "-m", "pytest", target, "-q", "--tb=no"]
        rc = _run_cmd(cmd, repo_root)
        outcomes.append("fail" if rc != 0 else "pass")
    return outcomes


def _run_calibrate_mode(repo_root: Path, targets: list[str]) -> None:
    print(f"[calibrate] Running mode=calibrate for {len(targets)} target test(s)...")
    print("[calibrate] Protocol: 100 runs in isolation, 20 runs within full test suite in standard suite order.\n")

    results: list[dict[str, Any]] = []

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

        iso_str = _fmt_interval(isolation_failures, isolation_runs)
        print(f"  Isolation:  {iso_str}")

        # 2. 20 runs within full test suite in standard suite order
        suite_failures = 0
        suite_runs = 20
        for _ in range(suite_runs):
            failed_tests = _run_suite_and_get_failures(repo_root)
            if target in failed_tests:
                suite_failures += 1

        suite_str = _fmt_interval(suite_failures, suite_runs)
        print(f"  Full Suite: {suite_str}\n")

        results.append({
            "target": target,
            "isolation_k": isolation_failures,
            "isolation_n": isolation_runs,
            "suite_k": suite_failures,
            "suite_n": suite_runs,
        })

    print("=" * 135)
    print("CALIBRATION SUMMARY (95% Wilson Score Confidence Intervals)")
    print("=" * 135)
    print(f"{'Test Node ID':<70} | {'Isolation Failures (95% CI)':<31} | {'Suite Failures (95% CI)':<28}")
    print("-" * 135)
    for r in results:
        iso_s = _fmt_interval(r["isolation_k"], r["isolation_n"])
        suite_s = _fmt_interval(r["suite_k"], r["suite_n"])
        print(f"{r['target']:<70} | {iso_s:<31} | {suite_s:<28}")
    print("=" * 135)


def _run_triage_sim_mode(repo_root: Path, targets: list[str], sim_iterations: int = 300) -> None:
    print(f"[calibrate] Running mode=triage-sim with {sim_iterations} iterations across {len(targets)} target(s)...")
    print("[calibrate] Protocol: Measure isolation rate (100 runs), then 300 suite runs with 5x isolation reruns on trigger.\n")

    # Step 1: Measure baseline isolation failure rate per target
    print("--- Step 1: Measuring Isolation Failure Rates (100 runs each) ---")
    iso_stats: dict[str, dict[str, Any]] = {}
    for target in targets:
        iso_k = 0
        iso_n = 100
        for _ in range(iso_n):
            cmd = [sys.executable, "-m", "pytest", target, "-q", "--tb=no"]
            if _run_cmd(cmd, repo_root) != 0:
                iso_k += 1
        p_iso = iso_k / iso_n
        low_iso, high_iso = _wilson_score_interval(iso_k, iso_n)
        p5_theoretical = p_iso ** 5
        p5_low = low_iso ** 5
        p5_high = high_iso ** 5
        iso_stats[target] = {
            "iso_k": iso_k,
            "iso_n": iso_n,
            "p_iso": p_iso,
            "low_iso": low_iso,
            "high_iso": high_iso,
            "p5_theoretical": p5_theoretical,
            "p5_low": p5_low,
            "p5_high": p5_high,
        }
        print(f"  {target}: {_fmt_interval(iso_k, iso_n)} | Theoretical p^5 = {p5_theoretical * 100.0:.4f}% [CI {p5_low * 100.0:.4f}%, {p5_high * 100.0:.4f}%]")

    # Step 2: 300 Triage Simulation Iterations
    print(f"\n--- Step 2: Simulating {sim_iterations} Suite Triage Cycles ---")
    triggers: dict[str, int] = {t: 0 for t in targets}
    labeled_intermittent: dict[str, int] = {t: 0 for t in targets}
    labeled_deterministic: dict[str, int] = {t: 0 for t in targets}

    for iteration in range(1, sim_iterations + 1):
        failed_tests = _run_suite_and_get_failures(repo_root)

        for target in targets:
            if target in failed_tests:
                triggers[target] += 1
                rerun_outcomes = _run_isolation_reruns(repo_root, target, count=5)
                observations = ["fail"] + rerun_outcomes

                # Classification rule: all fail -> deterministic, mixed -> intermittent
                if all(o == "fail" for o in observations):
                    labeled_deterministic[target] += 1
                else:
                    labeled_intermittent[target] += 1

        if iteration % 50 == 0 or iteration == sim_iterations:
            print(f"  Progress: Completed {iteration}/{sim_iterations} suite iterations...")

    # Step 3: Print summary report
    print("\n" + "=" * 145)
    print("TRIAGE SIMULATION SUMMARY (300 Suite Cycles, R=5 Isolation Reruns)")
    print("=" * 145)
    header = f"{'Test Node ID':<50} | {'Triggers':<15} | {'Intermittent':<20} | {'Deterministic':<20} | {'Isolation Rate':<24} | {'p^5 Theoretical'}"
    print(header)
    print("-" * 145)

    for target in targets:
        trig = triggers[target]
        interm = labeled_intermittent[target]
        deter = labeled_deterministic[target]

        trig_str = f"{trig}/{sim_iterations} ({(trig/sim_iterations)*100:.1f}%)"
        interm_str = f"{interm}/{trig} ({_fmt_pct(interm, trig)})" if trig > 0 else "0/0 (N/A)"
        deter_str = f"{deter}/{trig} ({_fmt_pct(deter, trig)})" if trig > 0 else "0/0 (N/A)"

        iso_info = iso_stats[target]
        iso_str = f"{iso_info['iso_k']}/{iso_info['iso_n']} ({iso_info['p_iso']*100:.1f}%)"
        p5_str = f"{iso_info['p5_theoretical'] * 100.0:.2f}%"

        print(f"{target:<50} | {trig_str:<15} | {interm_str:<20} | {deter_str:<20} | {iso_str:<24} | {p5_str}")

    print("=" * 145)
    print("Intervals Detail (95% Wilson Score):")
    for target in targets:
        trig = triggers[target]
        interm = labeled_intermittent[target]
        deter = labeled_deterministic[target]
        iso_info = iso_stats[target]

        trig_ci = _fmt_interval(trig, sim_iterations)
        interm_ci = _fmt_interval(interm, trig) if trig > 0 else "0/0 (N/A)"
        deter_ci = _fmt_interval(deter, trig) if trig > 0 else "0/0 (N/A)"
        iso_ci = _fmt_interval(iso_info["iso_k"], iso_info["iso_n"])
        p5_ci = f"{iso_info['p5_theoretical'] * 100.0:.4f}% [CI {iso_info['p5_low'] * 100.0:.4f}%, {iso_info['p5_high'] * 100.0:.4f}%]"

        print(f"\nTarget: {target}")
        print(f"  - Suite Trigger Rate:        {trig_ci}")
        print(f"  - Labeled Intermittent:      {interm_ci}")
        print(f"  - Labeled Deterministic:     {deter_ci}")
        print(f"  - Measured Isolation Rate:   {iso_ci}")
        print(f"  - Theoretical p^5 Rate:      {p5_ci}")
    print("=" * 145)


def _fmt_pct(k: int, n: int) -> str:
    if n <= 0:
        return "0.0%"
    return f"{(k / n) * 100.0:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate target tests or run triage simulation.")
    parser.add_argument("--mode", choices=["calibrate", "triage-sim"], help="Execution mode (calibrate or triage-sim)")
    parser.add_argument("--sim-iterations", type=int, help="Number of iterations for triage-sim mode")

    args = parser.parse_args()
    mode = args.mode if args.mode else "calibrate"
    sim_iterations = args.sim_iterations if args.sim_iterations else 300

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

    if mode == "triage-sim":
        _run_triage_sim_mode(repo_root, targets, sim_iterations=sim_iterations)
    else:
        _run_calibrate_mode(repo_root, targets)


if __name__ == "__main__":
    main()
