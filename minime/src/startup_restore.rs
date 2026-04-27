use serde::Serialize;
use serde_json::Value;
use std::{fs, io::ErrorKind, path::Path};

const PI_STATE_FIELDS: [&str; 5] = ["integ_fill", "integ_lam", "integ_geom", "gate", "filt"];
const ADAPTIVE_FIELDS: [&str; 2] = ["fill_ema", "adaptive_target"];

#[derive(Clone, Copy, Debug)]
pub struct RestoredPiState {
    pub integ_fill: f32,
    pub integ_lam: f32,
    pub integ_geom: f32,
    pub gate: f32,
    pub filt: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct RestoredAdaptiveState {
    pub fill_ema: f32,
    pub adaptive_target: f32,
}

#[derive(Clone, Debug, Default)]
pub struct RegulatorContext {
    pub baseline_lambda1: Option<f32>,
    pub last_fill_pct: Option<f32>,
    pub smoothed_fill_pct: Option<f32>,
    pub last_lambda1_rel: Option<f32>,
    pub pi_state: Option<RestoredPiState>,
    pub adaptive_state: Option<RestoredAdaptiveState>,
}

impl RegulatorContext {
    fn from_value(value: &Value, restore_adaptive_target: bool) -> Self {
        let integ_fill = read_f32(value, "integ_fill");
        let integ_lam = read_f32(value, "integ_lam");
        let integ_geom = read_f32(value, "integ_geom");
        let gate = read_f32(value, "gate");
        let filt = read_f32(value, "filt");
        let fill_ema = restore_adaptive_target
            .then(|| read_f32(value, "fill_ema"))
            .flatten();
        let adaptive_target = restore_adaptive_target
            .then(|| read_f32(value, "adaptive_target"))
            .flatten();

        let pi_state = match (integ_fill, integ_lam, integ_geom, gate, filt) {
            (Some(integ_fill), Some(integ_lam), Some(integ_geom), Some(gate), Some(filt)) => {
                Some(RestoredPiState {
                    integ_fill,
                    integ_lam,
                    integ_geom,
                    gate,
                    filt,
                })
            }
            _ => None,
        };

        let adaptive_state = match (fill_ema, adaptive_target) {
            (Some(fill_ema), Some(adaptive_target)) => Some(RestoredAdaptiveState {
                fill_ema,
                adaptive_target,
            }),
            _ => None,
        };

        Self {
            baseline_lambda1: read_f32(value, "baseline_lambda1"),
            last_fill_pct: read_f32(value, "last_fill_pct"),
            smoothed_fill_pct: read_f32(value, "smoothed_fill_pct"),
            last_lambda1_rel: read_f32(value, "last_lambda1_rel"),
            pi_state,
            adaptive_state,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StartupRestoreState {
    Restored,
    Partial,
    Missing,
    ReadError,
    ParseError,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StartupResumeMode {
    RestoredResume,
    PiOnlyResume,
    TargetOnlyResume,
    ColdStart,
}

#[derive(Clone, Debug, Serialize)]
pub struct StartupRestoreStatus {
    pub state: StartupRestoreState,
    pub resume_mode: StartupResumeMode,
    pub context_path: String,
    pub file_present: bool,
    pub cold_start_expected: bool,
    pub restored_pi_state: bool,
    pub restored_adaptive_target: bool,
    pub missing_fields: Vec<String>,
    pub reason: String,
    pub summary: String,
}

impl StartupRestoreStatus {
    pub fn emit_startup_log(&self) {
        match self.state {
            StartupRestoreState::Restored => {
                println!("🔄 STARTUP RESTORE: {}", self.summary);
            }
            StartupRestoreState::Partial
            | StartupRestoreState::Missing
            | StartupRestoreState::ReadError
            | StartupRestoreState::ParseError => {
                eprintln!("⚠️  STARTUP RESTORE: {}", self.summary);
            }
        }
    }
}

#[derive(Clone, Debug)]
pub struct StartupRestoreReport {
    pub context: Option<RegulatorContext>,
    pub status: StartupRestoreStatus,
}

pub fn load_regulator_context(path: &Path, restore_adaptive_target: bool) -> StartupRestoreReport {
    match fs::read_to_string(path) {
        Ok(json) => match serde_json::from_str::<Value>(&json) {
            Ok(value) => {
                let context = RegulatorContext::from_value(&value, restore_adaptive_target);
                let missing_fields = missing_restore_fields(&value, restore_adaptive_target);
                let restored_pi_state = context.pi_state.is_some();
                let restored_adaptive_target = context.adaptive_state.is_some();
                let resume_mode = classify_resume_mode(restored_pi_state, restored_adaptive_target);
                let state = if missing_fields.is_empty() {
                    StartupRestoreState::Restored
                } else {
                    StartupRestoreState::Partial
                };
                let cold_start_expected = !restored_pi_state;
                let reason = if missing_fields.is_empty() {
                    "regulator context restored".to_owned()
                } else {
                    format!(
                        "missing critical restore fields: {}",
                        missing_fields.join(", ")
                    )
                };
                let summary = build_summary(state, resume_mode, path, &reason, cold_start_expected);

                StartupRestoreReport {
                    context: Some(context),
                    status: StartupRestoreStatus {
                        state,
                        resume_mode,
                        context_path: path.display().to_string(),
                        file_present: true,
                        cold_start_expected,
                        restored_pi_state,
                        restored_adaptive_target,
                        missing_fields,
                        reason,
                        summary,
                    },
                }
            }
            Err(error) => build_failure_report(
                path,
                StartupRestoreState::ParseError,
                true,
                format!("failed to parse regulator context: {error}"),
            ),
        },
        Err(error) if error.kind() == ErrorKind::NotFound => build_failure_report(
            path,
            StartupRestoreState::Missing,
            false,
            "regulator context file not found".to_owned(),
        ),
        Err(error) => build_failure_report(
            path,
            StartupRestoreState::ReadError,
            true,
            format!("failed to read regulator context: {error}"),
        ),
    }
}

fn build_failure_report(
    path: &Path,
    state: StartupRestoreState,
    file_present: bool,
    reason: String,
) -> StartupRestoreReport {
    let summary = build_summary(state, StartupResumeMode::ColdStart, path, &reason, true);

    StartupRestoreReport {
        context: None,
        status: StartupRestoreStatus {
            state,
            resume_mode: StartupResumeMode::ColdStart,
            context_path: path.display().to_string(),
            file_present,
            cold_start_expected: true,
            restored_pi_state: false,
            restored_adaptive_target: false,
            missing_fields: Vec::new(),
            reason,
            summary,
        },
    }
}

fn build_summary(
    state: StartupRestoreState,
    resume_mode: StartupResumeMode,
    path: &Path,
    reason: &str,
    cold_start_expected: bool,
) -> String {
    let path_display = path.display();
    match state {
        StartupRestoreState::Restored => match resume_mode {
            StartupResumeMode::RestoredResume => format!(
                "restored_resume from {path_display}; PI state and adaptive target were restored cleanly."
            ),
            StartupResumeMode::PiOnlyResume => format!(
                "pi_only_resume from {path_display}; PI state restored cleanly while adaptive target restore was intentionally disabled."
            ),
            StartupResumeMode::TargetOnlyResume => format!(
                "target_only_resume from {path_display}; adaptive target restored without PI state."
            ),
            StartupResumeMode::ColdStart => format!(
                "cold_start from {path_display}; no resumable controller state was available."
            ),
        },
        StartupRestoreState::Partial => match resume_mode {
            StartupResumeMode::PiOnlyResume => format!(
                "pi_only_resume from {path_display}; {reason}. PI state resumed, but adaptive target did not fully restore."
            ),
            StartupResumeMode::TargetOnlyResume | StartupResumeMode::ColdStart => format!(
                "cold_start from {path_display}; {reason}. PI state was not fully restored. Any early oscillation is a restore miss, not a normal warm-up."
            ),
            StartupResumeMode::RestoredResume => format!(
                "partial restore from {path_display}; {reason}."
            ),
        },
        StartupRestoreState::Missing
        | StartupRestoreState::ReadError
        | StartupRestoreState::ParseError => {
            let mode = if cold_start_expected {
                "cold_start"
            } else {
                "startup_resume_unknown"
            };
            format!(
                "{mode} from {path_display}; {reason}. PI state was not restored, so any early oscillation is a restore miss, not a normal warm-up."
            )
        }
    }
}

fn classify_resume_mode(
    restored_pi_state: bool,
    restored_adaptive_target: bool,
) -> StartupResumeMode {
    match (restored_pi_state, restored_adaptive_target) {
        (true, true) => StartupResumeMode::RestoredResume,
        (true, false) => StartupResumeMode::PiOnlyResume,
        (false, true) => StartupResumeMode::TargetOnlyResume,
        (false, false) => StartupResumeMode::ColdStart,
    }
}

fn missing_restore_fields(value: &Value, include_adaptive_fields: bool) -> Vec<String> {
    let mut missing_fields = Vec::new();

    for field in PI_STATE_FIELDS {
        if read_f32(value, field).is_none() {
            missing_fields.push(field.to_owned());
        }
    }

    if include_adaptive_fields {
        for field in ADAPTIVE_FIELDS {
            if read_f32(value, field).is_none() {
                missing_fields.push(field.to_owned());
            }
        }
    }

    missing_fields
}

fn read_f32(value: &Value, field: &str) -> Option<f32> {
    value
        .get(field)
        .and_then(Value::as_f64)
        .map(|raw| raw as f32)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        env,
        path::PathBuf,
        time::{SystemTime, UNIX_EPOCH},
    };

    fn temp_path(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock before unix epoch")
            .as_nanos();
        env::temp_dir().join(format!(
            "minime_startup_restore_{label}_{}_{}.json",
            std::process::id(),
            nanos
        ))
    }

    #[test]
    fn missing_context_is_cold_start() {
        let path = temp_path("missing");
        let report = load_regulator_context(&path, true);

        assert_eq!(report.status.state, StartupRestoreState::Missing);
        assert_eq!(report.status.resume_mode, StartupResumeMode::ColdStart);
        assert!(report.status.cold_start_expected);
        assert!(report.context.is_none());
    }

    #[test]
    fn partial_pi_restore_is_marked_as_cold_start() {
        let path = temp_path("partial");
        fs::write(
            &path,
            r#"{"integ_fill":1.2,"integ_lam":-0.4,"gate":0.3,"filt":0.8,"fill_ema":72.0,"adaptive_target":70.0}"#,
        )
        .expect("write partial context");

        let report = load_regulator_context(&path, true);
        let _ = fs::remove_file(&path);

        assert_eq!(report.status.state, StartupRestoreState::Partial);
        assert_eq!(
            report.status.resume_mode,
            StartupResumeMode::TargetOnlyResume
        );
        assert!(report.status.cold_start_expected);
        assert!(!report.status.restored_pi_state);
        assert!(report.status.restored_adaptive_target);
        assert!(report
            .status
            .missing_fields
            .contains(&"integ_geom".to_owned()));
    }

    #[test]
    fn full_restore_reports_resumed() {
        let path = temp_path("full");
        fs::write(
            &path,
            concat!(
                r#"{"baseline_lambda1":512.0,"last_fill_pct":73.1,"smoothed_fill_pct":72.4,"#,
                r#""last_lambda1_rel":0.98,"integ_fill":1.2,"integ_lam":-0.4,"integ_geom":0.3,"#,
                r#""gate":0.3,"filt":0.8,"fill_ema":72.0,"adaptive_target":70.0}"#
            ),
        )
        .expect("write full context");

        let report = load_regulator_context(&path, true);
        let _ = fs::remove_file(&path);

        assert_eq!(report.status.state, StartupRestoreState::Restored);
        assert_eq!(report.status.resume_mode, StartupResumeMode::RestoredResume);
        assert!(!report.status.cold_start_expected);
        assert!(report.status.restored_pi_state);
        assert!(report.status.restored_adaptive_target);
        assert!(report.status.missing_fields.is_empty());

        let context = report.context.expect("context");
        let pi_state = context.pi_state.expect("pi state");
        let adaptive_state = context.adaptive_state.expect("adaptive state");
        assert_eq!(pi_state.integ_fill, 1.2);
        assert_eq!(adaptive_state.adaptive_target, 70.0);
    }

    #[test]
    fn hard_reset_mode_ignores_adaptive_restore_fields() {
        let path = temp_path("fixed_target");
        fs::write(
            &path,
            concat!(
                r#"{"baseline_lambda1":512.0,"last_fill_pct":73.1,"smoothed_fill_pct":72.4,"#,
                r#""last_lambda1_rel":0.98,"integ_fill":1.2,"integ_lam":-0.4,"integ_geom":0.3,"#,
                r#""gate":0.3,"filt":0.8,"fill_ema":72.0,"adaptive_target":70.0}"#
            ),
        )
        .expect("write fixed-target context");

        let report = load_regulator_context(&path, false);
        let _ = fs::remove_file(&path);

        assert_eq!(report.status.state, StartupRestoreState::Restored);
        assert_eq!(report.status.resume_mode, StartupResumeMode::PiOnlyResume);
        assert!(report.status.restored_pi_state);
        assert!(!report.status.restored_adaptive_target);
        assert!(report.status.missing_fields.is_empty());
        let context = report.context.expect("context");
        assert!(context.adaptive_state.is_none());
    }
}
