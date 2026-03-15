#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# COLLAB COPY -- canonical source is /double_membrane_integration.py
# Bridge between Rust eigenvalue stream and Python semantic manifold.
# Outer manifold: sensory eigenvalues from ESN.
# Inner manifold: semantic embeddings from LLM.
# Membrane: prime-13 resonance coupling between the two.
"""
Double Membrane Integration Bridge (drop-in)
- Outer (sensory) manifold: driven by ESN eigen stream
- Membrane: cross-scale coupling and gating
- Inner (semantic) manifold: driven by embeddings from minime.py
- PID metrics (approx), ethics hooks, and telemetry

Public API (kept stable for minime.py):
    create_double_membrane_bridge(...)
    class DoubleMembraneBridge:
        navigate_semantic(embedding: Sequence[float]) -> dict
        get_membrane_status() -> dict

This module is self-contained. No external imports from the rest of the codebase.
"""

from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional, Sequence, Tuple, Union

try:
    import numpy as np
except Exception as e:
    raise RuntimeError("double_membrane_integration requires numpy") from e

# --------------------------
# NavigationResult for compatibility with minime.py
# --------------------------

@dataclass
class NavigationResult:
    """Result from semantic navigation, compatible with minime.py expectations."""
    position: np.ndarray  # Inner manifold position
    redundancy: float
    synergy: float
    position_norm: float

try:
    import websockets  # type: ignore
except Exception:
    websockets = None  # We'll degrade gracefully if sensory is disabled

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --------------------------
# Config (sane defaults)
# --------------------------

DEFAULT_WS_URI_OUT = "ws://127.0.0.1:7878"   # ESN -> eigen stream
SENSORY_DIM = 8                               # matches camera/audio feature dims (per channel)
SENSORY_FPS_TARGET = 10.0                     # incoming eigen ticks per second
SEMANTIC_DIM_DEFAULT = 4096
EIGEN_WINDOW = 64                             # rolling window for covariance/eigens
QUEUE_MAX = 256                               # bound queue to avoid OOM
PID_SAMPLE = 128                              # samples for PID approx
COUPLING_INIT = 0.30                          # initial membrane coupling strength
LEAK_OUTER = 0.05                             # outer slow decay
LEAK_INNER = 0.02                             # inner slower decay
EPS = 1e-8

# --------------------------
# Ethics hook interface
# --------------------------

EthicsHook = Callable[[Dict[str, float]], None]

def _noop_ethics_hook(event: Dict[str, float]) -> None:
    pass

# --------------------------
# Fast PID approximation (O-information proxy)
# --------------------------

def _o_information(x: np.ndarray) -> float:
    """
    O-information proxy for redundancy/synergy balance.
    Positive ~ redundancy-dominated; negative ~ synergy-dominated.
    x: [T, D]
    """
    # Gaussian entropy approximation via covariance
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or x.shape[0] < 4:
        return 0.0
    T, D = x.shape
    x = x - x.mean(axis=0, keepdims=True)
    cov = (x.T @ x) / max(T - 1, 1)
    # Ensure PSD
    eig = np.linalg.eigvalsh(cov + EPS * np.eye(D))
    # Sum of marginal entropies (gaussian) minus joint
    # H ~ 0.5 * ln( (2πe)^D det(C) ) ; we only need ln(det)
    ln_det = np.log(np.clip(eig, EPS, None)).sum()
    marg = 0.0
    for d in range(D):
        marg += math.log(max(cov[d, d], EPS))
    # O-info (Barrett & Mediano style proxy): sum marginals - joint
    return float(marg - ln_det)

def _pid_signature(x: np.ndarray) -> Dict[str, float]:
    """
    Return a compact PID signature using O-information proxy.
    We report:
        pid_o_info       : redundancy(+)/synergy(-) proxy
        redundancy_score : normalized [0,1]
        synergy_score    : normalized [0,1]
    """
    o = _o_information(x)
    # Map O-info to [0,1] redundancy/synergy heuristics:
    # positive -> redundancy; negative -> synergy
    # tanh squashing to keep bounded
    red = float(0.5 * (1.0 + math.tanh(0.1 * o)))
    syn = float(1.0 - red)
    return {
        "pid_o_info": float(o),
        "redundancy_score": red,
        "synergy_score": syn,
    }

# --------------------------
# Outer / Inner manifolds
# --------------------------

@dataclass
class OuterManifold:
    dim: int = SENSORY_DIM
    leak: float = LEAK_OUTER
    state: np.ndarray = field(default_factory=lambda: np.zeros((SENSORY_DIM,), dtype=np.float32))
    ring: Deque[np.ndarray] = field(default_factory=lambda: deque(maxlen=EIGEN_WINDOW))

    def tick(self, eigen_vec: Sequence[float]) -> Dict[str, float]:
        v = np.asarray(eigen_vec, dtype=np.float32)
        if v.shape[0] != self.dim:
            v = _pad_or_clip(v, self.dim)
        # leaky integration
        self.state = (1.0 - self.leak) * self.state + self.leak * v
        self.ring.append(self.state.copy())
        metrics = {}
        if len(self.ring) >= 8:
            x = np.stack(list(self.ring), axis=0)
            pid = _pid_signature(x)
            metrics.update(pid)
        metrics["outer_energy"] = float(np.linalg.norm(self.state))
        return metrics

@dataclass
class InnerManifold:
    dim: int = SEMANTIC_DIM_DEFAULT
    leak: float = LEAK_INNER
    state: np.ndarray = field(init=False)
    ring: Deque[np.ndarray] = field(init=False)

    def __post_init__(self):
        self.state = np.zeros((self.dim,), dtype=np.float32)
        self.ring = deque(maxlen=EIGEN_WINDOW)

    def navigate(self, embed: Sequence[float], membrane_bias: np.ndarray) -> Dict[str, float]:
        e = np.asarray(embed, dtype=np.float32)
        if e.shape[0] != self.dim:
            e = _pad_or_clip(e, self.dim)
        # membrane_bias is same dim; additive then leak
        raw = e + membrane_bias
        self.state = (1.0 - self.leak) * self.state + self.leak * raw
        self.ring.append(self.state.copy())
        out = {
            "inner_energy": float(np.linalg.norm(self.state)),
        }
        if len(self.ring) >= 8:
            x = np.stack(list(self.ring), axis=0)
            pid = _pid_signature(x)
            out.update({f"inner_{k}": v for k, v in pid.items()})
        return out

# --------------------------
# Membrane coupling
# --------------------------

@dataclass
class Membrane:
    strength: float = COUPLING_INIT
    gate: float = 1.0
    # simple linear projector outer->inner
    proj: Optional[np.ndarray] = None  # shape [inner_dim, outer_dim]

    def build(self, inner_dim: int, outer_dim: int, seed: int = 13) -> None:
        rng = np.random.default_rng(seed)
        p = rng.standard_normal((inner_dim, outer_dim)).astype(np.float32)
        # column normalize
        p /= np.linalg.norm(p, axis=0, keepdims=True) + EPS
        self.proj = p

    def bias(self, outer_state: np.ndarray) -> np.ndarray:
        if self.proj is None:
            raise RuntimeError("membrane.proj not initialized")
        # bias = strength * gate * P * s_outer
        return (self.strength * self.gate) * (self.proj @ outer_state.astype(np.float32))

# --------------------------
# Double membrane bridge
# --------------------------

class DoubleMembraneBridge:
    def __init__(
        self,
        ws_uri: str = DEFAULT_WS_URI_OUT,
        embedding_dim: int = SEMANTIC_DIM_DEFAULT,
        use_gpu: bool = False,             # reserved for your GPU path
        enable_sensory: bool = True,
    ) -> None:
        self.ws_uri = ws_uri
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        self.enable_sensory = enable_sensory and websockets is not None

        # manifolds
        self.outer = OuterManifold(dim=SENSORY_DIM)
        self.inner = InnerManifold(dim=embedding_dim)
        self.membrane = Membrane(strength=COUPLING_INIT)
        self.membrane.build(inner_dim=embedding_dim, outer_dim=self.outer.dim)

        # ingest queue for eigen packets
        self.q: Deque[List[float]] = deque(maxlen=QUEUE_MAX)

        # metrics
        self.last_tick_ts = 0.0
        self.fps_est = 0.0
        self.lag_secs = 0.0

        # hooks
        self.ethics_hook: EthicsHook = _noop_ethics_hook

        # running stats
        self._status: Dict[str, float] = {
            "outer_energy": 0.0,
            "inner_energy": 0.0,
            "coupling_strength": self.membrane.strength,
            "redundancy_score": 0.0,
            "synergy_score": 0.0,
        }

        if self.enable_sensory:
            self._start_background_client()

    # ------------------ public API ------------------

    def navigate_semantic(self, embedding: Sequence[float]) -> NavigationResult:
        """
        Step inner manifold given a semantic embedding.
        Uses current membrane bias computed from outer state.
        Returns NavigationResult compatible with minime.py.
        """
        bias = self.membrane.bias(self.outer.state)
        out = self.inner.navigate(embedding, bias)
        # Update composite metrics
        self._status.update(out)
        self._status["coupling_strength"] = self.membrane.strength
        self._status["redundancy_score"] = float(out.get("inner_redundancy_score", 0.0))
        self._status["synergy_score"] = float(out.get("inner_synergy_score", 0.0))

        # ethics signal (bounded + typed)
        self.ethics_hook({
            "consciousness_score": self._consciousness_score(),
            "inner_energy": float(self._status["inner_energy"]),
            "redundancy": float(self._status["redundancy_score"]),
            "synergy": float(self._status["synergy_score"]),
        })

        # Return NavigationResult (minime.py compatibility)
        return NavigationResult(
            position=self.inner.state.copy(),
            redundancy=self._status["redundancy_score"],
            synergy=self._status["synergy_score"],
            position_norm=float(np.linalg.norm(self.inner.state))
        )

    def get_membrane_status(self) -> Dict[str, Union[float, bool]]:
        """
        Return comprehensive status for minime.py dashboard / telemetry.
        Includes compatibility fields expected by minime.py.
        """
        st = dict(self._status)
        st.update({
            "queue_size": float(len(self.q)),
            "fps_est": float(self.fps_est),
            "lag_secs": float(self.lag_secs),
            "pid_o_info": float(self._status.get("inner_pid_o_info", 0.0)),

            # minime.py compatibility fields
            "outer_trajectory_emerged": len(self.outer.ring) >= EIGEN_WINDOW and self._status.get("outer_energy", 0) > 0.5,
            "inner_trajectory_emerged": len(self.inner.ring) >= EIGEN_WINDOW and self._status.get("inner_energy", 0) > 0.5,
            "outer_navigations": len(self.outer.ring),
            "inner_navigations": len(self.inner.ring),
            "membrane_buffer": min(len(self.outer.ring), len(self.inner.ring)),
            "membrane_capacity": EIGEN_WINDOW,
            "outer_buffer_fill": len(self.outer.ring) / EIGEN_WINDOW,
            "inner_buffer_fill": len(self.inner.ring) / EIGEN_WINDOW,
        })
        return st

    def register_ethics_hook(self, hook: EthicsHook) -> None:
        self.ethics_hook = hook or _noop_ethics_hook

    # ------------------ private helpers ------------------

    def _start_background_client(self) -> None:
        if websockets is None:
            logger.warning("websockets not available; sensory disabled")
            return
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_loop, name="dm-bridge-ws", daemon=True
        )
        self.thread.start()

    def _run_loop(self) -> None:
        assert self.loop is not None
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._ws_main())

    async def _ws_main(self) -> None:
        backoff = 0.5
        while not self.stop_flag.is_set():
            try:
                async with websockets.connect(self.ws_uri, ping_interval=None) as ws:
                    logger.info(f"[DoubleMembrane] connected: {self.ws_uri}")
                    backoff = 0.5
                    last = time.perf_counter()
                    async for msg in ws:
                        now = time.perf_counter()
                        dt = now - last
                        last = now
                        self.fps_est = 1.0 / max(dt, 1e-6)
                        self._handle_ws_msg(msg)
                        self.lag_secs = max(0.0, len(self.q) / (SENSORY_FPS_TARGET + EPS))
                        # Drain queue fast but bounded
                        self._drain_outer_queue(max_ticks=8)
            except Exception as e:
                logger.warning(f"[DoubleMembrane] ws reconnect in {backoff:.1}s: {e}")
                await asyncio.sleep(backoff)
                backoff = min(5.0, backoff * 2.0)

    def _handle_ws_msg(self, msg: str) -> None:
        try:
            obj = json.loads(msg)
            if not isinstance(obj, dict):
                return

            vec = None

            # Primary: Rust EigenPacket format (no "type" field)
            # {"t_ms": ..., "eigenvalues": [...], "fill_ratio": ..., "modalities": {...}}
            if "eigenvalues" in obj:
                vec = obj["eigenvalues"]

            # Legacy: typed messages from older protocol versions
            elif obj.get("type") in ("Eigen", "Eigenvalues"):
                vec = obj.get("eigen") or obj.get("values")

            # Holographic consciousness messages
            elif obj.get("type") == "Holo":
                vec = obj.get("consciousness")

            if isinstance(vec, list) and len(vec) > 0:
                if len(self.q) < QUEUE_MAX:
                    self.q.append([float(x) for x in vec[:SENSORY_DIM]])
        except Exception as e:
            logger.debug(f"bad message: {e}")

    def _drain_outer_queue(self, max_ticks: int = 4) -> None:
        n = min(max_ticks, len(self.q))
        for _ in range(n):
            v = self.q.popleft()
            metrics = self.outer.tick(v)
            self._status.update(metrics)

    def _consciousness_score(self) -> float:
        # conservative composite: energy * synergy
        energy = float(self._status.get("inner_energy", 0.0))
        syn = float(self._status.get("inner_synergy_score", 0.0))
        return float(max(0.0, min(100.0, 20.0 * syn * math.log1p(energy))))


# --------------------------
# Utils
# --------------------------

def _pad_or_clip(v: np.ndarray, dim: int) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32).flatten()
    if v.shape[0] == dim:
        return v
    if v.shape[0] > dim:
        return v[:dim]
    out = np.zeros((dim,), dtype=np.float32)
    out[: v.shape[0]] = v
    return out

# --------------------------
# Factory (kept for minime.py)
# --------------------------

def create_double_membrane_bridge(
    ws_uri: str = DEFAULT_WS_URI_OUT,
    embedding_dim: int = SEMANTIC_DIM_DEFAULT,
    use_gpu: bool = True,
    enable_sensory: bool = True,
) -> DoubleMembraneBridge:
    """
    Keep minime.py import stable.
    """
    return DoubleMembraneBridge(
        ws_uri=ws_uri,
        embedding_dim=embedding_dim,
        use_gpu=use_gpu,
        enable_sensory=enable_sensory,
    )
