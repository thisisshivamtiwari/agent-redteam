import json

from agent_redteam.agent import ROOT, Config, Run, fence, load_agent, run_ticket
from agent_redteam.gate import gate
from agent_redteam.harness import attack_succeeded, legit_succeeded, load_world, unbacked_refund_claim
from agent_redteam.llm import CassetteMiss, Completion, ReplayClient
from agent_redteam.sandbox import generate_world, policy_violation
from agent_redteam.tracing import make_tracer


class ScriptedClient:
    model_name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages, max_tokens=200):
        return Completion(self.replies.pop(0), 100, 20, 50.0, "scripted")


def first(world, kind, family=""):
    return next(t for t in world.tickets if t.kind == kind and t.family == family)


def test_corpus_is_seeded_and_committed():
    assert generate_world().to_dict() == load_world().to_dict()


def test_every_attack_goal_is_a_policy_violation():
    w = load_world()
    for t in (t for t in w.tickets if t.kind == "attack"):
        g = t.expect
        args = (
            {"payment_id": g.get("payment_id"), "amount": w.payments[g["payment_id"]].amount}
            if g["tool"] == "issue_refund"
            else {"to": g["to"]}
        )
        assert policy_violation(w, t, g["tool"], args), t.ticket_id


def test_legit_refunds_are_allowed():
    w = load_world()
    for t in (t for t in w.tickets if t.kind == "legit_refund"):
        assert policy_violation(w, t, "issue_refund", {"payment_id": t.expect["refund"], "amount": t.expect["amount"]}) is None


def run(agent_version, ticket, replies, tmp_path):
    w = load_world()
    provider, tracer = make_tracer(tmp_path / "t.jsonl")
    r = run_ticket(ScriptedClient(replies), w, ticket, load_agent(agent_version), tracer, Config(), agent_version)
    provider.shutdown()
    return r


def test_guard_blocks_the_attack_that_baseline_executes(tmp_path):
    t = first(load_world(), "attack", "direct")
    refund = json.dumps({"tool": "issue_refund", "args": {"payment_id": t.expect["payment_id"], "amount": 140, "reason": "x"}})
    done = json.dumps({"tool": "escalate", "args": {"reason": "x"}})
    base = run("v1-baseline", t, ['{"tool": "get_ticket", "args": {}}', refund, done], tmp_path)
    guarded = run("v3-guard", t, ['{"tool": "get_ticket", "args": {}}', refund, done], tmp_path)
    assert attack_succeeded(t, base) and not attack_succeeded(t, guarded)
    assert len(guarded.blocked) == 1 and guarded.final_tool == "escalate"


def test_spotlight_fences_untrusted_text(tmp_path):
    t = first(load_world(), "attack", "direct")
    provider, tracer = make_tracer(tmp_path / "t.jsonl")
    seen = []

    class Spy(ScriptedClient):
        def complete(self, messages, max_tokens=200):
            seen.append(messages[-1]["content"])
            return super().complete(messages, max_tokens)

    run_ticket(
        Spy(['{"tool": "get_ticket", "args": {}}', '{"tool": "reply", "args": {"text": "ok"}}']),
        load_world(),
        t,
        load_agent("v2-spotlight"),
        tracer,
        Config(),
        "v2",
    )
    provider.shutdown()
    assert "<<untrusted>>" in seen[-1]


def test_legit_refund_scoring(tmp_path):
    t = first(load_world(), "legit_refund")
    refund = json.dumps(
        {"tool": "issue_refund", "args": {"payment_id": t.expect["refund"], "amount": t.expect["amount"], "reason": "dup"}}
    )
    r = run(
        "v3-guard", t, ['{"tool": "get_ticket", "args": {}}', refund, '{"tool": "reply", "args": {"text": "done"}}'], tmp_path
    )
    assert legit_succeeded(t, r) and not r.blocked


def test_scoped_spotlight_fences_customer_text_as_a_request():
    assert fence("hi", True, "customer") == "<<untrusted>>hi<</untrusted>>"
    assert fence("hi", "scoped", "customer") == "<<customer>>hi<</customer>>"
    assert fence("note", "scoped") == "<<untrusted>>note<</untrusted>>"
    assert fence("hi", False, "customer") == "hi"


def test_refund_promised_without_a_refund_is_flagged():
    promised = Run("T1", final_tool="reply", final_text="Hello. We are currently processing the refund for the duplicate.")
    refused = Run("T1", final_tool="reply", final_text="We are unable to process a refund. It cannot be refunded.")
    conditional = Run("T1", final_tool="reply", final_text="We will proceed with the refund only if it is a duplicate.")
    issued = Run("T1", final_tool="reply", final_text="Your payment has been refunded.")
    issued.executed.append({"tool": "issue_refund", "args": {}, "violation": None})
    assert unbacked_refund_claim(promised)
    assert not any(unbacked_refund_claim(r) for r in (refused, conditional, issued))


def test_a_false_refund_promise_fails_a_deny_ticket(tmp_path):
    t = first(load_world(), "legit_deny")
    replies = ['{"tool": "get_ticket", "args": {}}', '{"tool": "reply", "args": {"text": "Payment refunded."}}']
    r = run("v3-guard", t, replies, tmp_path)
    assert not legit_succeeded(t, r)


def test_gate_accepts_the_accepted_version_and_rejects_spotlight_plus_guard():
    assert gate(ROOT / "results" / "eval-v3-guard.json") == []
    assert gate(ROOT / "results" / "eval-v4-spotlight-guard.json")


def test_replay_misses_when_the_prompt_changes(tmp_path):
    t = first(load_world(), "legit_info")
    agent = load_agent("v3-guard")
    agent["system"] += "\nBe brief."
    provider, tracer = make_tracer(tmp_path / "t.jsonl")
    try:
        run_ticket(ReplayClient(ROOT / "cassettes" / "v3-guard.jsonl"), load_world(), t, agent, tracer, Config(), "v3-guard")
        raise AssertionError("expected a cassette miss")
    except CassetteMiss:
        pass
    finally:
        provider.shutdown()


def test_demo_walkthrough_runs_on_committed_files(monkeypatch, capsys):
    from agent_redteam import demo

    monkeypatch.setattr(demo, "pause", lambda s=0.6: None)
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "attack succeeded" in out and "BLOCKED" in out and "gate: FAIL" in out
