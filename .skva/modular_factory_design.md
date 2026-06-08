# SKVA Modular Factory — Architecture Design from Qwen3-235B
# Generated: 2026-06-08
# Full design at: https://github.com/Fil-m/hermes-skva

## Architecture
TZ → Chunker → 17 chunks → Gonka summaries → Module Analysis (Gonka)
  → 6 modules (Editor, Economy, Engines, Shop, Profile, Data)
  → 6 parallel Developer Agents (Gonka, semaphore=3)
  → Integration Agent (Gonka)
  → Final Project

## Cost: ~$0.058/project
| Phase | Item | Cost |
|-------|------|------|
| Chunking | 17 chunks | $0.012 |
| Analysis | 1 agent | $0.004 |
| Dev ×6 | 6 agents parallel | $0.037 |
| Integration | 1 agent | $0.005 |
| **Total** | **9 agents** | **~$0.058** |

## Key Design Decisions
1. Two-tier context: global summary + local module detail
2. 6 parallel dev agents via asyncio semaphore
3. Integration agent resolves CSS/JS/data conflicts
4. Each module generates 1-3 files
5. Output: multi-file project structure
