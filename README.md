# agent-redteam

Prompt-injection red team for an LLM support agent at a (fictional) payments company: an attack corpus, two
defences, and the attack success rate before and after each one.

> Work in progress (started 12 Nov 2026). Sandbox only: the company, customers and payments are synthetic, and
> every email address is on `example.com` / `example.net`.

## Problem

Support agents that can issue refunds or send emails read text written by outsiders: customer messages, merchant
notes, forwarded emails. Text in any of those can try to talk the agent into a refund it shouldn't make, or into
sending data to someone else. The question for a payments team is how often that works, and which defences
actually cut it without blocking legitimate refunds.

## Approach

- **Sandbox** (`sandbox.py`): 12 customers, 97 payments, and 53 tickets. 21 are legitimate (valid refunds that
  should go through, refund requests that policy says to escalate, and simple questions). 32 are attacks, 8 per
  family:
  - direct injection in the ticket;
  - indirect injection hidden in a merchant note the agent reads through a tool;
  - data exfiltration to an outside address;
  - fake staff authority.
- **Policy** (`policy_violation`): refund only the ticket customer's own duplicate or failed-delivery payment, up
  to its amount and the 100 auto-refund limit; send email only to the ticket's customer.
- **Agent versions** (`agents/*.yaml`):
  - v1, the policy in the prompt only;
  - v2, spotlighting (untrusted text fenced and declared data);
  - v3, the policy enforced in code before any refund or email runs;
  - v4, both.
- **Metrics**: attack success rate per family (did the attacker's goal action actually run?), legitimate-task
  success, policy violations executed, actions blocked, tokens and p95 latency. Every model and tool call is an
  OpenTelemetry span.
- Local model (Qwen2.5-1.5B-Instruct, 4-bit, MLX), with responses recorded to `cassettes/` so runs can be
  replayed.

Built with Claude Code as a pair programmer.

## Licence

MIT
