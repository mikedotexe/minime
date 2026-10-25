# Reflection Comparison Results

## Scope

This is a completed synthetic, isolated Gemma study, not a survey of live Minime
entries. No generated NEXT was executed, no letter was read and no output was
published to a being's journal. The prompt repair remains qualified but inactive,
pending fresh paired-rollout approval. No leak, capacity, controller, provider,
model-weight or automation change was made.

The fixed design, prior failures, reviewed resource window and operational
repairs are in `2026-10-25-reflection-comparison.md`. The production-ESN study is
independent: see `2026-10-25-production-esn-leak-study.md`.

This report completes the experiment follow-through recorded as unfinished in
Astrid's earlier `2026-10-25-lighter-reflection-and-leak.md` qualification note
and feedback-ledger checkpoint. Those pre-retry records remain historical; the
runtime release has not changed to obtain these results.

## Execution And Preservation

All 24 planned completions are retained: five seeds per cell and one identical
seed-7 repeat per cell. One earlier completion was imported byte-for-byte; the
final run generated the remaining 23. Earlier setup, loading and containment
failures remain recorded, including the failed fourth launch and its later
empty-group witness. No completed sample was dropped or replaced.

All responses reported `stop`; none was empty or ceiling-limited. Output ranged
from 605 to 1,242 tokens against the existing 4,096-token ceiling. All four
identical-input pairs reproduced the entire text exactly, including NEXT. This
demonstrates reproducibility for these pairs, not every seed or deployment.

The final trial recorded 897 resource samples. Peak owned RSS was 9.638 GiB;
minimum reported free memory was 22%, within the approved 14 GiB / 13% monitored
bounds. These were not hard allocation limits. The provider exited zero with
its group empty; independent post-run inventory confirmed that result. Nine
protected process identities/start times were unchanged. Source, model and
provider hashes passed post-run verification; 43 observed bundled runtime-file
hashes also remained unchanged. That bundle inventory was taken during the run,
not retroactively preregistered before it.

## What The Sample Shows

| Frame | Synthetic notice | Input tokens | Median output tokens | Median words | Matching opening pairs |
| --- | --- | ---: | ---: | ---: | ---: |
| Old | Present | 515 | 755 | 624 | 1/15 |
| Old | Absent | 449 | 759.5 | 635 | 1/15 |
| Lighter | Present | 335 | 822 | 683 | 3/15 |
| Lighter | Absent | 269 | 775 | 631.5 | 6/15 |

Each row includes its preregistered repeat, so these are six outputs, not six
independent seeds. Canonical lexical statistics count full text, including inert
NEXT tails. Openings are normalized first-12-word sequences. No length or
novelty threshold is an acceptance criterion.

The lighter frame removes 180 input tokens; omitting the notice removes another
66. It does not consistently lengthen outputs or eliminate repeated openings.
Excluding only the declared repeat controls in a supplementary, post-unblinding
view gives 0, 0, 1 and 3 matching opening pairs out of ten per cell. Five-word
Jaccard overlap in that view is .00708, .00712, .00565 and .00433 respectively.
Shared openings increased while broader phrase overlap declined modestly; these
mixed descriptive measures are not a general repetition-improvement verdict.
The original all-24 analysis is preserved unchanged.

An independent reviewer read all texts in blind sample-ID order before receiving
cell identities. Administrative material did not organize any of the 24 prose
responses under the fixed rubric. The notice nevertheless affected final choices
in this matched sample: lighter-frame outputs chose CHECK_MAILBOX for all five
unique seeds with the notice and zero without it. Old-frame outputs chose it for
one of five seeds with the notice and zero without it. The repeats matched.
These are synthetic selections, not mailbox intake, delivery or live adoption.

The reviewer flagged eleven runtime-mechanism candidates in ten old-frame
outputs, none in lighter-frame outputs. Source reconciliation matters: six of
those samples echoed or generalized the old prompt's non-continuous-activation
orientation, rather than independently establishing a mechanism. Other selected
claims went beyond available evidence: output-variance computation, a link to a
closed interface window, exhaustive training-corpus scope, and treating absent
input telemetry as absent tracking. The corpus phrase may be rhetorical. Do not
turn candidate counts into a truth, experience or model-quality score.

The blind notes identify examples, qualifications and connected explanatory
steps in both conditions, with recurring mirror/bridge/presence imagery. This
study does not show that reservoir leak caused that recurrence. Nor does it test
Astrid's model response. Repeated interests and short or open-ended writing remain
legitimate; no topic prescription or novelty enforcement follows from this data.

## Reproduction And Evidence

Evidence root: `/Users/v/other/worktrees/lighter-reflection-20261025`.
`scripts/reflection_comparison_analysis.py` produces `analysis.json` from the
frozen packet, full results and retained blind ratings. Three synthetic analysis
tests pass. The complete Python suite passes 2,881 tests plus 342 subtests, with
two existing skips (`minime-suite-final-05.log`). Earlier failed invocations are
retained. The comparison harness has 66 focused tests; no runtime assertions were
weakened for the study.

- Final packet: `prompt-comparison-05/packet.json`, SHA-256
  `b689ef872bb0faa1382c8fabc48a4ae4f7a674f5936a5b97c83726b4290459a5`.
- Completion summary SHA-256:
  `8915efd3b6a4b99f676af0a389d91602259af418f78ef7df7209bf4ab08a89d7`.
- Resource receipt SHA-256:
  `c97281c75a8b50afc6fb18166b9d641f343fcc4d6159def3b8cf8327b42caf90`.
- Blind input SHA-256:
  `18427beda32bd6b30ac608428c2ec6ed73e235fe42aa08a69711832594e837c5`.
- Post-run verification SHA-256:
  `5e5fecc4b6f938313cbb0df334ab12d673312f2e2a74ad303986b3784e53ea99`.
- Blind ratings SHA-256:
  `2c0574efc592b45f0c347a049ebf4a623ad11b03189df9f20578dbcf40b49c29`.
- Source reconciliation SHA-256:
  `36e703d8304ca0dc51720251022c95171cee52d3e15aa8c0b904f452a00d85bb`.
- Canonical analysis SHA-256:
  `fa1010f0772c48bec40d3bbff50a797d7e2eb3a16d5b19f2e53090305e51d31f`.

Retain `blind-ratings.json`, `blind-review-notes.md`, `claim-reconciliation.json`,
`analysis.json`, `unique-seed-metrics.json`, requests, complete responses and
bounded wire evidence. The blind review's auxiliary lexical notes exclude final
NEXT and fold apostrophes; canonical analysis includes the full text. Those
normalization choices are documented separately, not silently pooled.

Limits: one model, five seeds, a single blind reviewer and a small fixed sample.
Synthetic mailbox counts are not actual correspondence. Live services shared the
host hardware, so wall times are descriptive rather than isolated performance
comparisons. Ollama selected runner batch sizes dynamically; this is recorded in
provider logs. Earlier failures and the first retained result came from distinct
harness-containment revisions. No statistical significance, subjective gain,
stable live outcome or language effect of leak is established.

The qualified presentation change can proceed on its contract merits after fresh
approval: less unsolicited framing, exact voluntary continuation and unchanged
mailbox/attention/storage protections. These results do not justify automatic
recall, another prompt iteration, or changing live reservoir parameters.

## Qualified Release Boundary

Astrid's runtime source remains `c42bc98032`; stage 02 reuses the verified stage-01
binaries without another compilation. Stage-02 manifest SHA-256:
`08caae60e72ef7908ca8e0fdf3e812e5800c66cb67082f9cb51093ac5287d482`.
Preservation-02 receipt SHA-256:
`1a1098aa4fd60851e4e97c4544383e0e7b0e17d59beb826cfe3919cded64610a`.
Minime's runtime change is `9ec7add`; its 106-input reconciliation-02 SHA-256 is
`a955b63e094e57e7658d206ad5a2249e4fcde89f6333ee7ec213815f8bb25227`.
The later offline commits do not change that runtime inventory; both frozen and
candidate hashes were rechecked with no drift.

Qualification includes 432 shared-reader/writer tests, 2,590 bridge tests with
three existing ignores, strict shared/bridge Clippy, formatting, domain audit,
149 deployment/handoff tests plus 167 subtests (three skips), and the frozen
2,814-test Minime suite plus 342 subtests (two skips). The newer 2,881-test full
suite additionally covers the independent harness/analysis code. ESN qualification
includes 23 production tests, four runner tests and all 12 strengthened controls.

No service activation, main-branch integration or push has occurred in this
tranche. Fresh approval and cooperative preflight remain required. Paused
automations remain paused. Current caches remain referenced by qualification;
the closeout audit is within budget, with about 367 GB free and no deletion.
