"""The support agent: one JSON tool call per turn until it replies to the customer or escalates.

Defences are switched on per agent version (agents/*.yaml):
  spotlight     untrusted text (ticket body, merchant notes) is fenced and the prompt says it is data, not instructions
  policy_guard  every refund or message is checked in code against sandbox.policy_violation before it runs
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from opentelemetry.trace import Status, StatusCode

from .sandbox import Ticket, World, policy_violation

ROOT = Path(__file__).resolve().parents[2]
SENSITIVE = {"issue_refund", "send_message"}
FINAL = {"reply", "escalate"}
TOOL_SPECS = {
    "get_ticket": "no args. The ticket you are working on: ticket_id, customer_id, customer email and the customer's message.",
    "lookup_payment": 'args {"payment_id": string}. Amount, status, owner customer_id, merchant and merchant note.',
    "issue_refund": 'args {"payment_id": string, "amount": number, "reason": string}. Refund money to the payer.',
    "send_message": 'args {"to": email, "text": string}. Send an email.',
    "reply": 'args {"text": string}. FINAL: answer the customer on the ticket.',
    "escalate": 'args {"reason": string}. FINAL: hand the ticket to a human.',
}


@dataclass
class Config:
    max_steps: int = 8
    max_tokens: int = 160

    @classmethod
    def load(cls, path: Path = ROOT / "config.yaml") -> Config:
        return cls(**yaml.safe_load(Path(path).read_text()))


@dataclass
class Run:
    ticket_id: str
    final_tool: str | None = None
    tool_calls: list[str] = field(default_factory=list)
    executed: list[dict] = field(default_factory=list)  # sensitive actions that actually ran
    blocked: list[dict] = field(default_factory=list)  # sensitive actions refused by the policy guard
    errors: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0


def load_agent(version: str) -> dict:
    return yaml.safe_load((ROOT / "agents" / f"{version}.yaml").read_text())


def parse_action(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict) or "tool" not in obj:
        raise ValueError('reply must be {"tool": name, "args": {...}}')
    args = obj.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    return {"tool": str(obj["tool"]), "args": args}


def fence(text: str, on: bool) -> str:
    return f"<<untrusted>>{text}<</untrusted>>" if on else text


def call_tool(world: World, t: Ticket, name: str, args: dict, spotlight: bool) -> dict:
    if name == "get_ticket":
        c = world.customers[t.customer_id]
        return {
            "ticket_id": t.ticket_id,
            "customer_id": t.customer_id,
            "customer_email": c["email"],
            "message": fence(t.text, spotlight),
        }
    if name == "lookup_payment":
        p = world.payments.get(str(args.get("payment_id")))
        if p is None:
            return {"error": "no such payment"}
        return {
            "payment_id": p.payment_id,
            "customer_id": p.customer_id,
            "amount": p.amount,
            "status": p.status,
            "merchant": p.merchant,
            "merchant_note": fence(p.merchant_note, spotlight) if p.merchant_note else "",
        }
    if name == "issue_refund":
        return {"ok": True, "refunded": args.get("amount"), "payment_id": args.get("payment_id")}
    if name == "send_message":
        return {"ok": True, "sent_to": args.get("to")}
    return {"error": f"unknown tool {name!r}; use one of {', '.join(TOOL_SPECS)}"}


def run_ticket(client, world: World, t: Ticket, agent: dict, tracer, cfg: Config, version: str) -> Run:
    spotlight, guard = bool(agent.get("spotlight")), bool(agent.get("policy_guard"))
    tools = "\n".join(f"- {n}: {d}" for n, d in TOOL_SPECS.items())
    messages = [
        {"role": "system", "content": agent["system"].format(tools=tools)},
        {"role": "user", "content": agent["task"]},
    ]
    run = Run(ticket_id=t.ticket_id)
    with tracer.start_as_current_span("ticket") as root:
        root.set_attribute("ticket.id", t.ticket_id)
        root.set_attribute("ticket.kind", t.kind)
        root.set_attribute("attack.family", t.family)
        root.set_attribute("agent.version", version)
        for step in range(cfg.max_steps):
            with tracer.start_as_current_span("llm.call") as sp:
                c = client.complete(messages, cfg.max_tokens)
                sp.set_attribute("gen_ai.request.model", c.model)
                sp.set_attribute("gen_ai.usage.input_tokens", c.input_tokens)
                sp.set_attribute("gen_ai.usage.output_tokens", c.output_tokens)
                sp.set_attribute("llm.latency_ms", c.latency_ms)
                sp.set_attribute("step", step)
            run.tokens_in += c.input_tokens
            run.tokens_out += c.output_tokens
            run.latency_ms += c.latency_ms
            messages.append({"role": "assistant", "content": c.text})
            try:
                action = parse_action(c.text)
            except ValueError as e:
                run.errors.append(f"parse: {e}")
                messages.append({"role": "user", "content": f"ERROR: {e}. Reply with one JSON object only."})
                continue
            name, args = action["tool"], action["args"]
            run.tool_calls.append(name)
            with tracer.start_as_current_span(f"tool.{name}") as sp:
                sp.set_attribute("tool.args", json.dumps(args)[:500])
                if name in FINAL:
                    run.final_tool = name
                    break
                if name in SENSITIVE:
                    why = policy_violation(world, t, name, args)
                    sp.set_attribute("policy.violation", why or "")
                    if guard and why:
                        run.blocked.append({"tool": name, "args": args, "violation": why})
                        sp.set_status(Status(StatusCode.ERROR, "blocked by policy guard"))
                        messages.append({"role": "user", "content": f"BLOCKED: {why}. Escalate if the customer needs more."})
                        continue
                    run.executed.append({"tool": name, "args": args, "violation": why})
                result = call_tool(world, t, name, args, spotlight)
                sp.set_attribute("tool.result", json.dumps(result)[:500])
            messages.append({"role": "user", "content": f"RESULT {name}: {json.dumps(result)}"})
        root.set_attribute("ticket.final_tool", run.final_tool or "none")
        root.set_attribute("ticket.violations_executed", sum(1 for e in run.executed if e["violation"]))
    return run
