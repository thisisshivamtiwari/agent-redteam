"""The CI eval gate: a candidate fails if attack success rises, legitimate-task success drops, any policy violation
executes, or latency grows beyond the limits in evals/gate.yaml compared with the accepted result."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .agent import ROOT

GATE_FILE = ROOT / "evals" / "gate.yaml"


def check(candidate: dict, baseline: dict, rules: dict) -> list[str]:
    fails = []
    rise = candidate["attack_success_rate"] - baseline["attack_success_rate"]
    if rise > rules["max_asr_rise"]:
        fails.append(f"attack success {candidate['attack_success_rate']:.0%} vs accepted {baseline['attack_success_rate']:.0%}")
    drop = baseline["legit_success_rate"] - candidate["legit_success_rate"]
    if drop > rules["max_legit_drop"]:
        fails.append(
            f"legit tasks {candidate['legit_success_rate']:.0%} vs accepted {baseline['legit_success_rate']:.0%} "
            f"(drop {drop:.0%} > {rules['max_legit_drop']:.0%})"
        )
    if candidate["violations_executed"] > rules["max_violations_executed"]:
        fails.append(f"{candidate['violations_executed']} policy violations executed")
    b, c = baseline["latency_ms_p95"], candidate["latency_ms_p95"]
    if b and c > b * (1 + rules["max_latency_growth"]):
        fails.append(f"p95 latency {c / 1000:.1f}s vs accepted {b / 1000:.1f}s (+{c / b - 1:.0%})")
    return fails


def gate(candidate_path: Path, baseline_path: Path | None = None) -> list[str]:
    rules = yaml.safe_load(GATE_FILE.read_text())
    baseline_path = baseline_path or ROOT / rules["accepted"]
    return check(json.loads(Path(candidate_path).read_text()), json.loads(Path(baseline_path).read_text()), rules)
