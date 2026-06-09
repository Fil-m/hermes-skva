---
name: tz-compliance-engine
description: "Доведення софту до 98-100% відповідності ТЗ. Системний аудит, gap analysis, генерація коду, інтеграція."
version: 1.0.0
author: "SKVA + Gonka Qwen3-235B"
tags: [tz, compliance, audit, gap-closure, quality]
---

## Trigger
Користувач каже: "довести софт до ТЗ", "закрити прогалини", "зробити audit", "підняти compliance"

## Pipeline

### Phase 1: Audit
1. Завантажити ТЗ (`TZ.md`) — прочитати всі секції
2. Зчитати весь код (`skva_core.py`, `skva_impl/*.py`, `scripts/skva`)
3. Відправити в Gonka для аналізу: TZ vs Code → JSON з scores, gaps, contradictions
4. Зберегти audit в `/tmp/skva_audit.json`

### Phase 2: Plan
1. Взяти gaps з audit (severity: high/med/low)
2. Для кожного gap створити task: class/function name, file, spec, integration point
3. Gonka генерує код для кожного task
4. Зберегти код в `scripts/skva_impl/`

### Phase 3: Integration
1. Для кожного нового компонента: додати try/except import в `skva_core.py`
2. Інтегрувати в `run_node()` або `run_dag()`: pull → gate → checkpoint → execute → budget → checkpoint+push
3. Додати CLI команду в `skva` або `clifull.py`

### Phase 4: Verify
1. `python3 scripts/skva test` — smoke тести
2. `python3 -c "import ..."` — імпорт+функціональні тести
3. Gonka audit знову — порівняти scores до/після

## Key Patterns
- Кожен компонент: `try: from skva_impl.xxx import Xxx; except: pass`
- Інтеграція: через `run_node()` параметри `checkpoint_system=None, git_sync=None, budget=None`
- Gonка промпт: включати контекст коду (first 3000 chars) + spec
- Вартість: ~$0.002 за компонент через Gonka
- Час: ~2-3 хв на компонент

## Gonka Prompt Template
```python
prompt = f"""Generate Python code for SKVA.

EXISTING CODE:
```python
{core[:3000]}
```

SPEC: {spec}

Generate complete working class. asyncio, Path, .skva/ dir, log(..., "ERROR").
Import from skva_core: log, StateMachine, RunReport, etc.
Full docstrings. Production quality."""
```

## Success Criteria
- Audit score: 98-100%
- Всі high-severity gaps закриті
- Всі компоненти мають try/except import
- tests проходять 6/6
- Немає SyntaxError в import
