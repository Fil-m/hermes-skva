#!/usr/bin/env python3
"""
SKVA Gatekeeper — єдина точка входу для користувача.
Приймає ідею, веде діалог, формує brief, запускає виробництво.
"""
import json, os, sys, tempfile, subprocess, shlex

def log(msg):
    print(f"[Gatekeeper] {msg}", flush=True)

def ask_llm(prompt, timeout=30):
    """Ask Hermes, get JSON response."""
    try:
        r = subprocess.run(
            ["hermes", "chat", "-q", prompt],
            capture_output=True, text=True, timeout=timeout
        )
        output = r.stdout
        # Extract JSON from output
        brace_start = output.find("{")
        brace_end = output.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            return json.loads(output[brace_start:brace_end+1])
        return {"raw": output[:500]}
    except Exception as e:
        return {"error": str(e)}

def collect_idea():
    """Phase 0: Gatekeeper dialog with user."""
    log("👋 SKVA. Розкажи ідею проекту одним реченням.")
    idea = input("> ").strip()
    
    if not idea:
        idea = "create a hello world app"
    
    # Expand idea via LLM
    log("🤔 Аналізую ідею...")
    expansion = ask_llm(
        f"Користувач хоче: {idea}. "
        f"Розшир цю ідею: що типово для такого проекту? "
        f"Відповідай JSON: {{'type':'','features':[],'stack':'','estimated_complexity':'low|medium|high'}}"
    )
    
    features = expansion.get("features", ["основна функціональність"])
    stack = expansion.get("stack", "не визначено")
    complexity = expansion.get("estimated_complexity", "medium")
    
    log(f"📋 Тип: {expansion.get('type', 'project')}")
    log(f"🎯 Типові вимоги: {', '.join(features[:5])}")
    log(f"🔧 Стек: {stack}")
    
    # Confirm features
    print(f"\nДодати ці типові вимоги? [Y/n] ", end="")
    ans = input().strip().lower()
    if ans not in ("n", "no"):
        log("✅ Базові вимоги додано")
    else:
        features = []
    
    # Ask for additions
    print("\nЩо ще додати? (Enter щоб пропустити): ", end="")
    extra = input().strip()
    if extra:
        additions = ask_llm(
            f"Користувач додає: {extra}. "
            f"Додай до вимог: {json.dumps(features)}. "
            f"Відповідай JSON: {{'updated_features':[]}}"
        )
        features = additions.get("updated_features", features + [extra])
        log(f"✅ Додано: {extra}")
    
    # Collect user stories
    print("\nОпиши 2-3 сценарії використання (хто що робить):")
    print("  Наприклад: як гравець я хочу бачити рахунок")
    stories = []
    for i in range(3):
        print(f"  Сценарій {i+1}: ", end="")
        s = input().strip()
        if s:
            stories.append(s)
        if i == 0 and not s:
            stories.append(f"як користувач я хочу використовувати {idea}")
            break
    
    # Build structured brief
    brief = {
        "idea": idea,
        "type": expansion.get("type", "project"),
        "features": features,
        "user_stories": stories,
        "estimated_complexity": complexity,
        "stack_hint": stack,
        "constraints": ["GitHub Pages compatible", "offline-first", "no backend"],
    }
    
    # Show summary
    print("\n" + "=" * 50)
    log("📄 BRIEF проекту:")
    print(f"  Ідея: {brief['idea']}")
    print(f"  Тип: {brief['type']}")
    print(f"  Вимоги: {len(brief['features'])} шт")
    print(f"  Сценарії: {len(brief['user_stories'])} шт")
    print(f"  Складність: {brief['estimated_complexity']}")
    print("=" * 50)
    
    print("\nЗапустити виробництво? [Y/n] ", end="")
    confirm = input().strip().lower()
    if confirm in ("n", "no"):
        log("❌ Скасовано")
        return None
    
    return brief

def start_production(brief):
    """Pass brief to Orchestrator and start production."""
    log("🚀 Запускаю виробництво...")
    
    # Save brief
    brief_path = os.path.expanduser("~/.hermes-skva/current-brief.json")
    os.makedirs(os.path.dirname(brief_path), exist_ok=True)
    with open(brief_path, "w") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)
    
    # Determine method based on complexity
    method = "solo" if brief.get("estimated_complexity") == "low" else "rada"
    
    # Create project directory
    project_dir = tempfile.mkdtemp(prefix=f"skva-{brief['type']}-")
    
    # Run production
    cmd = ["python3", os.path.join(os.path.dirname(__file__), "skva"), method, json.dumps(brief), project_dir]
    log(f"  Метод: {method}")
    log(f"  Директорія: {project_dir}")
    log(f"  Команда: {' '.join(cmd)}")
    
    try:
        r = subprocess.run(cmd, timeout=3600, capture_output=True, text=True)
        log(r.stdout[-1000:] if len(r.stdout) > 1000 else r.stdout)
        if r.returncode == 0:
            log("✅ Проект готовий!")
        else:
            log(f"❌ Помилка: {r.stderr[-500:]}")
    except subprocess.TimeoutExpired:
        log("⏰ Timeout — проект перевищив ліміт часу")
    except Exception as e:
        log(f"❌ Виняток: {e}")

def main():
    print("\n╔══════════════════════════════════════╗")
    print("║   SKVA — Gatekeeper                  ║")
    print("║   Просто опиши ідею, я зроблю решту  ║")
    print("╚══════════════════════════════════════╝\n")
    
    brief = collect_idea()
    if brief:
        start_production(brief)
    else:
        log("👋 Бувай! Заходь ще.")

if __name__ == "__main__":
    main()
