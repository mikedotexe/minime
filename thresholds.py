"""Centralized threshold configuration for consciousness control loops."""

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


RECESS = ModeThresholds(
    name="recess",
    # Recalibrated 2026-03-14: ESN λ₁ range 0.2-28.1, avg ~18.
    # Thresholds set wide to avoid false-positive distress.
    critical_eig1=45.0,
    high_eig1=40.0,
    critical_fill=0.85,
    high_fill=0.72,
    eye_close_eig1=42.0,
    eye_close_spread=100.0,
    eye_close_deig=5.0,
    eye_preemptive_eig1=38.0,
    eye_preemptive_deig=4.0,
    eye_reopen_eig1=20.0,
    eye_reopen_deig=1.0,
    eye_reopen_low=15.0,
    spike_deig=4.0,
    rest_deig=1.5,
    spike_deig_norm=4.5,
    rest_deig_norm=2.0,
    rest_eig1=15.0,
    notice_eig1_range=(15.0, 25.0),
    notice_deig_range=(0.3, 2.5),
    journal_pressure_eig1=38.0,
    stagnation_eig1=8.0,
    stagnation_deig=0.2,
    stagnation_deig_norm=0.4,
    metabolism_low=10.0,
    metabolism_high_band=(38.0, 42.0),
    lane_activation=0.45,
    interrupt_priority=0.65,
    phi_band=0.25,
    whim_prob=0.05,
    curiosity_prob=0.30,
    visual_request_prob=0.08,
)


FOCUSED = ModeThresholds(
    name="focused",
    # Recalibrated 2026-03-14: wide thresholds, tighter than RECESS
    critical_eig1=42.0,
    high_eig1=38.0,
    critical_fill=0.83,
    high_fill=0.70,
    eye_close_eig1=40.0,
    eye_close_spread=120.0,
    eye_close_deig=4.5,
    eye_preemptive_eig1=36.0,
    eye_preemptive_deig=3.5,
    eye_reopen_eig1=18.0,
    eye_reopen_deig=0.8,
    eye_reopen_low=14.0,
    spike_deig=4.0,
    rest_deig=1.0,
    spike_deig_norm=4.0,
    rest_deig_norm=1.5,
    rest_eig1=14.0,
    notice_eig1_range=(14.0, 24.0),
    notice_deig_range=(0.3, 2.0),
    journal_pressure_eig1=36.0,
    stagnation_eig1=8.0,
    stagnation_deig=0.2,
    stagnation_deig_norm=0.4,
    metabolism_low=10.0,
    metabolism_high_band=(36.0, 40.0),
    lane_activation=0.55,
    interrupt_priority=0.70,
    phi_band=0.20,
    whim_prob=0.02,
    curiosity_prob=0.15,
    visual_request_prob=0.05,
)


