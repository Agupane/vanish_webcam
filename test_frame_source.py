import threading
import time
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

import frame_source as fs
from test_video_output import run_loop


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def fake_clip(frames=3, fps=25.0):
    """A cv2.VideoCapture-like clip whose frames are filled with their number."""
    position = {"i": 0}
    capture = Mock()
    capture.isOpened.return_value = True
    capture.get.side_effect = lambda prop: fps if prop == cv2.CAP_PROP_FPS else 0.0

    def read():
        if position["i"] >= frames:
            return False, None
        position["i"] += 1
        return True, np.full((4, 6, 3), position["i"], np.uint8)

    def seek(prop, value):
        position["i"] = int(value)
        return True

    capture.read.side_effect = read
    capture.set.side_effect = seek
    return capture


class VideoFileSourceTests(unittest.TestCase):
    def test_plays_at_the_clip_rate_and_loops(self):
        clock = FakeClock()
        source = fs.VideoFileSource("clip.mp4", clock=clock, sleep=clock.sleep, capture=fake_clip(3, 25.0))
        values = []
        for _ in range(5):
            ok, frame = source.read()
            self.assertTrue(ok)
            values.append(int(frame[0, 0, 0]))
        self.assertEqual(values, [1, 2, 3, 1, 2])
        self.assertAlmostEqual(clock.t, 4 / 25.0)

    def test_a_slow_reader_gets_no_burst_of_late_frames(self):
        clock = FakeClock()
        source = fs.VideoFileSource("clip.mp4", clock=clock, sleep=clock.sleep, capture=fake_clip(10, 10.0))
        source.read()
        clock.t = 1.0  # The loop took a whole second.
        source.read()
        before = clock.t
        source.read()
        self.assertAlmostEqual(clock.t - before, 0.1)

    def test_unreadable_file_is_an_error(self):
        capture = Mock()
        capture.isOpened.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Cannot open"):
            fs.VideoFileSource("missing.mp4", capture=capture)

    def test_resolution_and_rate_are_not_changed(self):
        source = fs.VideoFileSource("clip.mp4", capture=fake_clip())
        self.assertFalse(source.set(cv2.CAP_PROP_FPS, 60))


class SlowCamera:
    """Produces numbered frames every `interval` seconds until `count` frames, then fails."""

    def __init__(self, interval=0.01, count=1000):
        self.interval, self.count, self.produced = interval, count, 0
        self.released = threading.Event()

    def read(self):
        if self.produced >= self.count:
            return False, None
        time.sleep(self.interval)
        self.produced += 1
        return True, np.full((2, 2, 3), self.produced % 256, np.uint8)

    def set(self, prop, value):
        return True

    def get(self, prop):
        return 30.0

    def isOpened(self):
        return True

    def release(self):
        self.released.set()


class LatestFrameCaptureTests(unittest.TestCase):
    def test_a_slow_loop_gets_the_newest_frame_not_a_queued_one(self):
        camera = SlowCamera(interval=0.005)
        capture = fs.LatestFrameCapture(camera)
        try:
            capture.read()
            time.sleep(0.1)  # The loop is busy for ~20 camera frames.
            ok, frame = capture.read()
            self.assertTrue(ok)
            self.assertGreaterEqual(int(frame[0, 0, 0]), camera.produced - 1)
            self.assertGreater(capture.dropped, 5)
        finally:
            capture.release()
        self.assertTrue(camera.released.is_set())

    def test_never_returns_the_same_frame_twice(self):
        capture = fs.LatestFrameCapture(SlowCamera(interval=0.002, count=30))
        try:
            seen = []
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                seen.append(int(frame[0, 0, 0]))
            self.assertEqual(seen, sorted(set(seen)))
            self.assertEqual(seen[-1], 30)
        finally:
            capture.release()

    def test_a_camera_that_stops_is_reported(self):
        capture = fs.LatestFrameCapture(SlowCamera(count=0), timeout=1.0)
        try:
            self.assertEqual(capture.read(), (False, None))
        finally:
            capture.release()

    def test_settings_go_to_the_camera(self):
        camera = SlowCamera()
        camera.set = Mock(return_value=True)
        capture = fs.LatestFrameCapture(camera)
        try:
            self.assertTrue(capture.set(cv2.CAP_PROP_FPS, 30))
            camera.set.assert_called_once_with(cv2.CAP_PROP_FPS, 30)
        finally:
            capture.release()


class StageBenchTests(unittest.TestCase):
    def test_percentiles_per_stage_and_cpu(self):
        clock, cpu = FakeClock(), FakeClock()
        bench = fs.StageBench(4, clock=clock, cpu_clock=cpu)
        for index in range(4):
            bench.frame_started()
            with bench.stage("mask"):
                clock.t += 0.010
            if index == 3:
                with bench.stage("mask"):  # Two calls in one frame add up.
                    clock.t += 0.010
            clock.t += 0.010
            cpu.t += 0.010
            done = bench.frame_finished()
        self.assertTrue(done)
        self.assertEqual(len(bench.samples["frame"]), 4)
        np.testing.assert_allclose(bench.samples["mask"], [0.01, 0.01, 0.01, 0.02])
        report = "\n".join(bench.report())
        self.assertIn("4 frames", report)
        self.assertIn("CPU 44%", report)
        self.assertIn("mask", report)

    def test_empty_report(self):
        self.assertIn("No frames", fs.StageBench(3).report()[0])


class BenchLoopTests(unittest.TestCase):
    def test_bench_stops_after_n_frames_without_a_window_and_prints_the_report(self):
        _, shown, camera, _, printed = run_loop(seconds=13.0, bench=30, headless=True)
        self.assertEqual(shown, [])
        self.assertEqual(camera.send.call_count, 30)
        self.assertTrue(any("[Bench] 30 frames" in line for line in printed))
        self.assertTrue(any(line.startswith("[Bench] capture") for line in printed))

    def test_bench_can_start_transformed(self):
        _, _, _, _, printed = run_loop(mode="dragonball", seconds=6.0, bench=50, headless=True,
                                       bench_super_saiyan=True)
        self.assertTrue(any("Super Saiyan!" in line for line in printed))
        self.assertTrue(any(line.startswith("[Bench] super") for line in printed))


if __name__ == "__main__":
    unittest.main()
