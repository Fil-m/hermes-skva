#!/usr/bin/env bash
# SKVA Installer
set -e

echo "=== SKVA Installer ==="

# Перевірка Hermes
if ! command -v hermes &> /dev/null; then
    echo "→ Встановлюю Hermes..."
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
fi

echo "→ Hermes: $(hermes --version 2>&1 | head -1)"

# Встановлення
SKVA_DIR="${HOME}/.hermes-skva"
if [ ! -d "$SKVA_DIR" ]; then
    echo "→ Клоную SKVA..."
    git clone https://github.com/Fil-m/hermes-skva.git "$SKVA_DIR"
fi

# Встановлення скілів
echo "→ Встановлюю скіли..."
for skill in "$SKVA_DIR/skills/"*/; do
    hermes skills install "$skill" 2>/dev/null && echo "  ✓ $(basename $skill)" || echo "  ⚠️  $(basename $skill)"
done

# CLI доступ
echo "→ Налаштовую CLI..."
chmod +x "$SKVA_DIR/scripts/skva" "$SKVA_DIR/scripts/skva_core.py"
if ! command -v skva &> /dev/null; then
    echo "export PATH=\$PATH:$SKVA_DIR/scripts" >> ~/.bashrc
    echo "  ✓ skva додано в PATH (перезавантаж термінал або виконай: source ~/.bashrc)"
fi

echo ""
echo "=== SKVA готова! ==="
echo ""
echo "Команди:"
echo "  skva doctor               — діагностика"
echo "  skva test                 — smoke test"
echo "  skva solo \"запит\" /tmp/p  — Solo метод"
echo "  skva rada \"запит\" /tmp/p  — Rada+Fabryka"
echo ""
echo "Через Hermes:"
echo "  hermes --skills skva-orchestrator"
echo ""
echo "Документація: https://github.com/Fil-m/hermes-skva"
