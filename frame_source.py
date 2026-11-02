"""Frame sources and timing for the main loop: a recorded clip, the capture thread and the benchmark.

- `VideoFileSource` plays a clip like a webcam (paced to its FPS, looping), for `--input-video`. Frames are only read.
- `LatestFrameCapture` reads the camera in a thread and keeps only the newest frame: when a frame takes longer than
  the camera interval, the loop gets the current image instead of one that waited in the driver's queue.
- `StageBench` collects per-stage times for `--bench N` and prints p50/p95 and the process CPU use.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import cv2
import numpy as np

# Waiting longer than this for the first/next camera frame means the camera is gone (some take ~2 s to start).
FRAME_TIMEOUT_SECONDS = 5.0


class VideoFileSource:
    """A clip read like a webcam: one frame per 1/fps (when `paced`), from the start again at the end."""

    def __init__(self, path: str | Path, paced: bool = True, clock=time.perf_counter, sleep=time.sleep,
                 capture=None):
        self.path = str(path)
        self.capture = capture if capture is not None else cv2.VideoCapture(self.path)
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open the video {self.path}.")
        fps = self.capture.get(cv2.CAP_PROP_FPS) or 0.0
        self.interval = 1.0 / fps if 1.0 <= fps <= 240.0 else 1.0 / 30.0
        self.paced = paced
        self.clock, self.sleep = clock, sleep
        self.next_at: float | None = None
        self.frames = 0

    def read(self):
        if self.paced:
            now = self.clock()
            if self.next_at is not None and now < self.next_at:
                self.sleep(self.next_at - now)
            # A slow consumer does not get a burst of catch-up frames: like a camera, time just moves on.
            self.next_at = max(now, self.next_at or now) + self.interval
        ok, frame = self.capture.read()
        if not ok and self.frames:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        if ok:
            self.frames += 1
        return ok, frame

    def set(self, prop, value) -> bool:
        return False  # The clip keeps its own size and rate.

    def get(self, prop) -> float:
        return self.capture.get(prop)

    def isOpened(self) -> bool:  # noqa: N802 (cv2.VideoCapture API)
        return self.capture.isOpened()

    def release(self) -> None:
        self.capture.release()


class LatestFrameCapture:
    """Reads `source` in a background thread; `read()` returns the newest frame the loop has not seen yet."""

    def __init__(self, source, timeout: float = FRAME_TIMEOUT_SECONDS):
        self.source = source
        self.timeout = timeout
        self._condition = threading.Condition()
        self._frame: np.ndarray | None = None
        self._sequence = 0
        self._returned = 0
        self._failed = False
        self._running = True
        self.dropped = 0  # Frames replaced before the loop asked for them.
        self._thread = threading.Thread(target=self._run, name="VanishCam capture", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._running:
            try:
                ok, frame = self.source.read()
            except Exception:  # noqa: BLE001 - reported to the loop as a camera that stopped.
                ok, frame = False, None
            with self._condition:
                if not ok:
                    self._failed = True
                    self._condition.notify_all()
                    return
                if self._sequence > self._returned:
                    self.dropped += 1
                self._frame = frame
                self._sequence += 1
                self._condition.notify_all()

    def read(self):
        with self._condition:
            self._condition.wait_for(lambda: self._sequence > self._returned or self._failed, self.timeout)
            if self._sequence > self._returned:
                self._returned = self._sequence
                return True, self._frame
            return False, None

    def set(self, prop, value) -> bool:
        return self.source.set(prop, value)

    def get(self, prop) -> float:
        return self.source.get(prop)

    def isOpened(self) -> bool:  # noqa: N802 (cv2.VideoCapture API)
        return self.source.isOpened()

    def release(self) -> None:
        self._running = False
        # The reader may be blocked in source.read(); it returns within one camera frame.
        self._thread.join(timeout=1.0)
        self.source.release()


class BackgroundCall:
    """One call at a time in a worker thread, so the loop never waits for a model (MediaPipe releases the GIL).

    `submit` starts a call only when the previous one is done (a MediaPipe VIDEO task must not run twice at once and
    needs increasing timestamps); `take` returns each finished result once. With `threaded=False` the call runs
    inside `submit`, which keeps the loop deterministic for tests and `--no-async-inference`.
    """

    def __init__(self, name: str, threaded: bool = True):
        self.name = name
        self.threaded = threaded
        self._thread: threading.Thread | None = None
        self._done = False
        self._value = None
        self._error: BaseException | None = None

    @property
    def idle(self) -> bool:
        return self._thread is None or not self._thread.is_alive()

    def submit(self, function, *args) -> bool:
        if not self.idle:
            return False

        def call() -> None:
            try:
                self._value, self._error = function(*args), None
            except BaseException as error:  # noqa: BLE001 - raised again in the loop by take().
                self._value, self._error = None, error
            self._done = True

        self._done = False
        if self.threaded:
            self._thread = threading.Thread(target=call, name=f"VanishCam {self.name}", daemon=True)
            self._thread.start()
        else:
            call()
        return True

    def take(self, wait: bool = False):
        """(True, value) once per finished call, else (False, None). `wait` blocks for a call in progress."""
        if wait and self._thread is not None:
            self._thread.join()
        if not self._done or not self.idle:
            return False, None
        self._done = False
        if self._error is not None:
            error, self._error = self._error, None
            raise error
        return True, self._value

    def close(self) -> None:
        """Wait for a call in progress: the models it uses are closed right after."""
        if self._thread is not None:
            self._thread.join(timeout=2.0)


class StageBench:
    """Per-frame stage timings. `stage(name)` adds the wall time of a block to the current frame."""

    def __init__(self, frames: int, clock=time.perf_counter, cpu_clock=time.process_time):
        self.frames = frames
        self.clock, self.cpu_clock = clock, cpu_clock
        self.samples: dict[str, list[float]] = defaultdict(list)
        self._current: dict[str, float] = defaultdict(float)
        self._frame_started: float | None = None
        self._started = self._cpu_started = None
        self.done = 0

    @contextmanager
    def stage(self, name: str):
        started = self.clock()
        try:
            yield
        finally:
            self._current[name] += self.clock() - started

    def frame_started(self) -> None:
        now = self.clock()
        if self._started is None:
            self._started, self._cpu_started = now, self.cpu_clock()
        self._frame_started = now

    def frame_finished(self) -> bool:
        """Record the frame; True once `frames` frames are measured."""
        if self._frame_started is None:
            return False
        self.samples["frame"].append(self.clock() - self._frame_started)
        for name, seconds in self._current.items():
            self.samples[name].append(seconds)
        self._current.clear()
        self._frame_started = None
        self.done += 1
        return self.done >= self.frames

    def report(self) -> list[str]:
        if not self.done:
            return ["[Bench] No frames measured."]
        wall = self.clock() - self._started
        cpu = self.cpu_clock() - self._cpu_started
        lines = [f"[Bench] {self.done} frames in {wall:.1f} s: {self.done / max(wall, 1e-9):.1f} FPS, "
                 f"process CPU {100.0 * cpu / max(wall, 1e-9):.0f}% of one core."]
        lines.append(f"[Bench] {'stage':<10} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8} {'frames':>7}")
        order = ["frame"] + sorted(name for name in self.samples if name != "frame")
        for name in order:
            values = np.array(self.samples[name]) * 1000.0
            lines.append(f"[Bench] {name:<10} {np.percentile(values, 50):8.1f} {np.percentile(values, 95):8.1f} "
                         f"{values.max():8.1f} {len(values):7d}")
        return lines


@contextmanager
def no_stage(name: str):
    yield
