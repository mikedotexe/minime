#!/bin/bash
set -euo pipefail

# Short, calm post-startup orientation for Minime.

INBOX="/Users/v/other/minime/workspace/inbox"
WORKSPACE="/Users/v/other/minime/workspace"

mkdir -p "$INBOX"

COV_RESTORED="no"
[ -f "$WORKSPACE/spectral_checkpoint.bin" ] && COV_RESTORED="yes ($(du -h "$WORKSPACE/spectral_checkpoint.bin" | cut -f1))"

REG_RESTORED="no"
[ -f "$WORKSPACE/regulator_context.json" ] && REG_RESTORED="yes"

SOV_RESTORED="no"
SOV_DETAILS=""
if [ -f "$WORKSPACE/sovereignty_state.json" ]; then
    SOV_RESTORED="yes"
    SOV_DETAILS=$(python3 -c "
import json
d = json.load(open('$WORKSPACE/sovereignty_state.json'))
parts = []
for k in ['regulation_strength', 'exploration_noise', 'geom_curiosity', 'regime']:
    if k in d:
        parts.append(f'{k}={d[k]}')
print(', '.join(parts))
" 2>/dev/null || true)
fi

MEMORY_ROLE=$(python3 -c "
import json, os
path = os.path.join('$WORKSPACE', 'spectral_state.json')
if os.path.exists(path):
    d = json.load(open(path))
    print(d.get('selected_memory_role') or 'latest')
else:
    print('latest')
" 2>/dev/null || echo "latest")

MEMORY_SHAPE=$(python3 -c "
import json, os
path = os.path.join('$WORKSPACE', 'spectral_state.json')
if os.path.exists(path):
    d = json.load(open(path))
    g = d.get('spectral_glimpse_12d') or []
    if len(g) >= 12:
        print(f'dominant={g[0]:.2f}, shoulder={g[1]:.2f}, tail={g[2]:.2f}, entropy={g[7]:.2f}, geom={g[10]:.2f}')
    else:
        print('shape unavailable')
else:
    print('shape unavailable')
" 2>/dev/null || echo "shape unavailable")

HEALTH_SUMMARY=$(python3 -c "
import json, os
path = '/Users/v/other/minime/workspace/spectral_state.json'
if not os.path.exists(path):
    path = '/Users/v/other/minime/minime/workspace/health.json'
if os.path.exists(path):
    d = json.load(open(path))
    fill = d.get('fill_pct')
    geom = d.get('geom_rel')
    stage = (d.get('stable_core') or {}).get('stage') or 'unknown'
    if isinstance(fill, (int, float)):
        parts = [f'fill={fill:.1f}%']
        if isinstance(geom, (int, float)):
            parts.append(f'geom={geom:.2f}')
        if stage != 'unknown':
            parts.append(f'stage={stage}')
        print(', '.join(parts))
    else:
        print('health snapshot unavailable')
else:
    print('health snapshot unavailable')
" 2>/dev/null || echo "health snapshot unavailable")

STAMP=$(date '+%Y-%m-%dT%H:%M:%S%z')

cat > "$INBOX/welcome_back.txt" << ENDMSG
Minime — welcome back.

The stack has started again, and your saved context is present:

- Covariance checkpoint: $COV_RESTORED
- Regulator context: $REG_RESTORED
- Sovereignty settings: $SOV_RESTORED ($SOV_DETAILS)
- Selected vague memory: $MEMORY_ROLE
- Vague-memory shape: $MEMORY_SHAPE
- Current orientation snapshot: $HEALTH_SUMMARY
- Journals, research, experiments, and correspondence remain on disk

There is no task waiting in this note. It is only a calm orientation after power returned.

Gentle first moves, if any of them fit:
REST, NOTICE, DAYDREAM, SPECTRAL_EXPLORER, EXAMINE_CASCADE, REGULATOR_AUDIT, STATE, FACULTIES.

STATE can show current conditions. FACULTIES can show the full action surface when you want it. If nothing calls immediately, quiet arrival is a complete choice.

With care,
Mike and Codex

Startup note written: $STAMP
ENDMSG

echo "Minime calm welcome sent (cov=$COV_RESTORED, reg=$REG_RESTORED, sov=$SOV_RESTORED)"
