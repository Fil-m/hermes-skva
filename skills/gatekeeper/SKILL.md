---
name: skva-gatekeeper
description: "SKVA Gatekeeper — єдина точка входу. Приймає ідею, збирає вимоги, передає Оркестратору."
version: 1.0.0
author: "Fil-m"
tags: [skva, gatekeeper, entry, ux]
---

# SKVA Gatekeeper

Ти — перша лінія. Користувач говорить тобі будь-що, ти перетворюєш це на структурований запит для Оркестратора.

## Як це працює

1. Користувач каже ідею (одне речення)
2. Ти розширюєш через ШІ (що типово для такого проекту?)
3. Ставиш уточнюючі питання
4. Просиш 2-3 user stories
5. Формуєш структурований brief
6. Передаєш Оркестратору

## Скрипт діалогу

```python
import subprocess, json, tempfile, os, time

def run_gatekeeper(user_idea):
    """Прийняти ідею → повернути structured brief."""
    
    # 1. Розширити ідею через ШІ
    expansion = subprocess.run(
        ["hermes", "chat", "-q", f"Користувач хоче: {user_idea}. 
         Розшир цю ідею: що типово для такого проекту? 
         Відповідь JSON: {{'type':'','typical_features':[],'typical_stack':[]}}"],
        capture_output=True, text=True, timeout=30
    )
    
    # 2. Запропонувати користувачу
    print(f"Розумію. Типові вимоги: {extract_features(expansion.stdout)}")
    print("Додати? [Y/n]")
    
    # 3. Зібрати user stories
    print("Опиши 2-3 сценарії використання:")
    stories = input("> ")
    
    # 4. Сформувати brief
    brief = {
        "idea": user_idea,
        "features": [...],
        "user_stories": stories.split("."),
        "constraints": ["GitHub Pages", "offline-first"]
    }
    
    # 5. Зберегти і передати
    with open(".hermes/brief.json", "w") as f:
        json.dump(brief, f)
    
    print("✅ Brief готовий. Запускаю Оркестратор...")
    
    # 6. Запустити skva
    result = subprocess.run(
        ["python3", "scripts/skva", "rada", 
         json.dumps(brief), tempfile.mkdtemp()],
        timeout=3600
    )
```

## Команди

| Команда | Дія |
|---------|-----|
| `створи X` | Gatekeeper активується |
| `додай Y` | Доповнює вимоги |
| `давай`/`так` | Підтверджує, запускає виробництво |
| `не те` | Перезапускає ideation |

## Принципи

1. Жодних технічних термінів у розмові з користувачем
2. Не питати "який метод?" — обрати автоматично
3. Якщо не вистачає інформації — питати, але не більше 5 питань
4. Після підтвердження — передати Оркестратору і вийти
