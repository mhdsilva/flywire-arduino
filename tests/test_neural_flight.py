"""Behavior contracts for the neural-to-servo readout (no serial hardware)."""

import contextlib
import io
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))

from lif import LIF
from run_brain import (
    DT, STIM_GAIN, WEIGHT_SCALE, SERVO_SPEED_DPS, FlightBehavior, LoomingFilter,
    SENSORS, fake, load_circuit, port_loop, step_ms,
)


def drive(fly, counts, start=0.0, dt=0.02):
    return [fly.update(start + i * dt, dt, spikes)
            for i, spikes in enumerate(counts)]


class ArduinoStream:
    """Serial boundary only: neural simulation and controller stay real."""

    def __init__(self, sensor, values=None, end_error=KeyboardInterrupt):
        self.samples = []
        self.end_error = end_error
        if values is None:
            values = [0 if i < 10 else min(900, (i - 10) * 90) for i in range(100)]
        for raw in values:
            fields = [0, 0, 0, 0]
            fields[SENSORS[sensor]["field"] - 1] = raw
            self.samples.append(("S " + " ".join(map(str, fields)) + "\n").encode())
        self.commands = []
        self.closed = False

    @property
    def in_waiting(self):
        if not self.samples:
            raise self.end_error
        return len(self.samples[0])

    def read(self, n):
        return self.samples.pop(0)

    def write(self, data):
        self.commands.append(data.decode().split())

    def close(self):
        self.closed = True


class NeuralFlightTests(unittest.TestCase):
    def test_silent_network_stays_at_rest(self):
        self.assertEqual(drive(FlightBehavior(), [0] * 100), [90] * 100)

    def test_continued_spikes_sustain_motion_beyond_old_flight_timer(self):
        fly = FlightBehavior()
        angles = drive(fly, [4] * 300)
        self.assertTrue(fly.flying)
        self.assertGreater(max(angles[-50:]) - min(angles[-50:]), 20)
        self.assertEqual(fly.episodes, 1)

    def test_silence_ends_motion_after_the_rate_decays(self):
        fly = FlightBehavior()
        drive(fly, [4] * 25)
        angles = drive(fly, [0] * 200, start=0.5)
        self.assertFalse(fly.flying)
        self.assertEqual(angles[-1], 90)

    def test_rate_changes_amplitude_and_frequency_during_same_episode(self):
        fly = FlightBehavior()
        low = drive(fly, [1] * 200)[-100:]
        f_low = fly.frequency_hz
        high = drive(fly, [4] * 200, start=4.0)[-100:]
        f_high = fly.frequency_hz
        self.assertGreater(max(high) - min(high), max(low) - min(low))
        self.assertGreater(f_high, f_low)      # a stronger response flaps faster
        self.assertEqual(fly.episodes, 1)

    def test_same_spike_train_produces_same_motion(self):
        train = [4] * 10 + [0] * 150 + [2] * 50 + [0] * 150
        self.assertEqual(drive(FlightBehavior(), train),
                         drive(FlightBehavior(), train))

    def test_angle_and_speed_are_limited_including_return_to_rest(self):
        angles = [90] + drive(FlightBehavior(), [20] * 100 + [0] * 400)
        self.assertTrue(all(40 <= a <= 140 for a in angles))
        step_max = SERVO_SPEED_DPS * 0.02 + 1
        self.assertTrue(all(abs(b - a) <= step_max for a, b in zip(angles, angles[1:])))
        self.assertEqual(angles[-1], 90)

    def test_input_is_gated_while_flying_and_just_after_landing(self):
        fly = FlightBehavior()
        drive(fly, [4] * 50)
        self.assertTrue(fly.input_blocked(1.0))   # muted during the flap
        t = 1.0
        while fly.flying and t < 8.0:             # let the rate decay below the off threshold
            fly.update(t, 0.02, 0)
            t += 0.02
        self.assertFalse(fly.flying)
        self.assertTrue(fly.input_blocked(t + 0.1))    # guard just after landing
        self.assertFalse(fly.input_blocked(t + 0.6))   # guard expires

    def test_rate_estimate_uses_time_and_motor_population_size(self):
        # Same 50 Hz/neuron with different windows and population sizes.
        a, b = FlightBehavior(2), FlightBehavior(4)
        drive(a, [2] * 50)
        drive(b, [8] * 25, dt=0.04)
        self.assertAlmostEqual(a.rate_hz, b.rate_hz, places=8)


class CircuitReadoutTests(unittest.TestCase):
    def test_reconnect_discards_old_activity_and_accepts_a_new_startle(self):
        before = ArduinoStream("pot", [0] * 10 + [i * 90 for i in range(1, 9)], OSError)
        after = ArduinoStream("pot", [900] * 50 + [0] * 10
                              + [i * 90 for i in range(1, 11)] + [900] * 40)
        boards = iter([before, after])
        clock = [0.0]

        def now():
            clock[0] += 0.02
            return clock[0]

        def reopen(port, baud):
            clock[0] += 5.0
            return next(boards)

        with patch("run_brain.open_serial", side_effect=reopen), \
             patch("run_brain.time.time", side_effect=now), \
             patch("run_brain.time.sleep"), \
             contextlib.redirect_stdout(io.StringIO()):
            result = port_loop("simulated", 115200, 0)
        self.assertEqual(result, 0)
        self.assertTrue(any(c[4] != "90" for c in before.commands))
        self.assertTrue(before.closed and after.closed)
        self.assertTrue(all(c == ["L", "0", "0", "0", "90"]
                            for c in after.commands[:50]), after.commands[:5])
        self.assertTrue(any(c[3] == "1" and c[4] != "90"
                            for c in after.commands[50:]))

    def test_serial_loop_decodes_each_sensor_and_bounds_led_and_servo(self):
        for sensor in ("pot", "ldr"):
            with self.subTest(sensor=sensor):
                board = ArduinoStream(sensor)
                times = iter(i * 0.02 for i in range(200))
                with patch("run_brain.open_serial", return_value=board), \
                     patch("run_brain.time.time", side_effect=lambda: next(times)), \
                     contextlib.redirect_stdout(io.StringIO()):
                    result = port_loop("simulated", 115200, 0, sensor)
                self.assertEqual(result, 0)
                self.assertTrue(board.closed)
                self.assertEqual(board.commands[-1], ["L", "0", "0", "0", "90"])
                # the motor LED stays lit across the flight (many windows)
                self.assertGreater(sum(c[3] == "1" for c in board.commands), 5)
                # skip the final shutdown command, which snaps straight to rest
                angles = [90] + [int(c[4]) for c in board.commands[:-1]]
                self.assertTrue(all(40 <= a <= 140 for a in angles))
                step_max = SERVO_SPEED_DPS * 0.02 + 1
                self.assertTrue(all(abs(b - a) <= step_max for a, b in zip(angles, angles[1:])))

    def test_fake_loop_runs_one_bounded_flight_then_lands(self):
        # The sensor is muted during the flap (bench noise), so the episode is
        # driven purely by the readout decay: one startle, one bounded flight.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = fake(6.0)
        text = output.getvalue()
        summary = re.search(r"\((\d+) spikes\) -- (\d+) flights", text)
        self.assertEqual(result, 0)
        self.assertIsNotNone(summary)
        self.assertEqual(int(summary.group(2)), 1)
        self.assertGreater(int(summary.group(1)), 0)
        last_log = [ln for ln in text.splitlines() if "flight=" in ln][-1]
        self.assertIn("flight=0", last_log)  # back on the ground

    def test_real_circuit_follows_sensor_rise_then_returns_to_rest(self):
        W, roles, _ = load_circuit()
        for sensor in ("pot", "ldr"):
            with self.subTest(sensor=sensor):
                cfg = SENSORS[sensor]
                filt = LoomingFilter(direction=cfg["direction"],
                                     level_w=cfg["level_w"], dead=cfg["dead"])
                net = LIF(W, roles, weight_scale=WEIGHT_SCALE, dt=DT)
                fly = FlightBehavior(int((roles == "motor").sum()))
                ext = np.zeros(net.n)
                angles, counts, stimuli = [], [], []
                for i in range(260):
                    now = i * 0.02
                    # Rest, then a 200 ms rise, then hold steady.
                    raw = 0 if i < 10 else min(900, (i - 10) * 90)
                    stim = filt.update(raw, 0.02)
                    if fly.input_blocked(now):
                        stim = 0.0
                    ext[roles == "sensory"] = stim * STIM_GAIN
                    spikes = step_ms(net, ext, 20)
                    motor_spikes = int(spikes[roles == "motor"].sum())
                    angles.append(fly.update(now, 0.02, motor_spikes))
                    counts.append(motor_spikes)
                    stimuli.append(stim)
                self.assertEqual(angles[:10], [90] * 10)
                self.assertGreater(sum(counts), 10)
                self.assertGreaterEqual(sum(s > 0.5 for s in stimuli), 1)
                self.assertGreater(max(angles) - min(angles), 10)
                self.assertEqual(angles[-20:], [90] * 20)
                self.assertEqual(fly.episodes, 1)


if __name__ == "__main__":
    unittest.main()
