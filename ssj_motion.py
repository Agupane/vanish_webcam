"""Smooth, lively motion for the imported Super Saiyan hair.

The face landmarks arrive about 12.5 times a second while the video runs at 30 FPS, so a hair fitted to the latest
detection holds still for two or three frames and then jumps. `HeadTracker` turns the detections into a face for
every frame (filtered and predicted), `HairDynamics` adds secondary motion (the hair lags behind the head, overshoots
once, pops up on the transformation) and `hair_warp_maps` bends the tips while the roots stay on the head, with a
slow ki flutter. Pure NumPy/OpenCV with an injected clock, so everything is testable without a camera.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

import cv2
import numpy as np

# Head tracker: a speed-adaptive alpha-beta filter on (x, y, angle, log scale) of the face, one step per detection.
# Unlike a plain low-pass filter it has no lag on steady motion, so the hair does not trail behind a turning head.
TRACK_ALPHA_MIN = 0.4  # Position gain for a still head: smooths landmark jitter (to ~55 % on synthetic noise).
TRACK_ALPHA_MAX = 0.85  # Position gain for a fast head: follows it closely.
TRACK_ALPHA_SPEED = 0.6  # Gain added per face width per second of head speed (settles a sudden stop in ~0.4 s).
MAX_EXTRAPOLATION_SECONDS = 0.15  # Prediction horizon between detections.
PREDICTION_DECAY = 4.0  # 1/s: the predicted velocity fades, so a sudden stop overshoots only a little.
REACQUIRE_DISTANCE = 0.5  # Face widths: a bigger jump between detections is a new face, not motion.
TRACK_LOST_SECONDS = 1.0  # Without detections for this long (fists hiding the face) the tracked face is dropped.

# Secondary motion: a damped spring per axis pulled towards a lag proportional to the head's velocity.
SWAY_HZ = 2.0
SWAY_DAMPING = 0.35  # Under-damped: one visible overshoot when the head stops.
SWAY_LAG_SECONDS = 0.04  # Tip offset target = -velocity * this (face widths).
MAX_TIP_LAG = 0.06  # Face widths.
ROLL_LAG_SECONDS = 0.05
MAX_ROLL_LAG = math.radians(6.0)
POWER_UP_KICK = 1.2  # Face widths per second, upwards, when the transformation flashes.
SPRING_STEP = 1.0 / 120.0  # Fixed substeps: the same motion at 20, 30 or 60 FPS.

# Ki flutter: a slow wave travelling from the roots to the tips.
FLUTTER_AMPLITUDE = 0.012  # Face widths.
FLUTTER_HZ = 1.6
FLUTTER_WAVELENGTH = 0.8  # In root-to-tip weight units.
GRID_STEP = 16  # Pixels between nodes of the warp grid (the maps are interpolated in between).


def fit_similarity(src: np.ndarray, dst: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray | None:
    """Weighted least-squares similarity (rotation, uniform scale, translation) mapping src to dst, as 2x3.

    Closed form (Umeyama in 2D): deterministic, unlike LMEDS, whose choice of inliers flips with a few pixels of
    landmark noise and makes the hair jump in scale or angle.
    """
    src = np.asarray(src, np.float64)
    dst = np.asarray(dst, np.float64)
    w = np.ones(len(src)) if weights is None else np.asarray(weights, np.float64)
    if w.sum() <= 0 or not (np.isfinite(src).all() and np.isfinite(dst).all()):
        return None
    w = w / w.sum()
    mean_src, mean_dst = w @ src, w @ dst
    s, d = src - mean_src, dst - mean_dst
    variance = float(w @ (s ** 2).sum(axis=1))
    if variance < 1e-9:
        return None
    a = float(w @ (s[:, 0] * d[:, 0] + s[:, 1] * d[:, 1])) / variance
    b = float(w @ (s[:, 0] * d[:, 1] - s[:, 1] * d[:, 0])) / variance
    linear = np.array(((a, -b), (b, a)))
    return np.hstack((linear, (mean_dst - linear @ mean_src)[:, None])).astype(np.float32)


def compose(outer: np.ndarray, inner: np.ndarray) -> np.ndarray:
    """2x3 affine `outer ∘ inner`."""
    return np.hstack((outer[:, :2] @ inner[:, :2], (outer[:, :2] @ inner[:, 2] + outer[:, 2])[:, None]))


def invert(matrix: np.ndarray) -> np.ndarray:
    return cv2.invertAffineTransform(np.asarray(matrix, np.float64)).astype(np.float32)


def apply(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
    return (np.asarray(points, np.float32) @ matrix[:, :2].T + matrix[:, 2]).astype(np.float32)


def _params(matrix: np.ndarray, center: np.ndarray) -> np.ndarray:
    """(x, y, angle, log scale) of a similarity, with (x, y) where it sends `center`.

    Measured at the face rather than at the image corner: there, a tiny angle error would move (x, y) a lot.
    """
    a, b = float(matrix[0, 0]), float(matrix[1, 0])
    x, y = apply(matrix, np.asarray(center, np.float32)[None])[0]
    return np.array((x, y, math.atan2(b, a), math.log(max(1e-9, math.hypot(a, b)))))


def _matrix(params: np.ndarray, center: np.ndarray) -> np.ndarray:
    x, y, angle, log_scale = (float(value) for value in params)
    scale = math.exp(log_scale)
    a, b = scale * math.cos(angle), scale * math.sin(angle)
    cx, cy = float(center[0]), float(center[1])
    return np.array(((a, -b, x - (a * cx - b * cy)), (b, a, y - (b * cx + a * cy))), np.float32)


class HeadTracker:
    """A face for every frame from detections that arrive at a lower, uneven rate.

    Each detection is fitted (weighted similarity on the anchor points) against the first one, the four pose
    parameters go through an alpha-beta filter, and every frame the pose is predicted forward with a decaying
    velocity. The output is the latest detected face moved rigidly to the predicted pose: the expression comes from
    the detection, the motion is updated every frame. Anchor indices, weights and the yaw function are injected so
    this module does not depend on the face model.
    """

    def __init__(self, anchors: Sequence[int], weights: Sequence[float],
                 yaw: Callable[[np.ndarray], float] | None = None,
                 width_points: tuple[int, int] | None = None):
        self.anchors = list(anchors)
        self.weights = np.asarray(weights, np.float32)
        self.yaw_of = yaw
        self.width_points = width_points
        self.reset()

    def reset(self) -> None:
        self.reference: np.ndarray | None = None
        self.reference_width = 1.0
        self.face: np.ndarray | None = None  # Latest detected points.
        self.detected: np.ndarray | None = None  # Raw fit of that detection.
        self.pose = np.zeros(4)
        self.velocity = np.zeros(4)
        self.detected_at: float | None = None
        self.yaw = 0.0

    def _width(self, face: np.ndarray) -> float:
        if self.width_points is not None:
            left, right = self.width_points
            return max(1.0, float(np.linalg.norm(face[right] - face[left])))
        anchors = face[self.anchors]
        return max(1.0, float(np.ptp(anchors[:, 0])))

    def update(self, t: float, detection: np.ndarray | None = None,
               detected_at: float | None = None) -> np.ndarray | None:
        """Feed a new detection (if any) and return the face for time `t`, or None when lost."""
        if detection is not None:
            self._observe(detection, t if detected_at is None else detected_at)
        return self.face_at(t)

    def _observe(self, face: np.ndarray, t: float) -> None:
        face = np.asarray(face, np.float32)
        if not np.isfinite(face).all():
            return
        if self.reference is None:
            self.reference = face[self.anchors].copy()
            self.reference_width = self._width(face)
            self.center = (self.weights[:, None] * self.reference).sum(axis=0) / self.weights.sum()
        fit = fit_similarity(self.reference, face[self.anchors], self.weights)
        if fit is None:
            return
        measured = _params(fit, self.center)
        lost = self.detected_at is None or t - self.detected_at > TRACK_LOST_SECONDS
        if not lost:
            dt = max(1e-3, t - self.detected_at)
            predicted = self.pose + self.velocity * dt
            measured[2] = predicted[2] + math.remainder(measured[2] - predicted[2], 2 * math.pi)
            residual = measured - predicted
            width = self.reference_width * math.exp(predicted[3])
            if math.hypot(residual[0], residual[1]) > REACQUIRE_DISTANCE * width:
                lost = True
        if lost:
            self.pose, self.velocity = measured, np.zeros(4)
            yaw = self.yaw_of(face) if self.yaw_of else 0.0
        else:
            width = self.reference_width * math.exp(predicted[3])
            speed = math.hypot(self.velocity[0], self.velocity[1]) / width
            alpha = min(TRACK_ALPHA_MAX, TRACK_ALPHA_MIN + TRACK_ALPHA_SPEED * speed)
            beta = alpha * alpha / (2.0 - alpha)  # Critically damped alpha-beta pair.
            self.pose = predicted + alpha * residual
            self.velocity = self.velocity + (beta / dt) * residual
            yaw = self.yaw + alpha * ((self.yaw_of(face) if self.yaw_of else 0.0) - self.yaw)
        self.face, self.detected, self.detected_at, self.yaw = face, fit, t, yaw

    def matrix_at(self, t: float) -> np.ndarray | None:
        """Predicted similarity from the reference anchors to the face at time `t`."""
        if self.detected_at is None or t - self.detected_at > TRACK_LOST_SECONDS:
            return None
        ahead = min(max(0.0, t - self.detected_at), MAX_EXTRAPOLATION_SECONDS)
        travel = (1.0 - math.exp(-PREDICTION_DECAY * ahead)) / PREDICTION_DECAY
        return _matrix(self.pose + self.velocity * travel, self.center)

    def face_at(self, t: float) -> np.ndarray | None:
        matrix = self.matrix_at(t)
        if matrix is None or self.face is None:
            return None
        return apply(compose(matrix, invert(self.detected)), self.face)


@dataclass
class HairMotion:
    """What the warp needs this frame: sway offset (face widths), roll (radians) and flutter amplitude."""
    offset: np.ndarray
    roll: float = 0.0
    flutter: float = 0.0  # Face widths.


class HairDynamics:
    """Hair that lags behind the head, overshoots once when it stops and pops up on the transformation.

    Driven by the tracked head (centre, roll angle and face width per frame). Offsets are in face widths and the
    roll in radians; both are clamped. Fixed substeps make the motion independent of the frame rate.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.offset = np.zeros(2)
        self.offset_speed = np.zeros(2)
        self.roll = 0.0
        self.roll_speed = 0.0
        self._last: tuple[float, np.ndarray, float] | None = None

    def kick(self) -> None:
        self.offset_speed[1] -= POWER_UP_KICK  # Up in the image.

    def motion(self, flutter: float = 1.0) -> HairMotion:
        """The current state for the warp; `flutter` scales the ki flutter (the aura level)."""
        return HairMotion(self.offset.copy(), self.roll, FLUTTER_AMPLITUDE * max(0.0, flutter))

    def step(self, t: float, center: np.ndarray, angle: float, width: float) -> None:
        center = np.asarray(center, np.float64)
        if self._last is None or t <= self._last[0]:
            self._last = (t, center, angle)
            return
        last_t, last_center, last_angle = self._last
        dt = min(0.1, t - last_t)
        velocity = (center - last_center) / max(width, 1.0) / (t - last_t)
        spin = math.remainder(angle - last_angle, 2 * math.pi) / (t - last_t)
        self._last = (t, center, angle)
        target = np.clip(-velocity * SWAY_LAG_SECONDS, -MAX_TIP_LAG, MAX_TIP_LAG)
        roll_target = float(np.clip(-spin * ROLL_LAG_SECONDS, -MAX_ROLL_LAG, MAX_ROLL_LAG))
        omega = 2 * math.pi * SWAY_HZ
        steps = max(1, int(math.ceil(dt / SPRING_STEP)))
        h = dt / steps
        for _ in range(steps):  # Semi-implicit Euler.
            accel = -omega * omega * (self.offset - target) - 2 * SWAY_DAMPING * omega * self.offset_speed
            self.offset_speed = self.offset_speed + accel * h
            self.offset = self.offset + self.offset_speed * h
            roll_accel = -omega * omega * (self.roll - roll_target) - 2 * SWAY_DAMPING * omega * self.roll_speed
            self.roll_speed += roll_accel * h
            self.roll += self.roll_speed * h
        self.offset = np.clip(self.offset, -2 * MAX_TIP_LAG, 2 * MAX_TIP_LAG)  # Room for the kick's overshoot.
        self.roll = float(np.clip(self.roll, -MAX_ROLL_LAG, MAX_ROLL_LAG))


def root_weights(alpha: np.ndarray, face_hull: np.ndarray, root_band: float) -> np.ndarray:
    """0 at the roots (near the face) rising to 1 at the tips, per pixel of a hair cut-out.

    `face_hull` is the face outline in the cut-out's coordinates and `root_band` the distance (pixels) over which
    the hair goes from fixed to free.
    """
    outside = np.full(alpha.shape[:2], 255, np.uint8)
    cv2.fillConvexPoly(outside, cv2.convexHull(np.round(face_hull).astype(np.int32)), 0)
    distance = cv2.distanceTransform(outside, cv2.DIST_L2, 3)
    return (np.clip(distance / max(1.0, root_band), 0.0, 1.0) ** 1.5).astype(np.float32)


def hair_warp_maps(matrix: np.ndarray, weights: np.ndarray, box: tuple[int, int, int, int], pivot: np.ndarray,
                   offset: np.ndarray, roll: float, flutter: float, t: float) -> tuple[np.ndarray, np.ndarray]:
    """Backward maps for `cv2.remap`: the cut-out placed by `matrix`, tips moved, roots fixed.

    For each output pixel p (frame coordinates in `box`) the source is A⁻¹(p − w·D(p)), where w is the root weight
    and D = sway offset (pixels) + roll about `pivot` + flutter (pixels). The rigid part A⁻¹(p) is exact per pixel;
    the displacement, small and smooth, is computed on a coarse grid and interpolated.
    """
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    inverse = invert(matrix)
    px = np.arange(x0, x1, dtype=np.float32)[None, :]
    py = np.arange(y0, y1, dtype=np.float32)[:, None]
    base_x = inverse[0, 0] * px + inverse[0, 1] * py + inverse[0, 2]
    base_y = inverse[1, 0] * px + inverse[1, 1] * py + inverse[1, 2]
    xs = np.linspace(0, width - 1, max(2, int(math.ceil(width / GRID_STEP)) + 1), dtype=np.float32)
    ys = np.linspace(0, height - 1, max(2, int(math.ceil(height / GRID_STEP)) + 1), dtype=np.float32)
    gx, gy = np.meshgrid(xs + x0, ys + y0)
    frame = np.stack((gx, gy), axis=-1)
    source = frame @ inverse[:, :2].T + inverse[:, 2]
    w = cv2.remap(weights, source[..., 0].astype(np.float32), source[..., 1].astype(np.float32),
                  cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[..., None]
    relative = frame - np.asarray(pivot, np.float32)
    cos_r, sin_r = math.cos(roll), math.sin(roll)
    rotated = np.stack((relative[..., 0] * cos_r - relative[..., 1] * sin_r,
                        relative[..., 0] * sin_r + relative[..., 1] * cos_r), axis=-1)
    move = w * (np.asarray(offset, np.float32) + (rotated - relative))
    if flutter:
        phase = 2 * math.pi * (FLUTTER_HZ * t - w[..., 0] / FLUTTER_WAVELENGTH) + 0.015 * gx
        wave = np.sin(phase)
        move = move + (w * w) * flutter * np.stack((wave, -0.5 * np.abs(wave)), axis=-1)
    shift = (move @ inverse[:, :2].T).astype(np.float32)  # The displacement in cut-out pixels.
    size = (width, height)
    map_x = base_x - cv2.resize(np.ascontiguousarray(shift[..., 0]), size, interpolation=cv2.INTER_LINEAR)
    map_y = base_y - cv2.resize(np.ascontiguousarray(shift[..., 1]), size, interpolation=cv2.INTER_LINEAR)
    return map_x.astype(np.float32), map_y.astype(np.float32)
