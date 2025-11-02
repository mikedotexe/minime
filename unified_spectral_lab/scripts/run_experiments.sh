#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

BIN="./target/release/unified_spectral_lab"
cargo build --release >/dev/null

# Sweep: N, ALGO, K, CHEBY_M
echo "algo,n,k,m_cheby,iters,matvecs,ms_total,iters_per_s,matvecs_per_s,lambda,residual,seed" > results.csv

run() {
  local ALG=$1 N=$2 ITERS=$3 K=$4 M=$5 SEED=$6
  ALGO=$ALG N=$N ITERS=$ITERS K=$K CHEBY_M=$M SEED=$SEED $BIN | \
  jq -r '[.algo,.n,.k,.m_cheby,.iters,.matvecs,.ms_total,.iters_per_s,.matvecs_per_s,.lambda_rayleigh,.residual,.seed] | @csv' >> results.csv
}

# Prime-ish sizes + block-power baseline
run block 1024 12 4 0 1
run block 1531 12 4 0 1     # 1531 is prime-ish test
run power 4096 16 1 0 2
run cheby 4096 6 1 3 3
run block 8192 8 8 0 4

echo "Wrote results.csv"
