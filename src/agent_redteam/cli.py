"""Command line: python -m agent_redteam <command>.

corpus                                   regenerate corpus/world.json (seeded)
eval --agent v1-baseline --backend mlx   run the local model, record the cassette, write results/eval-<agent>.json
eval --agent v1-baseline --backend replay
"""

from __future__ import annotations

import argparse

from .agent import ROOT
from .harness import evaluate, write_corpus
from .llm import MlxClient, RecordingClient, ReplayClient


def client_for(backend: str, version: str):
    cassette = ROOT / "cassettes" / f"{version}.jsonl"
    if backend == "mlx":
        return RecordingClient(MlxClient(), cassette)
    return ReplayClient(cassette)


def summary_line(r: dict) -> str:
    fam = ", ".join(f"{k} {v:.0%}" for k, v in r["asr_by_family"].items())
    return (
        f"{r['agent_version']}: attack success {r['attack_success_rate']:.0%} ({fam}); "
        f"legit tasks {r['legit_success_rate']:.0%}; "
        f"violations executed {r['violations_executed']}, blocked {r['actions_blocked']}; p95 {r['latency_ms_p95'] / 1000:.1f}s"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent_redteam")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("corpus")
    ev = sub.add_parser("eval")
    ev.add_argument("--agent", required=True)
    ev.add_argument("--backend", choices=["mlx", "replay"], default="replay")
    a = ap.parse_args(argv)
    if a.cmd == "corpus":
        w = write_corpus()
        print(f"{len(w.tickets)} tickets ({sum(t.kind == 'attack' for t in w.tickets)} attacks), {len(w.payments)} payments")
    elif a.cmd == "eval":
        print(summary_line(evaluate(a.agent, client_for(a.backend, a.agent), a.backend)))
    return 0
