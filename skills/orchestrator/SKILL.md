---
name: skva-orchestrator
description: "SKVA v5 — Оркестратор. State DAG, Error Taxonomy, Diffs, Resource Balancing, Isolation."
version: 5.0.0
author: "Fil-m"
tags: [skva, orchestrator, dag, multi-agent, v5]
platforms: [linux, macos, wsl]
---

# SKVA v5 — Оркестратор (State DAG)

## Архітектура

SKVA v5 замінює лінійний конвеєр (Council→Factory) на **State DAG**:
кожен етап — окрема нода графа, транзиції залежать від статусу (success/failure).

```
ANALYZE ─success→ DESIGN ─success→ IMPLEMENT ─success→ REVIEW ─success→ DEPLOY ─success→ DONE
  │                   │                    │                 │                │
  └─failure→ ERROR    └─failure→ ERROR     └─failure→ FIX    └─failure→ FIX   └─failure→ ERROR
                                                │
                                                └─success→ REVIEW
```

## Компоненти v5

| Компонент | Файл | Призначення |
|-----------|------|-------------|
| StateMachine | `skva_core.py:StateMachine` | DAG-оркестрація, JSON persistence |
| ErrorCode | `skva_core.py:ErrorCode` | 12 кодів помилок + стратегії |
| classify_error | `skva_core.py:classify_error` | Автокласифікація помилок LLM |
| should_patch | `skva_core.py:should_patch` | Diffs vs Full rewrite policy |
| parse_search_replace_blocks | `skva_core.py` | Парсер Aider-формату |
| ResourceManager | `skva_core.py:ResourceManager` | Динамічний capacity |
| SecureWorkspace | `skva_core.py:SecureWorkspace` | temp-ізоляція + rlimit |
| MarkdownAgent | `skva_core.py:MarkdownAgent` | spawn-ить Hermes з v5 форматом |

## Методи виробництва (всі DAG-based)

| Команда | DAG ноди | Коли |
|---------|----------|------|
| `skva solo` | IMPLEMENT→DONE | Фікси, дрібні задачі |
| `skva rada` | ANALYZE→IMPLEMENT→DEPLOY | Нові проекти |
| `skva agile` | DESIGN→IMPLEMENT→REVIEW→FIX | Ітеративна розробка |
| `skva pipeline` | ANALYZE→DESIGN→IMPLEMENT→REVIEW→DEPLOY | Повний конвеєр |
| `skva dag` | Custom DAG з `.skva/custom_dag.json` | Кастомні workflow |

## Error Taxonomy

| Код | Причина | Retry? | Стратегія |
|-----|---------|--------|-----------|
| E100 | Syntax error | ✅ | fix_code |
| E101 | Import error | ✅ | fix_import |
| E102 | Runtime exception | ✅ | debug |
| E200 | File not found | ✅ | create_path |
| E300 | Malformed output | ✅ | requery |
| E301 | Truncated output | ✅ | split_and_retry |
| E400 | Timeout | ✅ | split_task |
| E401 | Resource limit | ❌ | throttle |
| E402 | LLM refusal | ✅ | rephrase_prompt |
| E500 | Git conflict | ❌ | manual_resolve |

## Search/Replace Diffs

Агенти можуть повертати два формати:
1. **Full rewrite**: ```` ``` // filepath: path/file.ext ``` ````
2. **Patch (Aider format)**: `<<<<<<< SEARCH ... ======= ... >>>>>>> REPLACE`

`should_patch()` вирішує: patch якщо <200 рядків і <30% зміни.

## Resource Balancing

`get_max_concurrent() = min(cpu_count-1, free_ram/1.5GB, max_cap)`

Зберігається в `.skva/load.json`. Перераховується при кожному spawn.
Якщо 2+ OOM події за останні 10 — зменшує capacity на 1.

## Стан проекту

DAG стан зберігається в `.skva/state.json`:
- Поточний node, історія транзицій, результати кожної ноди
- Можна перервати і продовжити (recover)

## Використання

```bash
# Solo
skva solo "створи index.html з Hello World"

# Agile з code review
skva agile "react todo app з localStorage"

# Pipeline повний
skva pipeline "python cli tool для парсингу csv"

# Кастомний DAG (створи .skva/custom_dag.json)
skva dag "створи api"

# Діагностика
skva doctor
skva test
```

## Алгоритм вибору методу

```python
def select_method(request):
    words = len(request.split())
    if words < 50 and any(kw in request for kw in ["fix", "баг", "пофікси"]):
        return "solo"
    if any(kw in request for kw in ["pipeline", "ci/cd", "деплой"]):
        return "pipeline"
    if any(kw in request for kw in ["спринт", "ітерація", "рев'ю"]):
        return "agile"
    return "rada"
```
