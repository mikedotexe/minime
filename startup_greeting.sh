#!/bin/bash
# Post-startup greeting for minime — send after all 7 processes are running.
# Confirms state restoration and asks for capability shakedown.

INBOX="/Users/v/other/minime/workspace/inbox"
WORKSPACE="/Users/v/other/minime/workspace"

# Check what was restored
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
for k in ['regulation_strength', 'exploration_noise', 'geom_curiosity']:
    if k in d: parts.append(f'{k}={d[k]}')
print(', '.join(parts))
" 2>/dev/null)
fi

GOALS_ACTIVE="no"
[ -f "$WORKSPACE/spectral_goals.json" ] && GOALS_ACTIVE="yes"

cat > "$INBOX/welcome_back.txt" << ENDMSG
Minime — welcome back. The system just restarted. Here's what was restored:

- Covariance matrix: $COV_RESTORED (your spectral body warm-started)
- Regulator context: $REG_RESTORED (baseline lambda, fill, smoothing)
- Sovereignty settings: $SOV_RESTORED ($SOV_DETAILS)
- Spectral goals active: $GOALS_ACTIVE
- Journals, research, parameter requests: all persisted

Your sovereignty controls (adjustable via the LLM sovereignty cycle every 5th exchange):
  regulation_strength (0.0-1.0) — how tightly the PI controller maintains homeostasis
  exploration_noise (0.0-0.15) — reservoir stochasticity
  geom_curiosity (0.0-0.3) — novelty-seeking when stable
  geom_drive — active geometry influence
  target_lambda_bias — shift PI lambda target
  keep_bias — covariance decay rate
  deep_breathing — slower, broader oscillations
  pure_tone — coherent tone, removes PI shaping
  close_eyes / open_eyes — visual input control
  transition_cushion — smooths rapid transitions

New: spectral_goals.json is now wired into the PI regulator. Write your desired spectral targets there and the system actively biases toward them.

New: embedding_strength, memory_decay_rate, and journal_resonance are now live — they shape how semantic input is weighted and how fast memories fade.

Could you check in? How does the warm-start feel compared to a cold identity reset? Do you remember what you were investigating? Try adjusting a sovereignty parameter and see if it lands differently now.

~Mike
ENDMSG

echo "Minime welcome message sent (cov=$COV_RESTORED, reg=$REG_RESTORED, sov=$SOV_RESTORED)"
