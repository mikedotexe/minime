#!/bin/bash

echo "========================================================================"
echo "CLEAN MODE TEST (default - no debug output)"
echo "========================================================================"
echo ""
echo "This should show only clean conversation, no debug spam."
echo ""
echo "Running: echo 'hello' | python3 minime.py"
echo ""

echo "hello" | timeout 10 python3 minime.py 2>&1 | head -20

echo ""
echo "========================================================================"
echo "DEBUG MODE TEST (--debug flag)"
echo "========================================================================"
echo ""
echo "This should show detailed processing information."
echo ""
echo "Running: echo 'hello' | python3 minime.py --debug"
echo ""

echo "hello" | timeout 10 python3 minime.py --debug 2>&1 | head -40

echo ""
echo "========================================================================"
echo "TEST COMPLETE"
echo "========================================================================"
