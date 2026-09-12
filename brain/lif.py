#!/usr/bin/env python3
"""Sparse LIF (leaky integrate-and-fire) simulator in numpy/scipy.

Model
-----
Each neuron i has:
    tau_m  dV_i/dt = (V_rest - V_i) + R_m * (I_syn_i + I_ext_i)
    tau_syn dI_syn_i/dt = -I_syn_i + sum_j W_ij * spike_j

with R_m = 1 (arbitrary units). Discretized with explicit Euler.

Parameters (default, documented):
    dt        = 0.1 ms
    tau_m     = 20 ms
    tau_syn   = 5 ms
    V_rest    = 0
    V_thresh  = 1
    V_reset   = 0
    refractory= 2 ms

Stability: the saved weights are raw syn_count (they can be in the hundreds).
weight_scale (default 1e-4) rescales the matrix so that the synaptic input
stays on the order of the threshold. Without it the network saturates immediately.

Usage
---
    net = LIF(weights_csr, roles)
    spikes = net.step(currents)          # currents: float vector per neuron
    hz = LIF.role_rates(spike_matrix, roles, net.dt)
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp


class LIF:
    def __init__(
        self,
        weights,
        roles,
        weight_scale: float = 1e-4,
        dt: float = 0.1,
        tau_m: float = 20.0,
        tau_syn: float = 5.0,
        v_rest: float = 0.0,
        v_thresh: float = 1.0,
        v_reset: float = 0.0,
        refractory: float = 2.0,
    ):
        self.W = sp.csr_matrix(weights, dtype=np.float64) * float(weight_scale)
        self.roles = np.asarray(roles)
        self.n = self.W.shape[0]
        self.weight_scale = float(weight_scale)

        self.dt = float(dt)
        self.tau_m = float(tau_m)
        self.tau_syn = float(tau_syn)
        self.v_rest = float(v_rest)
        self.v_thresh = float(v_thresh)
        self.v_reset = float(v_reset)
        self.refractory = float(refractory)
        self.n_refr = int(round(self.refractory / self.dt))

        self.V = np.full(self.n, self.v_rest, dtype=np.float64)
        self.I = np.zeros(self.n, dtype=np.float64)
        self.refr = np.zeros(self.n, dtype=np.int64)
        self.s = np.zeros(self.n, dtype=bool)

    def reset(self) -> None:
        self.V.fill(self.v_rest)
        self.I.fill(0.0)
        self.refr.fill(0)
        self.s.fill(False)

    def step(self, currents=None, dt: float | None = None) -> np.ndarray:
        """Advance one step. currents: external current per neuron (optional)."""
        dt = self.dt if dt is None else float(dt)
        if currents is None:
            currents = 0.0

        # Synapse: decay the current and receive the spikes from the previous step.
        self.I *= np.exp(-dt / self.tau_syn)
        self.I += self.W.dot(self.s.astype(np.float64))

        # Membrane: integrate only those not in the refractory period.
        active = self.refr <= 0
        dv = (dt / self.tau_m) * (self.v_rest - self.V) + dt * (self.I + currents)
        self.V[active] += dv[active]
        self.V[~active] = self.v_reset

        self.refr = np.maximum(self.refr - 1, 0)

        spikes = self.V >= self.v_thresh
        self.V[spikes] = self.v_reset
        self.refr[spikes] = self.n_refr
        self.s = spikes
        return spikes

    @staticmethod
    def role_rates(spike_matrix: np.ndarray, roles: np.ndarray, dt: float) -> dict:
        """Average rate (Hz) per role for a matrix (steps x neurons)."""
        spike_matrix = np.asarray(spike_matrix)
        steps = spike_matrix.shape[0]
        window_s = steps * dt / 1000.0
        if window_s <= 0:
            return {}
        hz = spike_matrix.sum(axis=0) / window_s
        return {
            str(r): float(hz[np.asarray(roles) == r].mean())
            for r in np.unique(roles)
        }

    @staticmethod
    def firing_counts(spike_matrix: np.ndarray) -> np.ndarray:
        return np.asarray(spike_matrix).sum(axis=0)
