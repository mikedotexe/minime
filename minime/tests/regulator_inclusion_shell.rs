//! Structural regressions for the `regulator` inclusion shell.
//!
//! Requested by Astrid in three source-first introspections of
//! `minime/src/regulator/core.rs` (source SHA-256
//! `46828f4c813eb88aae30212793f698285c696c108dd405604ffb6b5129827d97`):
//!
//! * `introspection_minime_regulator_1788849273` — "Symbol Resolution Test:
//!   Verify that `core/rate_gate.rs` (L22) correctly resolves as a set of
//!   inlined items within the `regulator` namespace rather than a nested
//!   module (since `include!` does not create a `mod` boundary)."
//! * `introspection_minime_regulator_1788706380` — "Inclusion Resolution
//!   Test" plus "Source Integrity Test: ... detect any additions or removals
//!   of `include!` paths in `core.rs`."
//! * `introspection_minime_regulator_1788542062` — "Structural Resolution
//!   Test ... (Note: This is a build-time invariant; if the project compiles,
//!   the inclusion is successful)" plus the same inclusion-integrity ask,
//!   naming `core/pi.rs` at L23.
//!
//! Scope boundary, stated because Astrid's reports insist on it: these tests
//! assert *structural presence and reachability only*. They assert nothing
//! about runtime activation, control effect, or the value of any coefficient
//! defined inside an included file. That is the "presence vs. activation"
//! distinction her reports name as the "Ghost of Implementation" snag, and it
//! is deliberately preserved here.

/// Astrid's Symbol/Inclusion/Structural Resolution Test.
///
/// `include!("core/rate_gate.rs")` at `core.rs` L22 textually inlines that
/// file's items; it does not introduce a `mod rate_gate` boundary. The items
/// therefore land in `regulator::core`, and `src/regulator.rs`'s
/// `pub use core::*;` re-exports them to `minime::regulator`.
///
/// Naming the types through `minime::regulator::…` from outside the crate
/// exercises that whole chain: if `include!` ever gained a module boundary,
/// or if the `pub use core::*;` glob were dropped, this file would fail to
/// compile — which is exactly the build-time invariant
/// `introspection_minime_regulator_1788542062` describes.
#[test]
fn rate_gate_items_resolve_unqualified_in_the_regulator_namespace() {
    use minime::regulator::{Decision, GateCfg, ItemMeta, MemMode, Modality, RateCfg};

    // Struct literals prove the type *and* its fields resolve at
    // `minime::regulator::`, with no `rate_gate::` path segment anywhere.
    let rate = RateCfg {
        target_lambda: 1.0,
        k_p: 0.0,
        k_d: 0.0,
        min_rate: 1.0,
        max_rate: 2.0,
        smooth: 0.5,
    };
    let gate = GateCfg {
        proj_tau_hi: 0.0,
        proj_tau_lo: 0.0,
        hysteresis: 0.0,
        decay_keep: 0.0,
    };
    let modality = Modality {
        name: "structural-probe".to_string(),
        dim: 1,
        rate_now: 0.0,
        bucket_tokens: 0.0,
        bucket_cap: 0.0,
        last_decision: false,
        utility_w: 0.0,
    };
    let feature = [0.0_f32];
    let item = ItemMeta {
        modality_idx: 0,
        feature: &feature,
        tokens_cost: 0.0,
    };

    // Enums from the same included file resolve at the same path.
    let decisions = [Decision::Admit, Decision::Attenuate(0.5), Decision::Defer];
    let modes = [MemMode::Shared, MemMode::Managed, MemMode::Private];

    // Structural assertions only: shape, not tuning.
    assert_eq!(modality.name, "structural-probe");
    assert_eq!(item.feature.len(), modality.dim);
    assert!(rate.max_rate > rate.min_rate);
    assert!(gate.decay_keep <= 1.0);
    assert_eq!(decisions.len(), 3);
    assert_eq!(modes.len(), 3);
}

/// `RegulatorState` is the aggregate defined in the same included file and is
/// the item `runtime.rs` reaches through `use crate::regulator::*;`. Naming it
/// explicitly keeps the glob import from being the only thing pinning it.
#[test]
fn regulator_state_resolves_in_the_regulator_namespace() {
    use minime::regulator::{GateCfg, RateCfg, RegulatorState};

    let state = RegulatorState {
        cfg_r: RateCfg::default(),
        cfg_g: GateCfg::default(),
        modes: Vec::new(),
        lambda_now: 0.0,
        dlam_dt: 0.0,
        lambda_ema: 0.0,
        geom_rel: 0.0,
    };

    // Field presence only. `RateCfg::default()` consults `HOMEOSTAT_STRONG`,
    // so its coefficients are deliberately not asserted here: those values
    // belong to `core/rate_gate.rs`, not to the `core.rs` shell.
    assert!(state.modes.is_empty());
    assert_eq!(state.lambda_now, 0.0);
}

/// Astrid's Inclusion/Source Integrity Test.
///
/// Her literal proposal was to compare `core.rs`'s whole-file SHA-256 against
/// a pinned hash. The invariant she wants protected is narrower and stated
/// plainly in both reports — "no include paths have been added or removed" —
/// so this pins the exact ordered `include!` list instead. A whole-file hash
/// would also fail on a comment edit, which is not the drift she named.
#[test]
fn core_shell_includes_exactly_the_nine_expected_paths_in_order() {
    const CORE_RS: &str = include_str!("../src/regulator/core.rs");

    // The nine paths, in the order they appear at core.rs L16..=L24.
    const EXPECTED: [&str; 9] = [
        "core/telemetry_types.rs",
        "core/viscosity.rs",
        "core/resonance_evidence.rs",
        "core/pressure_types.rs",
        "core/reviews.rs",
        "core/pressure_source.rs",
        "core/rate_gate.rs",
        "core/pi.rs",
        "core/tests.rs",
    ];

    let found: Vec<&str> = CORE_RS
        .lines()
        .filter_map(|line| {
            let rest = line.trim().strip_prefix("include!(\"")?;
            rest.strip_suffix("\");")
        })
        .collect();

    assert_eq!(
        found, EXPECTED,
        "the include! set in regulator/core.rs changed; re-read the shell and \
         update this pin deliberately, then re-check anything that attributed \
         behavior to a removed or added inclusion"
    );
}

/// The shell carries no logic of its own. This pins the second half of
/// Astrid's "Observed" claim — "no active logic, state-handling, or
/// coefficients" — so a later drift toward putting mechanics in the shell is
/// caught rather than silently contradicting her structural map.
#[test]
fn core_shell_declares_no_items_of_its_own() {
    const CORE_RS: &str = include_str!("../src/regulator/core.rs");

    for (idx, line) in CORE_RS.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.is_empty()
            || trimmed.starts_with("//")
            || trimmed.starts_with("#!")
            || trimmed.starts_with("include!(\"")
            || trimmed == "use serde::{Deserialize, Serialize};"
        {
            continue;
        }
        panic!(
            "regulator/core.rs line {} is neither a comment, an attribute, the \
             serde import, nor an include!: {trimmed:?}",
            idx.saturating_add(1)
        );
    }
}
