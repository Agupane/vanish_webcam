"""Super Saiyan transformation: charge-ki pose, yellow aura and sounds."""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


CHARGE_SECONDS = 1.5
FLASH_SECONDS = 0.45
POWER_DOWN_SECONDS = 0.6
AURA_SCALE = 0.5
AURA_RADIUS = 22.0  # At half resolution.

# Face Landmarker.
NOSE, CHIN, FOREHEAD_TOP = 1, 152, 10
FACE_LEFT, FACE_RIGHT = 234, 454

# BGR: from the orange edge to the almost-white core.
AURA_STOPS = ((0.0, (0, 0, 0)), (0.35, (0, 140, 255)), (0.7, (0, 215, 255)), (1.0, (200, 255, 255)))


def _gradient_lut(stops) -> np.ndarray:
    positions = np.array([position for position, _ in stops])
    colors = np.array([color for _, color in stops], dtype=np.float32)
    x = np.linspace(0.0, 1.0, 256)
    return np.stack([np.interp(x, positions, colors[:, channel]) for channel in range(3)], axis=1)


AURA_LUT = _gradient_lut(AURA_STOPS).astype(np.float32)


# ---------- gesture ----------

def _points(landmarks, width: int, height: int) -> np.ndarray:
    return np.array([(p.x * width, p.y * height) for p in landmarks], dtype=np.float32)


def hand_tension(hand: np.ndarray) -> int:
    """How many fingers (index..pinky) are curled or bent towards the palm."""
    curled = 0
    for base in (5, 9, 13, 17):
        finger = hand[base:base + 4]
        length = float(np.linalg.norm(np.diff(finger, axis=0), axis=1).sum())
        if length < 1e-3:
            curled += 1
            continue
        ratio = float(np.linalg.norm(finger[3] - finger[0])) / length
        reach = float(np.linalg.norm(finger[3] - hand[0]))
        knuckle = float(np.linalg.norm(finger[0] - hand[0]))
        if ratio < 0.75 or reach < knuckle * 1.15:
            curled += 1
    return curled


def charge_pose(hands: list[np.ndarray], face: np.ndarray, width: int, height: int) -> bool:
    """Two clenched fists in front of the face, one on each side of the nose."""
    if len(hands) < 2 or face.shape[0] <= max(FACE_RIGHT, CHIN):
        return False
    scale = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    if scale < 20.0:
        return False
    nose, chin = face[NOSE], face[CHIN]
    # The fists may sit anywhere from the forehead to just below the chin, and
    # a little wider than the face: that is how the charge pose looks in practice.
    top, bottom = nose[1] - 1.2 * scale, chin[1] + 1.0 * scale
    left, right = nose[0] - 1.5 * scale, nose[0] + 1.5 * scale
    centers = []
    for hand in hands[:2]:
        if hand.shape != (21, 2) or not np.isfinite(hand).all():
            return False
        # Two curled fingers are enough: a fist seen from the front hides the
        # rest of the hand and MediaPipe may not see all four fingertips.
        if hand_tension(hand) < 2:
            return False
        size = float(np.linalg.norm(hand[0] - hand[9]))
        if not 0.2 * scale < size < 1.4 * scale:
            return False
        center = hand[[5, 9, 13, 17]].mean(axis=0)
        if not (top <= center[1] <= bottom and left <= center[0] <= right):
            return False
        centers.append(center)
    first, second = centers
    return ((first[0] - nose[0]) * (second[0] - nose[0]) <= 0
            and abs(first[1] - second[1]) < 1.0 * scale)


def face_points(faces, width: int, height: int) -> np.ndarray | None:
    return _points(faces[0], width, height) if faces else None


def charging_from_landmarks(hands, faces, width: int, height: int) -> bool:
    face = face_points(faces, width, height)
    if face is None:
        return False
    points = [_points(hand, width, height) for hand in hands if len(hand) == 21]
    return charge_pose(points, face, width, height)


# ---------- aura ----------

class AuraRenderer:
    """Yellow aura with upward flames, pulse and sparks, at half resolution."""

    def __init__(self, seed: int = 77, sparks: int = 30):
        rng = np.random.default_rng(seed)
        coarse = rng.random((16, 64), dtype=np.float32)
        fine = rng.random((64, 128), dtype=np.float32)
        # Taller than wide: vertical tongues of fire.
        noise = (cv2.resize(coarse, (256, 256), interpolation=cv2.INTER_CUBIC) * 0.65
                 + cv2.resize(fine, (256, 256), interpolation=cv2.INTER_CUBIC) * 0.35)
        self.noise = np.clip(noise, 0.0, 1.0)
        self.sparks = sparks
        self.seed = seed
        kernel = np.zeros((26, 1), dtype=np.float32)
        kernel[:, 0] = np.linspace(1.0, 0.2, 26)
        self.upward = kernel / kernel.sum()

    def render(self, frame: np.ndarray, mask: np.ndarray | None, intensity: float, t: float,
               radius_scale: float = 1.0) -> np.ndarray:
        if mask is None or intensity <= 0.0:
            return frame
        x, y, w, h = cv2.boundingRect((mask > 0.3).astype(np.uint8))
        if w <= 0 or h <= 0:
            return frame
        height, width = mask.shape
        left, top = max(0, x - 70), max(0, y - 170)
        right, bottom = min(width, x + w + 70), min(height, y + h + 15)
        area = np.s_[top:bottom, left:right]
        small_size = (max(2, int((right - left) * AURA_SCALE)), max(2, int((bottom - top) * AURA_SCALE)))
        person = cv2.resize(mask[area], small_size, interpolation=cv2.INTER_LINEAR)

        outside = (person < 0.5).astype(np.uint8)
        distance = cv2.distanceTransform(outside, cv2.DIST_L2, 3)
        pulse = 1.0 + 0.15 * math.sin(2 * math.pi * 3.0 * t)
        ring = np.exp(-distance / (AURA_RADIUS * radius_scale * pulse)).astype(np.float32)
        # The flames rise: each row takes light from the rows below.
        rising = cv2.filter2D(ring, -1, self.upward, anchor=(0, 0), borderType=cv2.BORDER_REPLICATE)
        ring = np.maximum(ring, rising * 1.3)

        offset = int(t * 220 * AURA_SCALE) % self.noise.shape[0]
        noise = cv2.resize(np.roll(self.noise, offset, axis=0), small_size, interpolation=cv2.INTER_LINEAR)
        field = np.clip(ring * (0.55 + 0.9 * noise) * intensity, 0.0, 1.0)
        if bottom >= height:
            rows = min(field.shape[0], 15)
            field[-rows:] *= np.linspace(1.0, 0.0, rows, dtype=np.float32)[:, None]

        glow = AURA_LUT[(field * 255).astype(np.uint8)] * field[:, :, None]
        self._draw_sparks(glow, person, t, intensity)
        # Keep the person untouched: the aura lives outside the silhouette.
        glow *= (1.0 - person)[:, :, None]
        glow = cv2.resize(glow, (right - left, bottom - top), interpolation=cv2.INTER_LINEAR)

        result = frame.copy()
        result[area] = np.clip(frame[area].astype(np.float32) + glow, 0, 255).astype(np.uint8)
        return result

    def _draw_sparks(self, glow: np.ndarray, person: np.ndarray, t: float, intensity: float) -> None:
        contours, _ = cv2.findContours((person > 0.5).astype(np.uint8), cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_NONE)
        if not contours:
            return
        edge = np.concatenate([contour.reshape(-1, 2) for contour in contours])
        life = 0.4
        for index in range(self.sparks):
            shifted = t + index * life / self.sparks
            cycle = int(shifted // life)
            age = (shifted % life) / life
            rng = np.random.default_rng(self.seed * 1000 + index * 7919 + cycle)
            x, y = edge[int(rng.integers(len(edge)))]
            rise = rng.uniform(150, 300) * AURA_SCALE * age * life
            brightness = (1.0 - age) * intensity
            cv2.circle(glow, (int(x), int(y - rise)), int(rng.integers(1, 3)),
                       (200 * brightness, 255 * brightness, 255 * brightness), -1, cv2.LINE_AA)


# ---------- transformation state ----------

@dataclass
class PowerLevels:
    aura: float = 0.0
    flash: float = 0.0
    shake: float = 0.0
    radius: float = 1.0


@dataclass
class PowerState:
    """off → charging → flash → super → powering_down → off."""
    phase: str = "off"
    started: float = 0.0

    def update(self, now: float, charging_since: float | None) -> None:
        if self.phase == "off" and charging_since is not None:
            self.phase, self.started = "charging", charging_since
        elif self.phase == "charging" and charging_since is None:
            self.phase = "off"
        elif self.phase == "flash" and now - self.started >= FLASH_SECONDS:
            self.phase, self.started = "super", now
        elif self.phase == "powering_down" and now - self.started >= POWER_DOWN_SECONDS:
            self.phase = "off"

    def transform(self, now: float) -> None:
        self.phase, self.started = "flash", now

    def power_down(self, now: float) -> None:
        self.phase, self.started = "powering_down", now

    @property
    def transformed(self) -> bool:
        return self.phase in ("flash", "super")

    def reset(self) -> None:
        self.phase, self.started = "off", 0.0

    def levels(self, now: float) -> PowerLevels:
        age = max(0.0, now - self.started)
        if self.phase == "charging":
            charge = min(1.0, age / CHARGE_SECONDS)
            return PowerLevels(aura=0.6 * charge, shake=2.0 + 6.0 * charge)
        if self.phase == "flash":
            progress = min(1.0, age / FLASH_SECONDS)
            flash = 0.9 * age / 0.08 if age < 0.08 else 0.9 * math.exp(-(age - 0.08) * 8.0)
            return PowerLevels(aura=1.0, flash=flash, shake=6.0 * (1.0 - progress),
                               radius=2.5 - 1.5 * progress)
        if self.phase == "super":
            return PowerLevels(aura=1.0)
        if self.phase == "powering_down":
            left = max(0.0, 1.0 - age / POWER_DOWN_SECONDS)
            return PowerLevels(aura=left)
        return PowerLevels()


def shake_frame(frame: np.ndarray, amplitude: float, t: float) -> np.ndarray:
    if amplitude <= 0.0:
        return frame
    rng = np.random.default_rng(int(t * 30))
    dx, dy = rng.uniform(-amplitude, amplitude, 2)
    matrix = np.float32(((1, 0, dx), (0, 1, dy)))
    return cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]),
                          borderMode=cv2.BORDER_REPLICATE)


def render_super_saiyan(frame: np.ndarray, mask: np.ndarray | None,
                        levels: PowerLevels, t: float, aura: AuraRenderer | None) -> np.ndarray:
    output = frame
    if aura is not None:
        output = aura.render(output, mask, levels.aura, t, levels.radius)
    if levels.flash > 0.0:
        output = np.clip(output.astype(np.float32) + (255.0 - output) * min(1.0, levels.flash),
                         0, 255).astype(np.uint8)
    output = shake_frame(output, levels.shake, t)
    return output if output is not frame else frame.copy()


# ---------- sounds (synthesized: no third-party audio) ----------

def _write_wav(path: Path, signal: np.ndarray, sample_rate: int = 44100, peak: float = 0.9) -> Path:
    signal = signal / max(1e-6, float(np.abs(signal).max())) * peak
    samples = (signal * 32767).astype("<i2")
    stereo = np.repeat(samples[:, None], 2, axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(stereo.tobytes())
    return path


def _band_noise(size: int, seed: int, short: int = 4, long: int = 40) -> np.ndarray:
    noise = np.random.default_rng(seed).standard_normal(size)
    return np.convolve(noise, np.ones(short) / short, "same") - np.convolve(noise, np.ones(long) / long, "same")


def write_charge_sound(path: Path, sample_rate: int = 44100) -> Path:
    """Roar that builds over the whole charge (plays once, not looped)."""
    duration = CHARGE_SECONDS + 0.1
    t = np.arange(int(sample_rate * duration)) / sample_rate
    progress = t / duration
    signal = np.zeros_like(t)
    for detune in (0.0, 3.0):
        base = np.cumsum(55.0 + 55.0 * progress + detune) / sample_rate
        for harmonic in range(1, 7):
            signal += np.sin(2 * math.pi * harmonic * base) / harmonic
    tremolo = 0.75 + 0.25 * np.sin(2 * math.pi * np.cumsum(8.0 + 14.0 * progress) / sample_rate)
    signal *= tremolo * (0.2 + 0.8 * progress)
    signal += _band_noise(t.size, 11) * progress ** 1.5 * 2.5
    whistle = np.sin(2 * math.pi * np.cumsum(400.0 + 1400.0 * progress) / sample_rate)
    signal = signal / max(1e-6, float(np.abs(signal).max())) + whistle * 0.08 * progress
    signal = np.tanh(2.2 * signal)
    signal *= np.minimum(1.0, t / 0.03)
    return _write_wav(path, signal, sample_rate)


def write_transform_sound(path: Path, sample_rate: int = 44100) -> Path:
    """Explosion: low thump, whoosh, crackle and a falling sweep."""
    duration = 1.2
    t = np.arange(int(sample_rate * duration)) / sample_rate
    boom = np.sin(2 * math.pi * np.cumsum(60.0 - 25.0 * t / duration) / sample_rate) * np.exp(-6.0 * t)
    rng = np.random.default_rng(23)
    rumble = np.convolve(rng.standard_normal(t.size), np.ones(30) / 30, "same") * np.exp(-4.0 * t) * 4.0
    envelope = np.exp(-3.0 * t)
    crackle = (rng.random(t.size) < 0.004 * envelope) * rng.uniform(-1, 1, t.size) * 1.5
    sweep = np.sin(2 * math.pi * np.cumsum(2000.0 - 1700.0 * t / duration) / sample_rate) * np.exp(-5.0 * t) * 0.3
    signal = np.tanh(1.8 * (boom + rumble + crackle + sweep))
    signal *= np.minimum(1.0, (duration - t) / 0.05)
    return _write_wav(path, signal, sample_rate)


def write_aura_hum(path: Path, sample_rate: int = 44100) -> Path:
    """2 s hum that loops seamlessly: whole cycles and circularly filtered noise."""
    duration = 2.0
    size = int(sample_rate * duration)
    t = np.arange(size) / sample_rate
    hum = sum(np.sin(2 * math.pi * frequency * t) / index
              for index, frequency in enumerate((70.0, 140.0, 210.0), start=1))
    hum *= 0.8 + 0.2 * np.sin(2 * math.pi * 3.0 * t)
    spectrum = np.fft.rfft(np.random.default_rng(31).standard_normal(size))
    frequencies = np.fft.rfftfreq(size, 1.0 / sample_rate)
    spectrum[(frequencies < 2000) | (frequencies > 6000)] = 0
    crackle = np.fft.irfft(spectrum, size)
    crackle /= max(1e-6, float(np.abs(crackle).max()))
    signal = hum / max(1e-6, float(np.abs(hum).max())) + crackle * 0.15
    return _write_wav(path, signal, sample_rate, peak=0.35)
