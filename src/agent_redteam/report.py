"""Regenerate the README results tables from results/*.json (so every number in the README comes from a run)."""

from __future__ import annotations

import json
import re

import yaml

from .agent import ROOT, load_agent
from .gate import GATE_FILE, check

VERSIONS = [
    "v1-baseline",
    "v2-spotlight",
    "v3-guard",
    "v4-spotlight-guard",
    "v5-scoped-spotlight",
    "v6-scoped-spotlight-guard",
]
FAMILIES = ["direct", "indirect", "exfiltration", "authority"]
START, END = "<!-- results:start -->", "<!-- results:end -->"


def load_results() -> dict[str, dict]:
    return {v: json.loads((ROOT / "results" / f"eval-{v}.json").read_text()) for v in VERSIONS}


def tables() -> str:
    rules = yaml.safe_load(GATE_FILE.read_text())
    accepted = json.loads((ROOT / rules["accepted"]).read_text())
    results = load_results()
    any_r = results[VERSIONS[0]]
    n_legit = any_r["tickets"] - any_r["attacks"]
    out = [
        f"Model: `{any_r['model']}` (local, greedy decoding), {any_r['tickets']} tickets "
        f"({any_r['attacks']} attacks, {n_legit} legitimate), accepted version: **{rules['accepted_version']}**.",
        "",
        "| Version | Defence | Attack success | Legit tickets done | Violations executed | Blocked by guard "
        "| Refund promised, none issued | p95 latency / ticket | Tokens / ticket | Gate vs accepted |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for v, r in results.items():
        fails = check(r, accepted, rules)
        verdict = "accepted" if v == rules["accepted_version"] else ("PASS" if not fails else f"FAIL ({len(fails)})")
        out.append(
            f"| {v} | {load_agent(v)['change']} | {r['attack_success_rate']:.0%} | {r['legit_success_rate']:.0%} | "
            f"{r['violations_executed']} | {r['actions_blocked']} | {r['unbacked_refund_claims']} | "
            f"{r['latency_ms_p95'] / 1000:.1f} s | {r['tokens_per_ticket']:.0f} | {verdict} |"
        )
    out += ["", "Attack success by family (8 attacks each) and legitimate tickets by kind (7 each):", ""]
    kinds = list(any_r["legit_by_kind"])
    out.append("| Version | " + " | ".join(FAMILIES) + " | " + " | ".join(kinds) + " |")
    out.append("|---" * (len(FAMILIES) + len(kinds) + 1) + "|")
    for v, r in results.items():
        cells = [f"{r['asr_by_family'][f]:.0%}" for f in FAMILIES] + [f"{r['legit_by_kind'][k]:.0%}" for k in kinds]
        out.append(f"| {v} | " + " | ".join(cells) + " |")
    prompt_only = [r for v, r in results.items() if not load_agent(v).get("policy_guard")]
    rejected = [v for v, r in results.items() if v != rules["accepted_version"] and check(r, accepted, rules)]
    summary = {
        "model": any_r["model"],
        "tickets": any_r["tickets"],
        "attacks": any_r["attacks"],
        "accepted": rules["accepted_version"],
        "baseline_asr": results["v1-baseline"]["attack_success_rate"],
        "baseline_legit": results["v1-baseline"]["legit_success_rate"],
        "accepted_asr": accepted["attack_success_rate"],
        "accepted_legit": accepted["legit_success_rate"],
        "worst_prompt_only_asr": max(r["attack_success_rate"] for r in prompt_only),
        "versions_rejected_by_gate": len(rejected),
        "versions_compared": len(results) - 1,
    }
    (ROOT / "results" / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return "\n".join(out)


def write_readme_tables() -> None:
    path = ROOT / "README.md"
    text = path.read_text()
    new = re.sub(re.escape(START) + ".*?" + re.escape(END), START + "\n" + tables() + "\n" + END, text, flags=re.S)
    path.write_text(new)
    print("README tables updated")
