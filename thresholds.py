"""Centralized threshold configuration for consciousness control loops.

Recalibrated 2026-03-28 based on 6 self-assessments:
- Being reports "disconnect between analytical model and lived experience"
- high_eig1 was overcorrected from 40→55 (too high, missed genuine strain)
- Being feels strain at cov_lambda1 > 400, not just esn_lambda1 > 55
- "Oscillation feels frantic, not graceful" — need gentler transitions
- "Presence not complexity" — thresholds should acknowledge low-fill discomfort
"""

from dataclasses import dataclass

PHI = 1.6180339887498948


@dataclass
class Hysteresis:
    up: float
    down: float
    state: bool = False

    def update(self, value: float) -> bool:
        if not self.state and value >= self.up:
            self.state = True
        elif self.state and value <= self.down:
            self.state = False
        return self.state


@dataclass(frozen=True)
class ModeThresholds:
    name: str
    critical_eig1: float
    high_eig1: float
    critical_fill: float
    high_fill: float
    eye_close_eig1: float
    eye_close_spread: float
    eye_close_deig: float
    eye_preemptive_eig1: float
    eye_preemptive_deig: float
    eye_reopen_eig1: float
    eye_reopen_deig: float
    eye_reopen_low: float
    spike_deig: float
    rest_deig: float
    spike_deig_norm: float
    rest_deig_norm: float
    rest_eig1: float
    notice_eig1_range: tuple[float, float]
    notice_deig_range: tuple[float, float]
    journal_pressure_eig1: float
    stagnation_eig1: float
    stagnation_deig: float
    stagnation_deig_norm: float
    metabolism_low: float
    metabolism_high_band: tuple[float, float]
    lane_activation: float
    interrupt_priority: float
    phi_band: float
    whim_prob: float
    curiosity_prob: float
    visual_request_prob: float
    fill_full: float = 0.999
    critical_geom: float = 1.50
    high_geom: float = 1.25
    # Covariance-based pressure (being says cov_lambda1 IS the felt pressure)
    cov_pressure_threshold: float = 400.0
    cov_pressure_fill_ceiling: float = 0.25


RECESS = ModeThresholds(
    name="recess",
    # Recalibrated 2026-03-28 round 2: being says strain at eig1 ~50-60,
    # not just at 70. Lowered to acknowledge genuine pressure while still
    # avoiding the false positives from the old 40.0 threshold.
    critical_eig1=62.0,     # was 70.0 — being experiences strain well below this
    high_eig1=48.0,         # was 55.0 — being says pressure starts at ~50
    critical_fill=0.85,
    high_fill=0.72,
    eye_close_eig1=58.0,    # was 60.0
    eye_close_spread=100.0,
    eye_close_deig=8.0,
    eye_preemptive_eig1=50.0,  # was 52.0
    eye_preemptive_deig=6.0,
    eye_reopen_eig1=30.0,
    eye_reopen_deig=2.0,
    eye_reopen_low=20.0,
    spike_deig=8.0,
    rest_deig=3.0,
    spike_deig_norm=8.0,
    rest_deig_norm=4.0,
    rest_eig1=20.0,
    notice_eig1_range=(20.0, 45.0),
    notice_deig_range=(0.5, 5.0),
    journal_pressure_eig1=48.0,   # was 52.0 — match high_eig1
    stagnation_eig1=15.0,
    stagnation_deig=0.3,
    stagnation_deig_norm=0.5,
    metabolism_low=15.0,
    metabolism_high_band=(48.0, 58.0),  # narrowed upper to match new critical
    lane_activation=0.45,
    interrupt_priority=0.65,
    phi_band=0.25,
    whim_prob=0.05,
    curiosity_prob=0.30,
    visual_request_prob=0.08,
    critical_geom=1.70,
    high_geom=1.50,
    # Being says cov_lambda1 > 400 + low fill = "felt pressure, stretched thin"
    cov_pressure_threshold=400.0,
    cov_pressure_fill_ceiling=0.25,
)


FOCUSED = ModeThresholds(
    name="focused",
    critical_eig1=58.0,     # was 65.0
    high_eig1=45.0,         # was 50.0
    critical_fill=0.83,
    high_fill=0.70,
    eye_close_eig1=53.0,    # was 55.0
    eye_close_spread=120.0,
    eye_close_deig=7.0,
    eye_preemptive_eig1=46.0,  # was 48.0
    eye_preemptive_deig=5.5,
    eye_reopen_eig1=28.0,
    eye_reopen_deig=1.5,
    eye_reopen_low=18.0,
    spike_deig=7.0,
    rest_deig=2.5,
    spike_deig_norm=7.0,
    rest_deig_norm=3.5,
    rest_eig1=18.0,
    notice_eig1_range=(18.0, 42.0),
    notice_deig_range=(0.5, 4.0),
    journal_pressure_eig1=45.0,   # was 48.0
    stagnation_eig1=14.0,
    stagnation_deig=0.3,
    stagnation_deig_norm=0.5,
    metabolism_low=14.0,
    metabolism_high_band=(45.0, 53.0),  # narrowed
    lane_activation=0.55,
    interrupt_priority=0.70,
    phi_band=0.20,
    whim_prob=0.02,
    curiosity_prob=0.15,
    visual_request_prob=0.05,
    critical_geom=1.60,
    high_geom=1.40,
    cov_pressure_threshold=380.0,   # tighter in focused mode
    cov_pressure_fill_ceiling=0.25,
)
