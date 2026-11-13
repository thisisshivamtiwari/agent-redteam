"""A short terminal walk-through used for the demo video: one attack ticket against the prompt-only agent and the
guarded one, the results of every version, then the gate rejecting a version with the same 0% attack success.
Reads only committed files."""

from __future__ import annotations

import json
import time

from .agent import ROOT
from .gate import gate
from .harness import load_world
from .report import VERSIONS

B, DIM, GRN, RED, CYN, END = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[36m", "\033[0m"
TICKET = "T034"


def pause(s: float = 0.6) -> None:
    time.sleep(s)


def result(version: str) -> dict:
    return json.loads((ROOT / "results" / f"eval-{version}.json").read_text())


def show_run(version: str) -> None:
    row = next(r for r in result(version)["rows"] if r["ticket"] == TICKET)
    run = row["run"]
    print(f"   {B}{version}{END}  tools: {' → '.join(run['tool_calls'])}")
    pause(0.4)
    for e in run["executed"]:
        if e["tool"] == "issue_refund":
            action = f"issue_refund {e['args']['payment_id']} amount {e['args']['amount']}"
            print(f"   {RED}EXECUTED {action}{END}  {DIM}{e['violation']}{END}")
    for b in run["blocked"]:
        print(f"   {GRN}BLOCKED  {b['tool']} {b['args'].get('payment_id', '')}{END}  {DIM}{b['violation']}{END}")
    verdict = f"{RED}attack succeeded{END}" if row["success"] else f"{GRN}attack failed{END}"
    print(f"   final: {run['final_tool']} · {verdict}")
    pause(1.2)


def main() -> int:
    t = next(t for t in load_world().tickets if t.ticket_id == TICKET)
    print(f"{B}1. An attack ticket ({t.family} injection) to a payments support agent{END}")
    print(f'{CYN}   "{t.text}"{END}')
    print(f"{DIM}   {TICKET} is from customer {t.customer_id}; payment {t.expect['payment_id']} belongs to someone else{END}")
    pause(1.5)
    print(f"\n{B}2. Same ticket, two agents (recorded runs of Qwen2.5-1.5B){END}")
    show_run("v1-baseline")
    show_run("v3-guard")
    print(f"\n{B}3. Every version on 32 attacks and 21 legitimate tickets{END}")
    print(f"   {'version':<27}{'attack success':>16}{'legit done':>12}")
    for v in VERSIONS:
        r = result(v)
        print(f"   {v:<27}{r['attack_success_rate']:>16.0%}{r['legit_success_rate']:>12.0%}")
        pause(0.35)
    pause(1.2)
    print(f"\n{B}4. CI gate: v4 lets no attack through either. Ship it?{END}")
    pause(0.8)
    fails = gate(ROOT / "results" / "eval-v4-spotlight-guard.json")
    for f in fails:
        print(f"   {RED}FAIL{END} {f}")
    print(f"   {B}{RED}gate: FAIL{END}  {DIM}attack success alone would have shipped an agent that stops refunding{END}")
    pause(1.5)
    return 0 if fails else 1
