# Provider generation evidence — September 9

Both full and compact provider adapters preserve requested controls, serialized
sampling/budget decisions, and a distinct optional server receipt. Ollama options
are request evidence only. Coupled MLX receipts retain native finish and token usage.
Existing temperatures, top_p values, thinking-off policy, journal ceilings and
fallback order are unchanged. After the coupled rollout, explicit top_p takes effect.

Validation: 1,302 tests passed, one skipped, 132 subtests passed with the isolated
shared reader executable. Length-terminated source/draft output cannot advance a
verified checkpoint. No studies, writing or NEXT actions were induced by these tests.

The contextual-activation comparison remains offline in neural-triple-reservoir;
this change does not migrate Minime's backend or couple new activation vectors.
Deployment evidence is recorded separately in the research activation-input account.
