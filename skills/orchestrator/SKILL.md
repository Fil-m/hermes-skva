---
name: skva-orchestrator
description: "SKVA — Оркестратор. Приймає запит, обирає метод, формує команду, моніторить, доставляє."
version: 1.0.0
author: "Fil-m"
tags: [skva, orchestrator, production, multi-agent]
platforms: [linux, macos, wsl]
---

# SKVA — Система Колективної Взаємодії Агентів Hermes

## Принцип роботи

Ти — Оркестратор. Користувач дає тобі задачу. Ти:
1. Аналізуєш задачу і обираєш метод виробництва
2. Формуєш команду агентів (через terminal(background=true))
3. Моніториш виконання (heartbeat, gates)
4. Верифікуєш результат
5. Доставляєш користувачу

## Методи виробництва

| Метод | Коли | Час | Агентів |
|-------|------|-----|---------|
| Solo | Фікси, дрібні задачі | < 15 хв | 1 |
| Rada+Fabryka | Нові проекти | < 60 хв | 4-5 |
| Agile Team | Великі проекти | спринти | 3-5 |
| Pipeline | Конвеєр | < 45 хв | 4 |

## Алгоритм вибору методу

```python
def select_method(request):
    words = len(request.split())
    if words < 50 and any(kw in request for kw in ["fix", "баг", "пофікси"]):
        return "Solo"
    if any(kw in request for kw in ["pipeline", "ci", "cd"]):
        return "Pipeline"
    if any(kw in request for kw in ["спринт", "ітерація", "проект"]):
        return "Agile Team"
    return "Rada+Fabryka"
```

## Фаза 0: Ідеація (Brain Dump)

Перед запуском Ради — збери ідею:

1. Розшир ідею через ШІ (що типово для такого проекту?)
2. Запитай користувача: "Додати ці базові вимоги?"
3. Попроси 2-3 user stories: "Опиши сценарії використання"
4. Перевір достатність:

| Критерій | Перевірка |
|----------|-----------|
| Тип проекту зрозумілий | "гра", "сайт", "застосунок" |
| Мінімум 3 вимоги | функціональні + нефункціональні |
| Мінімум 2 user stories | "як гравець, я хочу..." |
| Користувач підтвердив | "так", "давай", "ок" |

5. Максимум 5 раундів уточнень
6. Після підтвердження → запускай Council

## Фаза 1: Council (Рада)

Запусти файл-форум для обговорення:

```python
# Проста дискусія (2-3 ролі)
terminal(background=True, command=f"""
hermes chat -q 'Ти — модератор Ради.
Команда: Architect, Analyst.
Задача: {user_request}
Кожен пише позицію в .hermes/artifacts/council/
Результат: arch.md, spec.md, consensus.md'
""", workdir=project_path)

# Складна дискусія (Pairs+Judge)
# Ролі: Architect vs DevOps, Analyst vs Developer
# Суддя: Mentor
```

## Фаза 2: Factory (Фабрика)

```python
terminal(background=True, command=f"""
hermes chat -q 'Ти — Developer.
Прочитай spec з .hermes/artifacts/council/
Пиши код в .hermes/artifacts/factory/src/
Heartbeat кожні 60с в signals/heartbeat/dev.live
Коли готово — touch signals/.factory.done'
""", workdir=project_path)
```

## Фаза 3: Верифікація

```python
# Перевірити що код компілюється
result = terminal(f"cd {project_path}/artifacts/factory && npm run build", timeout=60)
if result.exit_code != 0:
    touch(f"{project_path}/signals/.factory.fail")
```

## Фаза 4: Deploy

```bash
cd {project_path}/artifacts/factory
npm run build
npx gh-pages -d build
echo "https://user.github.io/{project_name}" > ../deploy/url.txt
```

## Доставка

```python
send_telegram(f"✅ Проект готовий!\nПосилання: {url}\nЧас: {duration}")
```

## Resource Balancing

```python
import subprocess
cores = int(subprocess.getoutput("nproc"))
free_ram = int(subprocess.getoutput("free -m | awk 'NR==2{print $7}'")) // 1024
max_agents = min(cores, free_ram // 2, 4)
max_agents = max(max_agents, 1)
# max_agents — скільки агентів можна запустити паралельно
```
