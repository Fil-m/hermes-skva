#!/bin/bash
# SKVA v5 Smoke Test
set -e

echo "=== SKVA v5 Smoke Test ==="
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 1. Imports
echo -n "1. Python imports... "
python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR/scripts'); from skva_core import StateMachine, Node, NodeType, ErrorCode, classify_error, ResourceManager, SecureWorkspace, should_patch, parse_search_replace_blocks, apply_search_replace, solo, rada_fabryka, agile, pipeline"
echo "✅"

# 2. StateMachine
echo -n "2. StateMachine DAG... "
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR/scripts')
from skva_core import StateMachine, Node, NodeType
sm = StateMachine('/tmp/skva-smoke')
sm.reset()
sm.add_node(Node('a', NodeType.ANALYZE, 'analyst'))
sm.add_node(Node('b', NodeType.DONE, ''))
sm.add_edge('a', 'b', 'success')
assert sm.transition('a', 'success') == 'b'
sm2 = StateMachine('/tmp/skva-smoke')
assert 'a' in sm2.nodes
print('✅')" 2>&1 | tail -1

# 3. Error taxonomy
echo -n "3. Error taxonomy... "
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR/scripts')
from skva_core import classify_error, ErrorCode
assert classify_error('SyntaxError: x') == ErrorCode.SYNTAX
assert classify_error('ModuleNotFoundError: x') == ErrorCode.IMPORT
assert classify_error('timeout') == ErrorCode.TIMEOUT
print('✅')" 2>&1 | tail -1

# 4. Diffs
echo -n "4. Diffs policy... "
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR/scripts')
from skva_core import should_patch, parse_search_replace_blocks, apply_search_replace
assert should_patch('', 'new') == False
assert parse_search_replace_blocks('<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE') == [('a','b')]
assert apply_search_replace('x a y', [('a','b')]) == 'x b y'
print('✅')" 2>&1 | tail -1

# 5. Resource balancer
echo -n "5. Resource balancer... "
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR/scripts')
from skva_core import ResourceManager
rm = ResourceManager('/tmp/skva-smoke')
assert rm.get_max_concurrent() >= 1
print('✅')" 2>&1 | tail -1

# 6. Isolation
echo -n "6. Secure workspace... "
python3 -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR/scripts')
from skva_core import SecureWorkspace
with SecureWorkspace() as ws:
    assert ws.work_dir.exists()
print('✅')" 2>&1 | tail -1

# 7. Hermes (optional)
echo -n "7. Hermes CLI... "
if command -v hermes &> /dev/null; then
    echo "$(hermes --version 2>&1 | head -1)"
else
    echo "⚠️ not found"
fi

echo ""
echo "=== Smoke test passed ✅ ==="
