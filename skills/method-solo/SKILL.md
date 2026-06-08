---
name: method-solo
description: "Solo method — one agent, quick fixes"
version: 1.0.0
tags: [skva, method, solo]
---

# Solo — Lean method

Use for: bug fixes, single-file changes, small tasks (<50 words)

Parameters:
- Agents: 1 (Fullstack)
- Model: DeepSeek Flash (cheapest)
- Timeout: 15 min
- Phases: Execute → Verify → Deliver

Process:
1. Orchestrator spawns one agent via terminal(background)
2. Agent writes code in .hermes/artifacts/fullstack/
3. Agent heartbeats every 60s
4. Agent signals .solo.done when complete
5. Orchestrator verifies: file exists, compiles if code
6. Deliver to user

Lean docs: no spec, no arch, no logs — just code.
