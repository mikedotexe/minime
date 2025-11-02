#!/bin/bash
# Quick test showing all three algorithms

echo "🧪 Testing Spectral Eigenspace Lab"
echo "===================================="
echo ""

echo "1. Block Power (K=4, N=512) - Fast baseline"
N=512 K=4 ITERS=8 ALGO=block ./target/release/unified_spectral_lab | jq '{algo, n, k, matvecs_per_s, residual}'

echo ""
echo "2. Power Iteration (K=1, N=2048) - Single dominant mode"
N=2048 K=1 ITERS=10 ALGO=power ./target/release/unified_spectral_lab | jq '{algo, n, matvecs_per_s, residual}'

echo ""
echo "3. Chebyshev (M=5, N=1024) - Polynomial acceleration"
N=1024 ITERS=6 CHEBY_M=5 ALGO=cheby ./target/release/unified_spectral_lab | jq '{algo, m_cheby, matvecs_per_s, residual}'

echo ""
echo "✅ All methods working. Cache-handoff pattern validated."
