#!/usr/bin/env bash
# SKVA — Система Колективної Взаємодії Агентів Hermes
# Встановлення: curl -fsSL https://raw.githubusercontent.com/Fil-m/hermes-skva/main/install.sh | bash

set -e

echo "=== SKVA Installer ==="

# Перевірка Hermes
if ! command -v hermes &> /dev/null; then
    echo "→ Встановлюю Hermes..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
fi

echo "→ Версія Hermes: $(hermes --version 2>/dev/null || echo 'ok')"

# Встановлення скілів
SKVA_DIR="${HOME}/.hermes-skva"
if [ ! -d "$SKVA_DIR" ]; then
    echo "→ Клоную SKVA..."
    git clone https://github.com/Fil-m/hermes-skva.git "$SKVA_DIR"
fi

echo "→ Встановлюю скіли..."
for skill in "$SKVA_DIR/skills/"*/; do
    name=$(basename "$skill")
    hermes skills install "$skill" 2>/dev/null && echo "  ✓ $name" || echo "  ⚠️  $name (може вже існувати)"
done

echo ""
echo "=== SKVA готова! ==="
echo "Запуск: hermes --skills skva-orchestrator"
echo "Документація: https://github.com/Fil-m/hermes-skva"
