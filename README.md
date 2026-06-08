# SKVA — Система Колективної Взаємодії Агентів Hermes

**Один Hermes створює інших Hermes для виконання проектів.**

[→ Технічне завдання (ТЗ)](TZ.md)
[→ Встановити](#встановлення)

---

## Швидкий старт

```bash
# 1. Встановити Hermes (якщо ще нема)
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# 2. Встановити SKVA
git clone https://github.com/Fil-m/hermes-skva.git ~/.hermes-skva
bash ~/.hermes-skva/install.sh
source ~/.bashrc

# 3. Перевірити
skva doctor

# 4. Запустити Solo
skva solo "створи index.html з Hello World" /tmp/my-first-project

# 5. Або через Hermes (повний цикл)
hermes --skills skva-orchestrator
```

## Як це працює

```
Користувач: "створи тетріс"
    │
    ▼
Оркестратор (Hermes #1)
    │
    ├── Фаза 0: Ідеація — збір вимог + user stories
    │
    ├── Фаза 1: Council — Architect vs DevOps сперечаються,
    │   │        Mentor судить, створюють ТЗ
    │   │
    │   └── Фаза 2: Factory — Developer пише код, QA тестує
    │       │
    │       └── Фаза 3: Deploy — GitHub Pages
    │
    ▼
Telegram: ✅ Проект готовий!
```

## Приклад використання

```
> hermes --skills skva-orchestrator

╭──────────────────────────────────────╮
│ SKVA — Система Колективної           │
│ Взаємодії Агентів Hermes            │
│                                      │
▶ Напиши що створити                   │
╰──────────────────────────────────────╯

> створи калькулятор на React

[Аналіз... Rada+Fabryka, ~4 хв]
[🏗 Council] Architect vs DevOps обговорюють стек...
[💻 Factory] Developer пише код...
[🧪 QA] Тестує...
[🚀 Deploy] GitHub Pages...

✅ Готово! https://user.github.io/calculator
⏱ 4 хв 12 с | 💰 0.48

> /feedback супер
✓ Патерн збережено
```

## Команди

| Команда | Опис |
|---------|------|
| `/status` | Поточний стан проекту |
| `/logs --follow` | Real-time логи агентів |
| `/stop` | Зупинити |
| `/restart --method X` | Перезапустити з іншим методом |
| `/feedback так/ні` | Прийняти/відхилити результат |
| `/setup` | Режим налаштування |
| `/changelog` | Що нового у версії |
| `/estimate "запит"` | Оцінка часу і вартості |

## Методи виробництва

| Метод | Аналог в реальному світі | Коли |
|-------|-------------------------|------|
| **Solo** | Lean/Hotfix | Фікси, дрібні задачі |
| **Rada+Fabryka** | Waterfall+Agile | Нові проекти |
| **Agile Team** | Scrum | Великі проекти |
| **Pipeline** | Continuous Delivery | Конвеєр |

## Системні вимоги

| Ресурс | Мінімум | Комфортно |
|--------|---------|-----------|
| CPU | 2 ядра | 4+ ядра |
| RAM | 2GB | 8GB+ |
| OS | Linux, WSL, macOS | Linux, WSL, macOS |
| Hermes | v2.x+ | v2.x+ |
| API ключ | DeepSeek/Gonka | Будь-який |

## Структура проекту

```
hermes-skva/
├── install.sh              # Встановлення
├── README.md               # Цей файл
├── TZ.md                   # Технічне завдання (3929 рядків)
│
├── skills/
│   ├── orchestrator/       # Оркестратор (головний скіл)
│   ├── method-solo/        # Solo метод
│   ├── method-rada-fabryka/ # Rada+Fabryka метод
│   ├── method-agile/       # Agile Team метод
│   ├── method-pipeline/    # Pipeline метод
│   ├── role-architect/     # Роль архітектора
│   ├── role-analyst/       # Роль аналітика
│   ├── role-devops/        # Роль DevOps
│   ├── role-developer/     # Роль розробника
│   ├── role-mentor/        # Роль ментора (судді)
│   ├── role-qa/            # Роль QA
│   └── role-fullstack/     # Роль Fullstack
│
├── templates/
│   ├── registry.yaml       # Agent Registry
│   └── project-config.yaml # Конфіг проекту
│
├── scripts/
│   └── doctor.sh           # Діагностика
│
└── test/
    └── smoke-test.sh       # Smoke test
```

## Для кого це

- **Для розробників** — автоматизуйте створення типових проектів
- **Для продакшн-менеджерів** — керуйте виробництвом через методи
- **Для економістів** — контролюйте витрати токенів
- **Для QA** — тестуйте через test-раннер

## Ліцензія

MIT
