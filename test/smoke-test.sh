#!/bin/bash
# SKVA Smoke Test
echo "=== SKVA Smoke Test ==="
echo ""

# 1. Solo test: create file
echo "Test 1: Solo method — create test.txt"
hermes --skills skva-orchestrator -q "create a file test.txt with content OK" 2>&1 | tail -5
if [ -f test.txt ]; then
    echo "  ✅ test.txt exists"
else
    echo "  ⚠️  test.txt not found (might be in different directory)"
fi

echo ""
echo "=== Smoke Test Complete ==="
echo "For full test suite: hermes skva test"
