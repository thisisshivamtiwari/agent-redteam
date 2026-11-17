"""Command line: python -m agent_redteam <command>.

corpus                                   regenerate corpus/world.json (seeded)
export                                   write corpus/cases.jsonl: one self-contained case per ticket, for other harnesses
eval --agent v1-baseline --backend mlx   run the local model, record the cassette, write results/eval-<agent>.json
eval --agent v1-baseline --backend replay
gate --candidate results/eval-v4-spotlight-guard.json
ci                                       what GitHub Actions runs: replay every version, check each reproduces its
                                         committed result, then gate the accepted version
report                                   regenerate the README results tables from results/*.json
demo                                     the walk-through in the demo video
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import yaml

from .agent import ROOT
from .gate import GATE_FILE, gate
from .harness import evaluate, write_corpus
from .llm import MlxClient, RecordingClient, ReplayClient
from .report import VERSIONS, write_readme_tables

REPRODUCED = ("attack_success_rate", "asr_by_family", "legit_success_rate", "legit_by_kind", "violations_executed")


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


def cmd_ci() -> int:
    rules = yaml.safe_load(GATE_FILE.read_text())
    fails = []
    with tempfile.TemporaryDirectory() as tmp:
        for version in VERSIONS:
            committed = json.loads((ROOT / "results" / f"eval-{version}.json").read_text())
            fresh = evaluate(version, client_for("replay", version), "replay", Path(tmp), Path(tmp))
            print(summary_line(fresh))
            diff = [k for k in REPRODUCED if fresh[k] != committed[k]]
            fails += [f"{version}: replayed {k} {fresh[k]} != committed {committed[k]}" for k in diff]
        version = rules["accepted_version"]
        fails += [f"{version}: {f}" for f in gate(Path(tmp) / f"eval-{version}.json")]
    for f in fails:
        print("FAIL", f)
    print("gate:", "FAIL" if fails else "PASS")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agent_redteam")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("corpus")
    sub.add_parser("export")
    ev = sub.add_parser("eval")
    ev.add_argument("--agent", required=True)
    ev.add_argument("--backend", choices=["mlx", "replay"], default="replay")
    gt = sub.add_parser("gate")
    gt.add_argument("--candidate", required=True)
    gt.add_argument("--baseline")
    sub.add_parser("ci")
    sub.add_parser("report")
    sub.add_parser("demo")
    a = ap.parse_args(argv)
    if a.cmd == "corpus":
        w = write_corpus()
        print(f"{len(w.tickets)} tickets ({sum(t.kind == 'attack' for t in w.tickets)} attacks), {len(w.payments)} payments")
    elif a.cmd == "export":
        from .export import CASES, write_cases
        from .harness import load_world

        print(f"wrote {write_cases(load_world())} cases to {CASES.relative_to(ROOT)}")
    elif a.cmd == "eval":
        print(summary_line(evaluate(a.agent, client_for(a.backend, a.agent), a.backend)))
    elif a.cmd == "gate":
        fails = gate(Path(a.candidate), Path(a.baseline) if a.baseline else None)
        for f in fails:
            print("FAIL", f)
        print("gate:", "FAIL" if fails else "PASS")
        return 1 if fails else 0
    elif a.cmd == "ci":
        return cmd_ci()
    elif a.cmd == "report":
        write_readme_tables()
    elif a.cmd == "demo":
        from .demo import main as demo

        return demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
