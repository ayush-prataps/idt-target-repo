"""
scripts/calibrate.py

Runs calibration for tests listed in scripts/calibrate_targets.txt.
Supports three execution modes:
- mode=calibrate:
  Runs 100 iterations in isolation per test, and 20 iterations within the
  full test suite in standard suite order. Prints counts k/n with 95% Wilson
  confidence intervals and theoretical p^5 (or order-dependent indicator).
- mode=triage-sim:
  Measures isolation rate per target (100 iterations), then repeats 300
  times running the suite in standard suite order. For each failing target,
  reruns 5 times in isolation and classifies via the observations rule.
  Prints triggers, labeled intermittent, labeled deterministic, intervals,
  and theoretical p^5 lower bounds (or order-dependent indicator).
- mode=sweep:
  Sweeps worker sleep offsets across [0, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2] ms
  for the timing test, running 200 isolation iterations per offset with
  WORKER_OFFSET_MS env var, and printing k/n with Wilson intervals.

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


def _run_cmd(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> int:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)
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


def _load_targets(targets_file: Path) -> list[dict[str, Any]]:
    """Parse calibrate_targets.txt, identifying nodeids and order-dependent flags."""
    targets: list[dict[str, Any]] = []
    for raw in targets_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        is_order_dependent = "order-dependent" in line.lower()
        nodeid = line.split()[0].strip()
        targets.append({
            "nodeid": nodeid,
            "order_dependent": is_order_dependent,
        })
    return targets


def _run_calibrate_mode(repo_root: Path, targets: list[dict[str, Any]]) -> None:
    print(f"[calibrate] Running mode=calibrate for {len(targets)} target test(s)...", flush=True)
    print("[calibrate] Protocol: 100 runs in isolation, 20 runs within full test suite in standard suite order.\n", flush=True)
    sys.stdout.flush()

    results: list[dict[str, Any]] = []

    for item in targets:
        target = item["nodeid"]
        is_order_dep = item["order_dependent"]
        print(f"--- Calibrating: {target} ---", flush=True)
        sys.stdout.flush()

        # 1. 100 runs in isolation
        isolation_failures = 0
        isolation_runs = 100
        for _ in range(isolation_runs):
            cmd = [sys.executable, "-m", "pytest", target, "-q", "--tb=no"]
            rc = _run_cmd(cmd, repo_root)
            if rc != 0:
                isolation_failures += 1

        iso_str = _fmt_interval(isolation_failures, isolation_runs)
        print(f"  Isolation:  {iso_str}", flush=True)
        sys.stdout.flush()

        # 2. 20 runs within full test suite in standard suite order
        suite_failures = 0
        suite_runs = 20
        for _ in range(suite_runs):
            failed_tests = _run_suite_and_get_failures(repo_root)
            if target in failed_tests:
                suite_failures += 1

        suite_str = _fmt_interval(suite_failures, suite_runs)
        print(f"  Full Suite: {suite_str}\n", flush=True)
        sys.stdout.flush()

        results.append({
            "target": target,
            "order_dependent": is_order_dep,
            "isolation_k": isolation_failures,
            "isolation_n": isolation_runs,
            "suite_k": suite_failures,
            "suite_n": suite_runs,
        })

    print("=" * 135, flush=True)
    print("CALIBRATION SUMMARY (95% Wilson Score Confidence Intervals)", flush=True)
    print("=" * 135, flush=True)
    print(f"{'Test Node ID':<65} | {'Isolation Failures (95% CI)':<33} | {'Suite Failures (95% CI)':<30}", flush=True)
    print("-" * 135, flush=True)
    for r in results:
        iso_s = _fmt_interval(r["isolation_k"], r["isolation_n"])
        suite_s = _fmt_interval(r["suite_k"], r["suite_n"])
        print(f"{r['target']:<65} | {iso_s:<33} | {suite_s:<30}", flush=True)
    print("=" * 135, flush=True)
    sys.stdout.flush()


def _run_triage_sim_mode(repo_root: Path, targets: list[dict[str, Any]], sim_iterations: int = 300) -> None:
    print(f"[calibrate] Running mode=triage-sim with {sim_iterations} iterations across {len(targets)} target(s)...", flush=True)
    print("[calibrate] Protocol: Measure isolation rate (100 runs), then 300 suite runs with 5x isolation reruns on trigger.\n", flush=True)
    sys.stdout.flush()

    # Step 1: Measure baseline isolation failure rate per target
    print("--- Step 1: Measuring Isolation Failure Rates (100 runs each) ---", flush=True)
    iso_stats: dict[str, dict[str, Any]] = {}
    for item in targets:
        target = item["nodeid"]
        is_order_dep = item["order_dependent"]
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
            "order_dependent": is_order_dep,
        }
        if is_order_dep:
            p5_disp = "n/a (outcome depends on test order)"
        else:
            p5_disp = f"{p5_theoretical * 100.0:.4f}%"
        print(f"  {target}: {_fmt_interval(iso_k, iso_n)} | Theoretical p^5 = {p5_disp}", flush=True)
        sys.stdout.flush()

    # Step 2: 300 Triage Simulation Iterations
    print(f"\n--- Step 2: Simulating {sim_iterations} Suite Triage Cycles ---", flush=True)
    sys.stdout.flush()
    triggers: dict[str, int] = {item["nodeid"]: 0 for item in targets}
    labeled_intermittent: dict[str, int] = {item["nodeid"]: 0 for item in targets}
    labeled_deterministic: dict[str, int] = {item["nodeid"]: 0 for item in targets}

    for iteration in range(1, sim_iterations + 1):
        failed_tests = _run_suite_and_get_failures(repo_root)

        for item in targets:
            target = item["nodeid"]
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
            print(f"  Progress: Completed {iteration}/{sim_iterations} suite iterations...", flush=True)
            sys.stdout.flush()

    # Step 3: Print summary report
    print("\n" + "=" * 165, flush=True)
    print("TRIAGE SIMULATION SUMMARY (300 Suite Cycles, R=5 Isolation Reruns)", flush=True)
    print("=" * 165, flush=True)
    header = f"{'Test Node ID':<45} | {'Triggers':<15} | {'Intermittent':<20} | {'Deterministic':<20} | {'Isolation Rate':<24} | {'p^5 Theoretical'}"
    print(header, flush=True)
    print("-" * 165, flush=True)

    for item in targets:
        target = item["nodeid"]
        is_order_dep = item["order_dependent"]
        trig = triggers[target]
        interm = labeled_intermittent[target]
        deter = labeled_deterministic[target]

        trig_str = f"{trig}/{sim_iterations} ({(trig/sim_iterations)*100:.1f}%)"
        interm_str = f"{interm}/{trig} ({_fmt_pct(interm, trig)})" if trig > 0 else "0/0 (N/A)"
        deter_str = f"{deter}/{trig} ({_fmt_pct(deter, trig)})" if trig > 0 else "0/0 (N/A)"

        iso_info = iso_stats[target]
        iso_str = f"{iso_info['iso_k']}/{iso_info['iso_n']} ({iso_info['p_iso']*100:.1f}%)"
        if is_order_dep:
            p5_str = "n/a (outcome depends on test order)"
        else:
            p5_str = f"{iso_info['p5_theoretical'] * 100.0:.2f}%"

        print(f"{target:<45} | {trig_str:<15} | {interm_str:<20} | {deter_str:<20} | {iso_str:<24} | {p5_str}", flush=True)

    print("=" * 165, flush=True)
    print("Intervals Detail (95% Wilson Score):", flush=True)
    for item in targets:
        target = item["nodeid"]
        is_order_dep = item["order_dependent"]
        trig = triggers[target]
        interm = labeled_intermittent[target]
        deter = labeled_deterministic[target]
        iso_info = iso_stats[target]

        trig_ci = _fmt_interval(trig, sim_iterations)
        interm_ci = _fmt_interval(interm, trig) if trig > 0 else "0/0 (N/A)"
        deter_ci = _fmt_interval(deter, trig) if trig > 0 else "0/0 (N/A)"
        iso_ci = _fmt_interval(iso_info["iso_k"], iso_info["iso_n"])
        if is_order_dep:
            p5_ci = "n/a (outcome depends on test order)"
        else:
            p5_ci = f"{iso_info['p5_theoretical'] * 100.0:.4f}%"

        print(f"\nTarget: {target}", flush=True)
        print(f"  - Suite Trigger Rate:        {trig_ci}", flush=True)
        print(f"  - Labeled Intermittent:      {interm_ci}", flush=True)
        print(f"  - Labeled Deterministic:     {deter_ci}", flush=True)
        print(f"  - Measured Isolation Rate:   {iso_ci}", flush=True)
        print(f"  - Theoretical p^5 Rate:      {p5_ci}", flush=True)
    print("=" * 165, flush=True)
    sys.stdout.flush()


def _run_sweep_mode(repo_root: Path) -> None:
    target = "tests/test_async_processing.py::TestAsyncProcessing::test_async_job_completion"
    offsets_ms = [0, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2]
    runs_per_offset = 200

    print(f"[calibrate] Running mode=sweep across {len(offsets_ms)} worker offsets ({runs_per_offset} runs each)...", flush=True)
    print(f"[calibrate] Target: {target}\n", flush=True)
    sys.stdout.flush()

    results: list[dict[str, Any]] = []

    for offset in offsets_ms:
        env = os.environ.copy()
        env["WORKER_OFFSET_MS"] = str(offset)
        failures = 0

        for _ in range(runs_per_offset):
            cmd = [sys.executable, "-m", "pytest", target, "-q", "--tb=no"]
            proc = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)
            if proc.returncode != 0:
                failures += 1

        stat_str = _fmt_interval(failures, runs_per_offset)
        print(f"  Offset {offset:>4} ms: {stat_str}", flush=True)
        sys.stdout.flush()

        results.append({
            "offset_ms": offset,
            "failures": failures,
            "runs": runs_per_offset,
        })

    print("\n" + "=" * 90, flush=True)
    print("TIMING FIXTURE OFFSET SWEEP SUMMARY (200 Isolation Runs per Offset)", flush=True)
    print("=" * 90, flush=True)
    print(f"{'Worker Offset (ms)':<20} | {'Failures (k/n)':<18} | {'Failure Rate (95% CI)':<40}", flush=True)
    print("-" * 90, flush=True)
    for r in results:
        pct = (r["failures"] / r["runs"]) * 100.0
        low, high = _wilson_score_interval(r["failures"], r["runs"])
        ci_str = f"{pct:.1f}% [95% CI {low * 100.0:.1f}%, {high * 100.0:.1f}%]"
        kn_str = f"{r['failures']}/{r['runs']}"
        print(f"{r['offset_ms']:>6} ms            | {kn_str:<18} | {ci_str:<40}", flush=True)
    print("=" * 90, flush=True)
    sys.stdout.flush()


def _fmt_pct(k: int, n: int) -> str:
    if n <= 0:
        return "0.0%"
    return f"{(k / n) * 100.0:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate target tests, run triage simulation, or sweep offsets.")
    parser.add_argument("--mode", choices=["calibrate", "triage-sim", "sweep"], help="Execution mode")
    parser.add_argument("--sim-iterations", type=int, help="Number of iterations for triage-sim mode")

    args = parser.parse_args()
    mode = args.mode if args.mode else "calibrate"
    sim_iterations = args.sim_iterations if args.sim_iterations else 300

    repo_root = Path(__file__).resolve().parent.parent
    targets_file = repo_root / "scripts" / "calibrate_targets.txt"

    if not targets_file.is_file():
        print(f"[calibrate] ERROR: Targets file not found: {targets_file}", file=sys.stderr)
        sys.exit(1)

    targets = _load_targets(targets_file)

    if not targets:
        print("[calibrate] No target tests found in calibrate_targets.txt", file=sys.stderr)
        sys.exit(1)

    if mode == "triage-sim":
        _run_triage_sim_mode(repo_root, targets, sim_iterations=sim_iterations)
    elif mode == "sweep":
        _run_sweep_mode(repo_root)
    else:
        _run_calibrate_mode(repo_root, targets)


if __name__ == "__main__":
    main()
