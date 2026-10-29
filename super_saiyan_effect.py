"""Super Saiyan transformation: charge-ki pose, golden hair, yellow aura and sounds."""

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
HAIR_INTERVAL = 0.1
HAIR_HOLD_SECONDS = 0.3
AURA_SCALE = 0.5
AURA_RADIUS = 16.0  # At half resolution.
HAIR_CLASS = 1  # selfie_multiclass_256x256: 0 background, 1 hair, 2 body skin, 3 face skin, 4 clothes, 5 other.

# Face Landmarker.
NOSE, CHIN, FOREHEAD_TOP = 1, 152, 10
FACE_LEFT, FACE_RIGHT = 234, 454

# BGR: from the orange edge to the almost-white core.
AURA_STOPS = ((0.0, (0, 0, 0)), (0.35, (0, 140, 255)), (0.7, (0, 215, 255)), (1.0, (200, 255, 255)))
GOLD_STOPS = ((0.0, (10, 70, 140)), (0.55, (30, 190, 255)), (1.0, (170, 250, 255)))


def _gradient_lut(stops) -> np.ndarray:
    positions = np.array([position for position, _ in stops])
    colors = np.array([color for _, color in stops], dtype=np.float32)
    x = np.linspace(0.0, 1.0, 256)
    return np.stack([np.interp(x, positions, colors[:, channel]) for channel in range(3)], axis=1)


AURA_LUT = _gradient_lut(AURA_STOPS).astype(np.float32)
GOLD_LUT = _gradient_lut(GOLD_STOPS).astype(np.float32)


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
    """Two fists at chest height, one on each side of the nose (the ki-charging pose)."""
    if len(hands) < 2 or face.shape[0] <= max(FACE_RIGHT, CHIN):
        return False
    scale = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    if scale < 20.0:
        return False
    nose, chin = face[NOSE], face[CHIN]
    centers = []
    for hand in hands[:2]:
        if hand.shape != (21, 2) or not np.isfinite(hand).all():
            return False
        if hand_tension(hand) < 3:
            return False
        size = float(np.linalg.norm(hand[0] - hand[9]))
        if not 0.25 * scale < size < 0.9 * scale:
            return False
        if hand[0][1] <= chin[1] + 0.5 * scale:
            return False
        center = hand[[0, 5, 9, 13, 17]].mean(axis=0)
        if center[1] >= 0.97 * height:
            return False
        if abs(center[0] - nose[0]) <= 0.35 * scale:
            return False
        centers.append(center)
    left, right = centers
    return (left[0] - nose[0]) * (right[0] - nose[0]) < 0 and abs(left[1] - right[1]) < scale


def face_points(faces, width: int, height: int) -> np.ndarray | None:
    return _points(faces[0], width, height) if faces else None


def charging_from_landmarks(hands, faces, width: int, height: int) -> bool:
    face = face_points(faces, width, height)
    if face is None:
        return False
    points = [_points(hand, width, height) for hand in hands if len(hand) == 21]
    return charge_pose(points, face, width, height)


# ---------- golden hair ----------

def head_box(face: np.ndarray, width: int, height: int) -> tuple[int, int, int, int] | None:
    scale = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    if scale < 20.0:
        return None
    left = int(max(0, min(face[FACE_LEFT][0], face[FACE_RIGHT][0]) - 0.6 * scale))
    right = int(min(width, max(face[FACE_LEFT][0], face[FACE_RIGHT][0]) + 0.6 * scale))
    top = int(max(0, face[FOREHEAD_TOP][1] - 1.2 * scale))
    bottom = int(min(height, face[CHIN][1] + 0.2 * scale))
    if right - left < 8 or bottom - top < 8:
        return None
    return left, top, right, bottom


def hair_from_confidence(confidence: np.ndarray, box: tuple[int, int, int, int],
                         shape: tuple[int, int]) -> np.ndarray:
    left, top, right, bottom = box
    mask = np.zeros(shape, dtype=np.float32)
    resized = cv2.resize(confidence.astype(np.float32), (right - left, bottom - top),
                         interpolation=cv2.INTER_LINEAR)
    resized = cv2.GaussianBlur(resized, (0, 0), sigmaX=1.5, sigmaY=1.5)
    mask[top:bottom, left:right] = np.clip((resized - 0.35) / 0.4, 0.0, 1.0)
    return mask


def recolor_hair(frame: np.ndarray, hair: np.ndarray | None, amount: float) -> np.ndarray:
    """Golden hair that keeps texture and lighting (gradient map on luminance)."""
    if hair is None or amount <= 0.0:
        return frame
    alpha_full = hair * float(min(1.0, amount))
    points = cv2.findNonZero((alpha_full > 0.02).astype(np.uint8))
    if points is None:
        return frame
    x, y, w, h = cv2.boundingRect(points)
    margin = 20
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(frame.shape[1], x + w + margin), min(frame.shape[0], y + h + margin)
    area = np.s_[top:bottom, left:right]
    crop = frame[area].astype(np.float32)
    alpha = alpha_full[area]
    gray = cv2.cvtColor(frame[area], cv2.COLOR_BGR2GRAY).astype(np.float32)
    selected = gray[alpha > 0.5]
    if selected.size < 20:
        selected = gray[alpha > 0.02]
    low, high = np.percentile(selected, (5, 95))
    normalized = np.clip((gray - low) / max(1.0, high - low), 0.0, 1.0)
    index = ((0.3 + 0.7 * normalized) * 255).astype(np.uint8)
    gold = GOLD_LUT[index]
    output = crop * (1.0 - alpha[:, :, None]) + gold * alpha[:, :, None]
    glow = cv2.GaussianBlur(alpha, (0, 0), sigmaX=6.0, sigmaY=6.0)[:, :, None]
    output += glow * np.array((0, 200, 255), dtype=np.float32) * 0.25
    result = frame.copy()
    result[area] = np.clip(output, 0, 255).astype(np.uint8)
    return result


class HairTracker:
    """Segment the hair on a head crop (multiclass model, IMAGE mode)."""

    def __init__(self, segmenter):
        self.segmenter = segmenter
        self.mask: np.ndarray | None = None
        self.last_update = float("-inf")
        self.last_face = float("-inf")

    def update(self, frame: np.ndarray, face: np.ndarray | None, now: float) -> np.ndarray | None:
        height, width = frame.shape[:2]
        if self.mask is not None and self.mask.shape != (height, width):
            self.mask = None
        if face is None:
            if now - self.last_face > HAIR_HOLD_SECONDS:
                self.mask = None
            return self.mask
        self.last_face = now
        if self.mask is not None and now - self.last_update < HAIR_INTERVAL:
            return self.mask
        self.last_update = now
        box = head_box(face, width, height)
        if box is None:
            return self.mask
        import mediapipe as mp

        left, top, right, bottom = box
        rgb = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2RGB)
        result = self.segmenter.segment(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        )
        masks = result.confidence_masks or []
        if len(masks) <= HAIR_CLASS:
            return self.mask
        confidence = np.squeeze(masks[HAIR_CLASS].numpy_view())
        fresh = hair_from_confidence(confidence, box, (height, width))
        self.mask = fresh if self.mask is None else fresh * 0.6 + self.mask * 0.4
        return self.mask

    def close(self) -> None:
        self.segmenter.close()


# ---------- aura ----------

AURA_SPRITE = Path(__file__).resolve().parent / "assets" / "saiyanaura.gif"


class AuraSprite:
    """Optional animated aura (GIF) blended over the frame with a screen mode."""

    def __init__(self, path: Path = AURA_SPRITE):
        from PIL import Image

        image = Image.open(path)
        self.duration = max(0.03, image.info.get("duration", 40) / 1000.0)
        self.frames: list[np.ndarray] = []
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frame = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
            height, width = frame.shape[:2]
            # The source has a small watermark in the bottom-left corner.
            frame[int(height * 0.93):, :int(width * 0.18)] = 0
            self.frames.append(frame)
        self.scaled: dict[tuple[int, int], list[np.ndarray]] = {}

    def apply(self, frame: np.ndarray, intensity: float, t: float,
              mask: np.ndarray | None = None) -> np.ndarray:
        if intensity <= 0.0 or not self.frames:
            return frame
        source = self.frames[int(t / self.duration) % len(self.frames)]
        height, width = frame.shape[:2]
        output = frame.copy()
        area = np.s_[0:height, 0:width]
        if mask is not None:
            points = cv2.findNonZero((mask > 0.3).astype(np.uint8))
            if points is not None:
                x, y, w, h = cv2.boundingRect(points)
                aura_w = min(width, max(32, int(w * 1.8)))
                aura_h = min(height, max(32, int(h * 2.0)))
                left = min(max(0, x + w // 2 - aura_w // 2), width - aura_w)
                top = min(max(0, y + h - aura_h), height - aura_h)
                area = np.s_[top:top + aura_h, left:left + aura_w]
        target = output[area]
        sprite = cv2.resize(source, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_LINEAR)
        aura = sprite.astype(np.float32) / 255.0 * min(1.0, max(0.0, intensity))
        base = target.astype(np.float32) / 255.0
        output[area] = np.clip((1.0 - (1.0 - base) * (1.0 - aura)) * 255.0, 0, 255).astype(np.uint8)
        return output


def load_aura_sprite(path: Path = AURA_SPRITE) -> AuraSprite | None:
    if not path.is_file():
        return None
    try:
        return AuraSprite(path)
    except Exception as error:
        print(f"[Super Saiyan] Could not load the aura image ({error}); using the generated aura.")
        return None


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
        points = cv2.findNonZero((mask > 0.3).astype(np.uint8))
        if points is None:
            return frame
        height, width = mask.shape
        x, y, w, h = cv2.boundingRect(points)
        left, top = max(0, x - 60), max(0, y - 140)
        right, bottom = min(width, x + w + 60), min(height, y + h + 10)
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
        glow *= (1.0 - 0.85 * person)[:, :, None]
        self._draw_sparks(glow, person, t, intensity)
        glow = cv2.resize(glow, (right - left, bottom - top), interpolation=cv2.INTER_LINEAR)
        body = mask[area][:, :, None] * np.array((0, 215, 255), dtype=np.float32) * 0.08 * intensity

        result = frame.copy()
        result[area] = np.clip(frame[area].astype(np.float32) + glow + body, 0, 255).astype(np.uint8)
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
    hair: float = 0.0
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
            flicker = 0.8 if charge > 0.5 and int(now * 12) % 2 else 0.0
            return PowerLevels(aura=0.6 * charge, hair=flicker, shake=2.0 + 6.0 * charge)
        if self.phase == "flash":
            progress = min(1.0, age / FLASH_SECONDS)
            flash = 0.9 * age / 0.08 if age < 0.08 else 0.9 * math.exp(-(age - 0.08) * 8.0)
            return PowerLevels(aura=1.0, hair=1.0, flash=flash, shake=6.0 * (1.0 - progress),
                               radius=2.5 - 1.5 * progress)
        if self.phase == "super":
            return PowerLevels(aura=1.0, hair=1.0)
        if self.phase == "powering_down":
            left = max(0.0, 1.0 - age / POWER_DOWN_SECONDS)
            hair = left if age < POWER_DOWN_SECONDS - 0.2 or int(now * 20) % 2 else 0.0
            return PowerLevels(aura=left, hair=hair)
        return PowerLevels()


def shake_frame(frame: np.ndarray, amplitude: float, t: float) -> np.ndarray:
    if amplitude <= 0.0:
        return frame
    rng = np.random.default_rng(int(t * 30))
    dx, dy = rng.uniform(-amplitude, amplitude, 2)
    matrix = np.float32(((1, 0, dx), (0, 1, dy)))
    return cv2.warpAffine(frame, matrix, (frame.shape[1], frame.shape[0]),
                          borderMode=cv2.BORDER_REPLICATE)


def render_super_saiyan(frame: np.ndarray, mask: np.ndarray | None, hair: np.ndarray | None,
                        levels: PowerLevels, t: float, aura: AuraRenderer) -> np.ndarray:
    output = recolor_hair(frame, hair, levels.hair)
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
