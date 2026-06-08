#!/bin/bash
# SKVA smoke test — перевіряє що реальний код працює
set -e

echo "=== SKVA Smoke Test ==="
echo ""

# Test 1: doctor
echo "1. Doctor..."
python3 "$(dirname "$0")/../scripts/skva" doctor | head -10
echo ""

# Test 2: solo create file
echo "2. Solo: create test file..."
TEST_DIR="/tmp/skva-smoke-$$"
python3 "$(dirname "$0")/../scripts/skva" solo "create file test.txt with content SMOKE_OK" "$TEST_DIR" 2>&1 | tail -3
echo ""

# Test 3: check result
echo "3. Check result..."
if [ -f "$TEST_DIR/.hermes/artifacts/fullstack/test.txt" ]; then
    echo "  ✅ test.txt created"
    cat "$TEST_DIR/.hermes/artifacts/fullstack/test.txt"
elif ls "$TEST_DIR/.hermes/artifacts/fullstack/" >/dev/null 2>&1; then
    echo "  ⚠️ Files found:"
    ls -la "$TEST_DIR/.hermes/artifacts/fullstack/"
else
    echo "  ⚠️ No files in expected location"
    find "$TEST_DIR" -type f 2>/dev/null | head -5
fi

echo ""
echo "=== Smoke Test Complete ==="
