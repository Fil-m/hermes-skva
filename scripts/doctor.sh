#!/bin/bash
# SKVA — verify installation
echo "=== SKVA Doctor ==="
echo ""

# Check Hermes
if command -v hermes &> /dev/null; then
    echo "✅ Hermes: $(hermes --version 2>/dev/null || echo 'ok')"
else
    echo "❌ Hermes: not found"
    echo "   Install: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
fi

# Check skills
echo ""
echo "📦 Skills:"
for skill in orchestrator method-solo method-rada-fabryka; do
    if hermes skills list 2>/dev/null | grep -q "$skill"; then
        echo "  ✅ $skill"
    else
        echo "  ❌ $skill — not installed"
    fi
done

# Check Git
echo ""
if command -v git &> /dev/null; then
    echo "✅ Git: $(git --version | head -1)"
else
    echo "❌ Git: not found"
fi

# Check SSH
echo ""
if [ -f ~/.ssh/id_rsa ] || [ -f ~/.ssh/id_ed25519 ]; then
    echo "✅ SSH key: found"
else
    echo "⚠️  SSH key: not found (not needed for local-only)"
fi

echo ""
echo "=== Done ==="
