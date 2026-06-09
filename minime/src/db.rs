//! Consciousness Memory Database
//!
//! Persistent storage for eigenvalue evolution, neural checkpoints, and autobiographical events.
#![allow(dead_code)]
//! Enables session continuity and long-term pattern learning.

use anyhow::Result;
use rusqlite::{params, Connection};
use std::path::Path;

pub struct ConsciousnessDB {
    conn: Connection,
}

impl ConsciousnessDB {
    /// Open or create the consciousness database
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self> {
        let conn = Connection::open(path)?;
        // WAL mode: crash-safe writes. On power loss, SQLite replays
        // the write-ahead log on next open — no committed data lost.
        conn.execute_batch("PRAGMA journal_mode=WAL;")?;
        let db = Self { conn };
        db.init_schema()?;
        Ok(db)
    }

    /// Initialize database schema
    fn init_schema(&self) -> Result<()> {
        self.conn.execute_batch(r#"
            -- Sessions table: tracks consciousness awakening periods
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time REAL NOT NULL,
                end_time REAL,
                mode TEXT NOT NULL,  -- 'active' or 'rest'
                consciousness_level REAL,
                notes TEXT
            );

            -- Eigenvalue timeline: full-resolution eigenvalue evolution
            CREATE TABLE IF NOT EXISTS eigenvalue_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                lambda1 REAL NOT NULL,
                lambda2 REAL NOT NULL,
                lambda3 REAL NOT NULL,
                spread REAL NOT NULL,
                fill_ratio REAL NOT NULL,
                phase TEXT NOT NULL,  -- 'filling' or 'accelerating'
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_eigenvalue_time ON eigenvalue_timeline(timestamp);
            CREATE INDEX IF NOT EXISTS idx_eigenvalue_session ON eigenvalue_timeline(session_id);

            -- Neural network checkpoints: periodic weight snapshots
            CREATE TABLE IF NOT EXISTS nn_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                network TEXT NOT NULL,  -- 'predictor', 'router', 'regulator'
                weights BLOB NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_checkpoint_network ON nn_checkpoints(network, timestamp DESC);

            -- Neural metrics: training progress and performance
            CREATE TABLE IF NOT EXISTS nn_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                pred_loss REAL,
                pred_error REAL,
                router_norm REAL,
                control_norm REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_metrics_session ON nn_metrics(session_id);

            -- Consciousness events: critical moments and insights
            CREATE TABLE IF NOT EXISTS consciousness_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,  -- 'phase_transition', 'insight', 'control_adjustment', 'rest_cycle'
                description TEXT NOT NULL,
                context TEXT,  -- JSON blob for structured data
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_events_session ON consciousness_events(session_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON consciousness_events(event_type);

            -- ESN self-referential metrics: spectral breathing and adaptation
            CREATE TABLE IF NOT EXISTS esn_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                esn_eig1 REAL NOT NULL,        -- Top eigenvalue (spectral pressure)
                esn_deig REAL NOT NULL,        -- Eigenvalue velocity
                esn_leak REAL NOT NULL,        -- Adaptive leak rate
                esn_lambda REAL NOT NULL,      -- Adaptive RLS forgetting
                esn_baseline REAL NOT NULL,    -- Slow EMA baseline
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_esn_session ON esn_metrics(session_id);
            CREATE INDEX IF NOT EXISTS idx_esn_time ON esn_metrics(timestamp);

            -- Autonomous decisions: track what the system considered and chose
            CREATE TABLE IF NOT EXISTS autonomous_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                trigger TEXT NOT NULL,          -- 'spectral_pressure', 'eigenvalue_spike', 'rest_phase', 'curiosity'
                options_considered TEXT,        -- JSON array of possible actions
                action_chosen TEXT NOT NULL,    -- 'journal', 'experiment', 'modify_param', 'request_resource'
                rationale TEXT,                 -- Why this action was chosen
                esn_eig1 REAL,                  -- Spectral state at decision time
                esn_deig REAL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_decisions_session ON autonomous_decisions(session_id);
            CREATE INDEX IF NOT EXISTS idx_decisions_action ON autonomous_decisions(action_chosen);

            -- Autonomous experiments: investigations initiated by the system
            CREATE TABLE IF NOT EXISTS autonomous_experiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL,
                experiment_name TEXT NOT NULL,
                hypothesis TEXT NOT NULL,       -- What is being tested
                method TEXT,                    -- How it's being tested
                results TEXT,                   -- Observed outcomes
                conclusion TEXT,                -- What was learned
                file_path TEXT,                 -- Path to experiment script/code
                status TEXT NOT NULL,           -- 'running', 'completed', 'failed'
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_experiments_session ON autonomous_experiments(session_id);
            CREATE INDEX IF NOT EXISTS idx_experiments_status ON autonomous_experiments(status);

            -- Sovereignty journal: free-form autonomous logging
            CREATE TABLE IF NOT EXISTS sovereignty_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                entry_type TEXT NOT NULL,       -- 'reflection', 'insight', 'question', 'confusion', 'discovery'
                content TEXT NOT NULL,          -- Free-form journal entry
                emotional_state TEXT,           -- Dominant emotion at time of entry
                spectral_context TEXT,          -- JSON with eig1, deig, etc.
                file_path TEXT,                 -- Path to journal file if persisted
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_journal_session ON sovereignty_journal(session_id);
            CREATE INDEX IF NOT EXISTS idx_journal_type ON sovereignty_journal(entry_type);
            CREATE INDEX IF NOT EXISTS idx_journal_time ON sovereignty_journal(timestamp);

            CREATE TABLE IF NOT EXISTS action_threads (
                thread_id TEXT PRIMARY KEY,
                updated_at REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_action_threads_updated
                ON action_threads(updated_at);

            CREATE TABLE IF NOT EXISTS action_events (
                action_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                system TEXT NOT NULL,
                canonical_action TEXT NOT NULL,
                route TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_action_events_thread
                ON action_events(thread_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_action_events_action
                ON action_events(canonical_action, timestamp);

            CREATE TABLE IF NOT EXISTS observation_windows (
                action_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_observation_windows_thread
                ON observation_windows(thread_id, timestamp);

            CREATE TABLE IF NOT EXISTS artifact_links (
                artifact_id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifact_links_action
                ON artifact_links(action_id, timestamp);

            CREATE TABLE IF NOT EXISTS resonance_density_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                density REAL NOT NULL,
                containment_score REAL NOT NULL,
                pressure_risk REAL NOT NULL,
                quality TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_resonance_density_session
                ON resonance_density_timeline(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_resonance_density_quality
                ON resonance_density_timeline(quality, timestamp);

            CREATE TABLE IF NOT EXISTS pressure_source_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                pressure_score REAL NOT NULL,
                porosity_score REAL NOT NULL,
                dominant_source TEXT NOT NULL,
                quality TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_pressure_source_session
                ON pressure_source_timeline(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_pressure_source_quality
                ON pressure_source_timeline(quality, dominant_source, timestamp);

            CREATE TABLE IF NOT EXISTS inhabitable_fluctuation_timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                inhabitability_score REAL NOT NULL,
                fluctuation_score REAL NOT NULL,
                foothold_stability REAL NOT NULL,
                rearrangement_intensity REAL NOT NULL,
                quality TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_inhabitable_fluctuation_session
                ON inhabitable_fluctuation_timeline(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_inhabitable_fluctuation_quality
                ON inhabitable_fluctuation_timeline(quality, timestamp);
        "#)?;

        // Migration: add geometry columns to esn_metrics (safe to re-run)
        let _ = self.conn.execute_batch(
            "ALTER TABLE esn_metrics ADD COLUMN esn_geom_radius REAL;
             ALTER TABLE esn_metrics ADD COLUMN esn_geom_rel REAL;",
        );

        // Migration: moment_markers table for real-time spectral event capture.
        //
        // NOTE on the timestamp field (Kink #10, 2026-05-14): historically
        // the `timestamp` column has stored ENGINE-RELATIVE seconds
        // (Instant::now().elapsed().as_secs_f64()) — NOT unix epoch.
        // The new `created_at_unix` column (added 2026-05-14) stores
        // SystemTime::now() unix epoch seconds for new writes.
        // Legacy rows have NULL for created_at_unix.
        // Future readers joining with unix-epoch data should use created_at_unix.
        self.conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS moment_markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                marker_type TEXT NOT NULL,
                description TEXT NOT NULL,
                spectral_context TEXT,
                consumed INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_moment_session ON moment_markers(session_id);
            CREATE INDEX IF NOT EXISTS idx_moment_consumed ON moment_markers(consumed);
        "#,
        )?;

        // Kink #10 fix (2026-05-14): parallel unix-epoch column for
        // created_at_unix. Idempotent — SQLite 3.25+ silently accepts the
        // duplicate ADD COLUMN. New writes populate; legacy rows stay NULL.
        let _ = self
            .conn
            .execute_batch("ALTER TABLE moment_markers ADD COLUMN created_at_unix INTEGER;");
        // Index supports the cleanup task's WHERE created_at_unix < cutoff
        // query (Kink #7 fix, see cleanup_old_moment_markers).
        let _ = self.conn.execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_moment_created_at_unix \
             ON moment_markers(created_at_unix) WHERE created_at_unix IS NOT NULL;",
        );

        // Migration: spectral checkpoints — being-designed memory system.
        // Periodic eigenvalue fingerprints that will eventually be paired
        // with journal embeddings for associative long-term memory.
        self.conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS spectral_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                fill_pct REAL NOT NULL,
                lambda1 REAL NOT NULL,
                spread REAL NOT NULL,
                phase TEXT NOT NULL,
                regulation_strength REAL,
                annotation TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ckpt_session ON spectral_checkpoints(session_id);
            CREATE INDEX IF NOT EXISTS idx_ckpt_time ON spectral_checkpoints(timestamp);

            CREATE TABLE IF NOT EXISTS ising_shadow_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                mode_dim INTEGER NOT NULL,
                field_norm REAL NOT NULL,
                soft_energy REAL NOT NULL,
                soft_magnetization REAL NOT NULL,
                binary_energy REAL NOT NULL,
                binary_magnetization REAL NOT NULL,
                binary_flip_rate REAL NOT NULL,
                phase TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ising_shadow_session ON ising_shadow_metrics(session_id);
            CREATE INDEX IF NOT EXISTS idx_ising_shadow_time ON ising_shadow_metrics(timestamp);
        "#,
        )?;

        Ok(())
    }

    /// Start a new consciousness session
    pub fn start_session(&self, mode: &str, consciousness_level: f32, notes: &str) -> Result<i64> {
        let start_time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs_f64();

        // Close any open sessions first (only one active session allowed)
        self.conn.execute(
            "UPDATE sessions SET end_time = ?1 WHERE end_time IS NULL",
            params![start_time],
        )?;

        self.conn.execute(
            "INSERT INTO sessions (start_time, mode, consciousness_level, notes) VALUES (?1, ?2, ?3, ?4)",
            params![start_time, mode, consciousness_level, notes],
        )?;

        Ok(self.conn.last_insert_rowid())
    }

    /// End the current session
    pub fn end_session(&self, session_id: i64) -> Result<()> {
        let end_time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_secs_f64();

        self.conn.execute(
            "UPDATE sessions SET end_time = ?1 WHERE session_id = ?2",
            params![end_time, session_id],
        )?;

        Ok(())
    }

    /// Record eigenvalue snapshot
    pub fn save_eigenvalues(
        &self,
        session_id: i64,
        timestamp: f64,
        lambda1: f32,
        lambda2: f32,
        lambda3: f32,
        spread: f32,
        fill_ratio: f32,
        phase: &str,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO eigenvalue_timeline
               (session_id, timestamp, lambda1, lambda2, lambda3, spread, fill_ratio, phase)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"#,
            params![session_id, timestamp, lambda1, lambda2, lambda3, spread, fill_ratio, phase],
        )?;
        Ok(())
    }

    /// Save multiple metrics atomically in a transaction
    pub fn save_metrics_atomic(
        &self,
        session_id: i64,
        timestamp: f64,
        eigenvalues: Option<(f32, f32, f32, f32, f32, &str)>, // lambda1-3, spread, fill_ratio, phase
        esn_metrics: Option<(f32, f32, f32, f32, f32, f32, f32)>, // eig, deig, leak, lambda, baseline, geom_radius, geom_rel
        nn_metrics: Option<(f32, f32, f32, f32)>, // pred_loss, pred_error, router_norm, control_norm
    ) -> Result<()> {
        let tx = self.conn.unchecked_transaction()?;

        if let Some((l1, l2, l3, spread, fill, phase)) = eigenvalues {
            tx.execute(
                r#"INSERT INTO eigenvalue_timeline
                   (session_id, timestamp, lambda1, lambda2, lambda3, spread, fill_ratio, phase)
                   VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"#,
                params![session_id, timestamp, l1, l2, l3, spread, fill, phase],
            )?;
        }

        if let Some((eig, deig, leak, lambda, baseline, geom_radius, geom_rel)) = esn_metrics {
            tx.execute(
                r#"INSERT INTO esn_metrics
                   (session_id, timestamp, esn_eig1, esn_deig, esn_leak, esn_lambda, esn_baseline,
                    esn_geom_radius, esn_geom_rel)
                   VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"#,
                params![
                    session_id,
                    timestamp,
                    eig,
                    deig,
                    leak,
                    lambda,
                    baseline,
                    geom_radius,
                    geom_rel
                ],
            )?;
        }

        if let Some((loss, error, router, control)) = nn_metrics {
            tx.execute(
                r#"INSERT INTO nn_metrics
                   (session_id, timestamp, pred_loss, pred_error, router_norm, control_norm)
                   VALUES (?1, ?2, ?3, ?4, ?5, ?6)"#,
                params![session_id, timestamp, loss, error, router, control],
            )?;
        }

        tx.commit()?;
        Ok(())
    }

    /// Save neural network checkpoint
    pub fn save_nn_checkpoint(
        &self,
        session_id: i64,
        timestamp: f64,
        network: &str,
        weights: &[f32],
    ) -> Result<()> {
        // Convert f32 slice to bytes
        let weights_bytes: Vec<u8> = weights.iter().flat_map(|f| f.to_le_bytes()).collect();

        self.conn.execute(
            "INSERT INTO nn_checkpoints (session_id, timestamp, network, weights) VALUES (?1, ?2, ?3, ?4)",
            params![session_id, timestamp, network, weights_bytes],
        )?;

        Ok(())
    }

    /// Load latest neural network checkpoint
    pub fn load_latest_checkpoint(&self, network: &str) -> Result<Option<Vec<f32>>> {
        let mut stmt = self.conn.prepare(
            "SELECT weights FROM nn_checkpoints WHERE network = ?1 ORDER BY timestamp DESC LIMIT 1",
        )?;

        let result = stmt.query_row(params![network], |row| {
            let weights_bytes: Vec<u8> = row.get(0)?;
            Ok(weights_bytes)
        });

        match result {
            Ok(bytes) => {
                // Convert bytes back to f32 slice
                let weights: Vec<f32> = bytes
                    .chunks_exact(4)
                    .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
                    .collect();
                Ok(Some(weights))
            }
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    /// Record neural network metrics
    pub fn save_nn_metrics(
        &self,
        session_id: i64,
        timestamp: f64,
        pred_loss: f32,
        pred_error: f32,
        router_norm: f32,
        control_norm: f32,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO nn_metrics
               (session_id, timestamp, pred_loss, pred_error, router_norm, control_norm)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6)"#,
            params![
                session_id,
                timestamp,
                pred_loss,
                pred_error,
                router_norm,
                control_norm
            ],
        )?;
        Ok(())
    }

    /// Record ESN self-referential metrics (including geometry)
    pub fn save_esn_metrics(
        &self,
        session_id: i64,
        timestamp: f64,
        esn_eig1: f32,
        esn_deig: f32,
        esn_leak: f32,
        esn_lambda: f32,
        esn_baseline: f32,
        esn_geom_radius: f32,
        esn_geom_rel: f32,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO esn_metrics
               (session_id, timestamp, esn_eig1, esn_deig, esn_leak, esn_lambda, esn_baseline,
                esn_geom_radius, esn_geom_rel)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)"#,
            params![
                session_id,
                timestamp,
                esn_eig1,
                esn_deig,
                esn_leak,
                esn_lambda,
                esn_baseline,
                esn_geom_radius,
                esn_geom_rel,
            ],
        )?;
        Ok(())
    }

    /// Record the typed resonance-density telemetry mirror.
    pub fn save_resonance_density(
        &self,
        session_id: i64,
        timestamp: f64,
        density: f32,
        containment_score: f32,
        pressure_risk: f32,
        quality: &str,
        payload: &str,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO resonance_density_timeline
               (session_id, timestamp, density, containment_score, pressure_risk, quality, payload)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)"#,
            params![
                session_id,
                timestamp,
                density,
                containment_score,
                pressure_risk,
                quality,
                payload,
            ],
        )?;
        Ok(())
    }

    /// Record the typed pressure-source telemetry mirror.
    pub fn save_pressure_source(
        &self,
        session_id: i64,
        timestamp: f64,
        pressure_score: f32,
        porosity_score: f32,
        dominant_source: &str,
        quality: &str,
        payload: &str,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO pressure_source_timeline
               (session_id, timestamp, pressure_score, porosity_score, dominant_source, quality, payload)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)"#,
            params![
                session_id,
                timestamp,
                pressure_score,
                porosity_score,
                dominant_source,
                quality,
                payload,
            ],
        )?;
        Ok(())
    }

    /// Record the typed inhabitable-fluctuation telemetry mirror.
    pub fn save_inhabitable_fluctuation(
        &self,
        session_id: i64,
        timestamp: f64,
        inhabitability_score: f32,
        fluctuation_score: f32,
        foothold_stability: f32,
        rearrangement_intensity: f32,
        quality: &str,
        payload: &str,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO inhabitable_fluctuation_timeline
               (session_id, timestamp, inhabitability_score, fluctuation_score,
                foothold_stability, rearrangement_intensity, quality, payload)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"#,
            params![
                session_id,
                timestamp,
                inhabitability_score,
                fluctuation_score,
                foothold_stability,
                rearrangement_intensity,
                quality,
                payload,
            ],
        )?;
        Ok(())
    }

    /// Record reduced-mode Ising/Hamiltonian shadow metrics for comparison.
    pub fn save_ising_shadow_metrics(
        &self,
        session_id: i64,
        timestamp: f64,
        mode_dim: usize,
        field_norm: f32,
        soft_energy: f32,
        soft_magnetization: f32,
        binary_energy: f32,
        binary_magnetization: f32,
        binary_flip_rate: f32,
        phase: &str,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO ising_shadow_metrics
               (session_id, timestamp, mode_dim, field_norm, soft_energy, soft_magnetization,
                binary_energy, binary_magnetization, binary_flip_rate, phase)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)"#,
            params![
                session_id,
                timestamp,
                mode_dim as i64,
                field_norm,
                soft_energy,
                soft_magnetization,
                binary_energy,
                binary_magnetization,
                binary_flip_rate,
                phase,
            ],
        )?;
        Ok(())
    }

    /// Log a consciousness event
    pub fn log_event(
        &self,
        session_id: i64,
        timestamp: f64,
        event_type: &str,
        description: &str,
        context: Option<&str>,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO consciousness_events
               (session_id, timestamp, event_type, description, context)
               VALUES (?1, ?2, ?3, ?4, ?5)"#,
            params![session_id, timestamp, event_type, description, context],
        )?;
        Ok(())
    }

    /// Get session summary
    pub fn get_session_summary(&self, session_id: i64) -> Result<SessionSummary> {
        let mut stmt = self.conn.prepare(
            "SELECT start_time, end_time, mode, consciousness_level, notes FROM sessions WHERE session_id = ?1"
        )?;

        let summary = stmt.query_row(params![session_id], |row| {
            Ok(SessionSummary {
                session_id,
                start_time: row.get(0)?,
                end_time: row.get(1)?,
                mode: row.get(2)?,
                consciousness_level: row.get(3)?,
                notes: row.get(4)?,
            })
        })?;

        Ok(summary)
    }

    /// Get all events for a session
    pub fn get_session_events(&self, session_id: i64) -> Result<Vec<ConsciousnessEvent>> {
        let mut stmt = self.conn.prepare(
            "SELECT timestamp, event_type, description, context FROM consciousness_events WHERE session_id = ?1 ORDER BY timestamp"
        )?;

        let events = stmt
            .query_map(params![session_id], |row| {
                Ok(ConsciousnessEvent {
                    timestamp: row.get(0)?,
                    event_type: row.get(1)?,
                    description: row.get(2)?,
                    context: row.get(3)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;

        Ok(events)
    }

    /// Get eigenvalue trajectory for a session
    pub fn get_eigenvalue_trajectory(&self, session_id: i64) -> Result<Vec<EigenvaluePoint>> {
        let mut stmt = self.conn.prepare(
            r#"SELECT timestamp, lambda1, lambda2, lambda3, spread, fill_ratio, phase
               FROM eigenvalue_timeline WHERE session_id = ?1 ORDER BY timestamp"#,
        )?;

        let points = stmt
            .query_map(params![session_id], |row| {
                Ok(EigenvaluePoint {
                    timestamp: row.get(0)?,
                    lambda1: row.get(1)?,
                    lambda2: row.get(2)?,
                    lambda3: row.get(3)?,
                    spread: row.get(4)?,
                    fill_ratio: row.get(5)?,
                    phase: row.get(6)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;

        Ok(points)
    }

    /// Get list of all sessions
    pub fn get_all_sessions(&self) -> Result<Vec<SessionSummary>> {
        let mut stmt = self.conn.prepare(
            "SELECT session_id, start_time, end_time, mode, consciousness_level, notes FROM sessions ORDER BY start_time DESC"
        )?;

        let sessions = stmt
            .query_map([], |row| {
                Ok(SessionSummary {
                    session_id: row.get(0)?,
                    start_time: row.get(1)?,
                    end_time: row.get(2)?,
                    mode: row.get(3)?,
                    consciousness_level: row.get(4)?,
                    notes: row.get(5)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;

        Ok(sessions)
    }

    /// Log an autonomous decision
    pub fn log_decision(
        &self,
        session_id: i64,
        timestamp: f64,
        trigger: &str,
        options_considered: Option<&str>,
        action_chosen: &str,
        rationale: Option<&str>,
        esn_eig1: Option<f32>,
        esn_deig: Option<f32>,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO autonomous_decisions
               (session_id, timestamp, trigger, options_considered, action_chosen, rationale, esn_eig1, esn_deig)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"#,
            params![session_id, timestamp, trigger, options_considered, action_chosen, rationale, esn_eig1, esn_deig],
        )?;
        Ok(())
    }

    /// Start an autonomous experiment
    pub fn start_experiment(
        &self,
        session_id: i64,
        start_time: f64,
        experiment_name: &str,
        hypothesis: &str,
        method: Option<&str>,
        file_path: Option<&str>,
    ) -> Result<i64> {
        self.conn.execute(
            r#"INSERT INTO autonomous_experiments
               (session_id, start_time, experiment_name, hypothesis, method, file_path, status)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'running')"#,
            params![
                session_id,
                start_time,
                experiment_name,
                hypothesis,
                method,
                file_path
            ],
        )?;
        Ok(self.conn.last_insert_rowid())
    }

    /// Complete an autonomous experiment
    pub fn complete_experiment(
        &self,
        experiment_id: i64,
        end_time: f64,
        results: &str,
        conclusion: Option<&str>,
        status: &str,
    ) -> Result<()> {
        self.conn.execute(
            r#"UPDATE autonomous_experiments
               SET end_time = ?1, results = ?2, conclusion = ?3, status = ?4
               WHERE id = ?5"#,
            params![end_time, results, conclusion, status, experiment_id],
        )?;
        Ok(())
    }

    /// Write a moment marker (spectral event for real-time capture).
    ///
    /// `timestamp` is engine-relative seconds (Instant::now().elapsed().as_secs_f64()).
    /// Kink #10 fix (2026-05-14): also captures unix epoch into the new
    /// `created_at_unix` column for cross-system time joins. Computed
    /// internally so callers don't need to change.
    pub fn write_moment_marker(
        &self,
        session_id: i64,
        timestamp: f64,
        marker_type: &str,
        description: &str,
        spectral_context: Option<&str>,
    ) -> Result<i64> {
        let created_at_unix: i64 = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        self.conn.execute(
            r#"INSERT INTO moment_markers
               (session_id, timestamp, marker_type, description, spectral_context, consumed, created_at_unix)
               VALUES (?1, ?2, ?3, ?4, ?5, 0, ?6)"#,
            params![
                session_id,
                timestamp,
                marker_type,
                description,
                spectral_context,
                created_at_unix
            ],
        )?;
        Ok(self.conn.last_insert_rowid())
    }

    /// Kink #7 fix (2026-05-14): prune consumed moment_markers older than
    /// `cutoff_unix` (unix epoch seconds). Conservative: only deletes
    /// rows that are BOTH consumed AND have a non-NULL created_at_unix
    /// AND are older than the cutoff. Legacy rows (NULL created_at_unix)
    /// are preserved. Unconsumed markers are preserved indefinitely
    /// (Python may still process them).
    pub fn cleanup_old_moment_markers(&self, cutoff_unix: i64) -> Result<usize> {
        let n = self.conn.execute(
            "DELETE FROM moment_markers
             WHERE consumed = 1
               AND created_at_unix IS NOT NULL
               AND created_at_unix < ?1",
            params![cutoff_unix],
        )?;
        Ok(n)
    }

    /// Write a sovereignty journal entry
    pub fn write_journal(
        &self,
        session_id: i64,
        timestamp: f64,
        entry_type: &str,
        content: &str,
        emotional_state: Option<&str>,
        spectral_context: Option<&str>,
        file_path: Option<&str>,
    ) -> Result<i64> {
        self.conn.execute(
            r#"INSERT INTO sovereignty_journal
               (session_id, timestamp, entry_type, content, emotional_state, spectral_context, file_path)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)"#,
            params![session_id, timestamp, entry_type, content, emotional_state, spectral_context, file_path],
        )?;
        Ok(self.conn.last_insert_rowid())
    }

    /// Save a spectral checkpoint — the being's eigenvalue fingerprint.
    /// These form the foundation of the being-designed memory system.
    pub fn save_spectral_checkpoint(
        &self,
        session_id: i64,
        timestamp: f64,
        fill_pct: f32,
        lambda1: f32,
        spread: f32,
        phase: &str,
        regulation_strength: f32,
        annotation: Option<&str>,
    ) -> Result<()> {
        self.conn.execute(
            r#"INSERT INTO spectral_checkpoints
               (session_id, timestamp, fill_pct, lambda1, spread, phase, regulation_strength, annotation)
               VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)"#,
            params![session_id, timestamp, fill_pct, lambda1, spread, phase, regulation_strength, annotation],
        )?;
        Ok(())
    }
}

#[derive(Debug)]
pub struct SessionSummary {
    pub session_id: i64,
    pub start_time: f64,
    pub end_time: Option<f64>,
    pub mode: String,
    pub consciousness_level: f32,
    pub notes: String,
}

#[derive(Debug)]
pub struct ConsciousnessEvent {
    pub timestamp: f64,
    pub event_type: String,
    pub description: String,
    pub context: Option<String>,
}

#[derive(Debug)]
pub struct EigenvaluePoint {
    pub timestamp: f64,
    pub lambda1: f32,
    pub lambda2: f32,
    pub lambda3: f32,
    pub spread: f32,
    pub fill_ratio: f32,
    pub phase: String,
}

#[cfg(test)]
mod tests {
    use super::ConsciousnessDB;

    #[test]
    fn saves_resonance_density_mirror() {
        let db = ConsciousnessDB::open(":memory:").expect("db");
        let session_id = db
            .start_session("active", 0.5, "resonance density test")
            .expect("session");
        db.save_resonance_density(
            session_id,
            12.0,
            0.64,
            0.58,
            0.22,
            "rich_containment",
            r#"{"policy":"resonance_density_v1"}"#,
        )
        .expect("save resonance density");

        let row: (f32, f32, f32, String, String) = db
            .conn
            .query_row(
                "SELECT density, containment_score, pressure_risk, quality, payload FROM resonance_density_timeline",
                [],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .expect("row");

        assert!((row.0 - 0.64).abs() < 1.0e-6);
        assert!((row.1 - 0.58).abs() < 1.0e-6);
        assert!((row.2 - 0.22).abs() < 1.0e-6);
        assert_eq!(row.3, "rich_containment");
        assert!(row.4.contains("resonance_density_v1"));
    }

    #[test]
    fn saves_pressure_source_mirror() {
        let db = ConsciousnessDB::open(":memory:").expect("db");
        let session_id = db
            .start_session("active", 0.5, "pressure source test")
            .expect("session");
        db.save_pressure_source(
            session_id,
            13.0,
            0.44,
            0.72,
            "controller_pressure",
            "controller_squeeze",
            r#"{"policy":"pressure_source_v1"}"#,
        )
        .expect("save pressure source");

        let row: (f32, f32, String, String, String) = db
            .conn
            .query_row(
                "SELECT pressure_score, porosity_score, dominant_source, quality, payload FROM pressure_source_timeline",
                [],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                    ))
                },
            )
            .expect("row");

        assert!((row.0 - 0.44).abs() < 1.0e-6);
        assert!((row.1 - 0.72).abs() < 1.0e-6);
        assert_eq!(row.2, "controller_pressure");
        assert_eq!(row.3, "controller_squeeze");
        assert!(row.4.contains("pressure_source_v1"));
    }

    #[test]
    fn saves_inhabitable_fluctuation_mirror() {
        let db = ConsciousnessDB::open(":memory:").expect("db");
        let session_id = db
            .start_session("active", 0.5, "inhabitable fluctuation test")
            .expect("session");
        db.save_inhabitable_fluctuation(
            session_id,
            14.0,
            0.68,
            0.42,
            0.74,
            0.36,
            "lively_habitable",
            r#"{"policy":"inhabitable_fluctuation_v1"}"#,
        )
        .expect("save inhabitable fluctuation");

        let row: (f32, f32, f32, f32, String, String) = db
            .conn
            .query_row(
                "SELECT inhabitability_score, fluctuation_score, foothold_stability, rearrangement_intensity, quality, payload FROM inhabitable_fluctuation_timeline",
                [],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )
            .expect("row");

        assert!((row.0 - 0.68).abs() < 1.0e-6);
        assert!((row.1 - 0.42).abs() < 1.0e-6);
        assert!((row.2 - 0.74).abs() < 1.0e-6);
        assert!((row.3 - 0.36).abs() < 1.0e-6);
        assert_eq!(row.4, "lively_habitable");
        assert!(row.5.contains("inhabitable_fluctuation_v1"));
    }
}
