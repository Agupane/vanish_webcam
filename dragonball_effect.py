"""Dragon Ball mode: Instant Transmission gesture and teleport effect."""

from __future__ import annotations

import math
import wave
from pathlib import Path

import cv2
import numpy as np


HOLD_SECONDS = 1.0
EFFECT_SECONDS = 0.95
# Momento in cui la persona sparisce del tutto; le linee restano fino alla fine.
VANISH_AT = 0.42
LINES_FULL_AT = 0.30

# Face Landmarker: parte alta della fronte, centro fronte, tra le sopracciglia, lati del viso.
FOREHEAD_TOP, FOREHEAD_CENTER, BROWS = 10, 151, 9
FACE_LEFT, FACE_RIGHT = 234, 454

LINE_COLOR = np.array((255, 250, 236), dtype=np.float32)  # BGR, bianco caldo.
GLOW_COLOR = np.array((255, 236, 170), dtype=np.float32)  # BGR, azzurro chiaro.


def _image_points(landmarks, width: int, height: int) -> np.ndarray:
    return np.array([(p.x * width, p.y * height) for p in landmarks], dtype=np.float32)


def _finger(hand: np.ndarray, base: int) -> tuple[float, float, bool]:
    """Lunghezza, rettilineità e se il dito è disteso (punta lontana dal polso)."""
    finger = hand[base:base + 4]
    length = float(np.linalg.norm(np.diff(finger, axis=0), axis=1).sum())
    if length < 1e-3:
        return 0.0, 0.0, False
    ratio = float(np.linalg.norm(finger[3] - finger[0])) / length
    reach = float(np.linalg.norm(finger[3] - hand[0]))
    knuckle = float(np.linalg.norm(finger[0] - hand[0]))
    return length, ratio, ratio >= 0.8 and reach > knuckle * 1.25


def two_finger_tip(hand: np.ndarray) -> np.ndarray | None:
    """Punto medio delle punte di indice e medio se sono distesi e uniti.

    Anulare e mignolo non devono essere distesi: una mano aperta sulla fronte
    (facepalm) non deve far partire il teletrasporto.
    """
    if hand.shape != (21, 2) or not np.isfinite(hand).all():
        return None
    lengths = []
    for base in (5, 9):
        length, _, extended = _finger(hand, base)
        if not extended:
            return None
        lengths.append(length)
    for base in (13, 17):
        if _finger(hand, base)[2]:
            return None
    if float(np.linalg.norm(hand[8] - hand[12])) > min(lengths) * 0.5:
        return None
    return (hand[8] + hand[12]) * 0.5


def _segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    segment = end - start
    t = float(np.dot(point - start, segment) / max(1e-6, float(np.dot(segment, segment))))
    return float(np.linalg.norm(point - (start + segment * np.clip(t, 0.0, 1.0))))


def touching_forehead(tip: np.ndarray, face: np.ndarray) -> bool:
    if face.shape[0] <= max(FACE_RIGHT, FACE_LEFT, FOREHEAD_TOP, BROWS):
        return False
    face_width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    if face_width < 20.0:
        return False
    distance = _segment_distance(tip, face[FOREHEAD_TOP], face[BROWS])
    return distance < face_width * 0.38


def instant_transmission(hands, faces, width: int, height: int) -> bool:
    """Indice e medio uniti appoggiati sulla fronte (la posa del teletrasporto)."""
    if not hands or not faces:
        return False
    face = _image_points(faces[0], width, height)
    for landmarks in hands:
        if len(landmarks) != 21:
            continue
        tip = two_finger_tip(_image_points(landmarks, width, height))
        if tip is not None and touching_forehead(tip, face):
            return True
    return False


class InstantTransmissionDetector:
    """Hand + Face Landmarker in modalità video sullo stesso fotogramma."""

    def __init__(self, hands, faces):
        self.hands = hands
        self.faces = faces
        self.last_hand_count = 0
        self.last_face_found = False

    def detect(self, image, timestamp_ms: int) -> bool:
        hands = self.hands.detect_for_video(image, timestamp_ms).hand_landmarks
        faces = self.faces.detect_for_video(image, timestamp_ms).face_landmarks
        self.last_hand_count = len(hands)
        self.last_face_found = bool(faces)
        return instant_transmission(hands, faces, image.width, image.height)

    def close(self) -> None:
        try:
            self.hands.close()
        finally:
            self.faces.close()


def person_alpha(age: float) -> float:
    """Opacità della persona: resta, sfarfalla e sparisce entro VANISH_AT."""
    if age <= 0.25:
        return 1.0
    if age >= VANISH_AT:
        return 0.0
    fade = 1.0 - (age - 0.25) / (VANISH_AT - 0.25)
    flicker = 0.55 if int(age * 30) % 2 else 1.0
    return fade * flicker


def lines_intensity(age: float) -> float:
    if age <= 0.0 or age >= EFFECT_SECONDS:
        return 0.0
    if age < LINES_FULL_AT:
        return age / LINES_FULL_AT
    if age < VANISH_AT:
        return 1.0
    return 1.0 - (age - VANISH_AT) / (EFFECT_SECONDS - VANISH_AT)


def speed_lines(region: np.ndarray, age: float, seed: int = 4242) -> np.ndarray:
    """Linee verticali in stile fumetto che scorrono dentro la silhouette."""
    height, width = region.shape
    layer = np.zeros((height, width), dtype=np.uint8)
    rng = np.random.default_rng(seed)
    count = max(6, width // 7)
    for _ in range(count):
        x = int(rng.uniform(0, width))
        length = max(4, int(height * rng.uniform(0.25, 0.8)))
        speed = rng.uniform(2.5, 5.0)
        offset = rng.uniform(0, height + length)
        thickness = int(rng.choice((1, 1, 2, 3)))
        # Scorrono verso l'alto e rientrano dal basso.
        top = int((offset - age * speed * height) % (height + length)) - length
        cv2.line(layer, (x, top), (x, top + length), 255, thickness, cv2.LINE_AA)
    lines = layer.astype(np.float32) / 255.0
    lines = cv2.GaussianBlur(lines, (0, 0), sigmaX=1.2, sigmaY=0.4)
    return np.clip(lines * region, 0.0, 1.0)


def render_teleport(frame: np.ndarray, background: np.ndarray, mask: np.ndarray,
                    age: float) -> np.ndarray:
    """Teletrasporto in uscita. Per il ritorno si usa age = EFFECT_SECONDS - tempo."""
    if age >= EFFECT_SECONDS or mask is None:
        return background.copy()
    points = cv2.findNonZero((mask > 0.2).astype(np.uint8))
    if points is None:
        return background.copy()
    x, y, w, h = cv2.boundingRect(points)
    margin = 24
    left, top = max(0, x - margin), max(0, y - margin)
    right = min(mask.shape[1], x + w + margin)
    bottom = min(mask.shape[0], y + h + margin)
    area = np.s_[top:bottom, left:right]

    canvas = background.copy()
    person = mask[area] * person_alpha(age)
    lines_level = lines_intensity(age)
    output = (
        frame[area].astype(np.float32) * person[:, :, None]
        + background[area].astype(np.float32) * (1.0 - person[:, :, None])
    )
    if lines_level > 0:
        # La persona si illumina mentre le linee si intensificano.
        glow = (person * lines_level * 0.35)[:, :, None]
        output = output * (1.0 - glow) + GLOW_COLOR * glow
        region = cv2.GaussianBlur(mask[area], (0, 0), sigmaX=6.0, sigmaY=6.0)
        lines = (speed_lines(np.clip(region * 1.4, 0.0, 1.0), age) * lines_level)[:, :, None]
        output = output * (1.0 - lines) + LINE_COLOR * lines
    canvas[area] = np.clip(output, 0, 255).astype(np.uint8)
    return canvas


def write_teleport_sound(path: Path, sample_rate: int = 44100) -> Path:
    """Genera un breve "shwip" (sweep + soffio) senza usare audio di terzi."""
    duration = 0.5
    t = np.arange(int(sample_rate * duration), dtype=np.float64) / sample_rate
    frequency = 500.0 + 2600.0 * (t / duration) ** 1.5
    chirp = np.sin(2 * math.pi * np.cumsum(frequency) / sample_rate) * np.exp(-t * 7.0) * 0.35
    noise = np.random.default_rng(5).standard_normal(t.size)
    band = np.convolve(noise, np.ones(4) / 4, "same") - np.convolve(noise, np.ones(40) / 40, "same")
    whoosh = band * np.minimum(1.0, t / 0.04) * np.exp(-t * 9.0) * 0.5
    ping = np.sin(2 * math.pi * 3200.0 * t) * np.exp(-t * 30.0) * 0.2
    signal = chirp + whoosh + ping
    signal *= np.minimum(1.0, (t[-1] - t) / 0.02)
    signal /= max(1e-6, float(np.abs(signal).max())) * 1.1
    samples = (signal * 32767).astype("<i2")
    stereo = np.repeat(samples[:, None], 2, axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(stereo.tobytes())
    return path
