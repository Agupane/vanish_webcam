"""Super Saiyan face: teal eyes, golden eyebrows and the user's imported golden hair.

The hair is not drawn by VanishCam. The user takes a few photos (`--ssj-hair-photos`), turns them into Super Saiyan
versions with an image model of their choice (ChatGPT, Gemini...) and saves them as `ssj_hair/ssj_*.png`. This
module cuts the golden hair out of those images and, while transformed, fits it on the live face with a similarity
transform from the face landmarks. VanishCam itself never sends anything over the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


# Face Landmarker (478 points, with irises).
NOSE, CHIN, FOREHEAD_TOP = 1, 152, 10
FACE_LEFT, FACE_RIGHT = 234, 454
IRISES = ((468, (469, 470, 471, 472)), (473, (474, 475, 476, 477)))
EYE_OPENINGS = (
    (33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246),
    (362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398),
)
# Each brow: upper edge from the outside in, then the lower edge from the inside out.
BROWS = (
    (70, 63, 105, 66, 107, 55, 65, 52, 53, 46),
    (300, 293, 334, 296, 336, 285, 295, 282, 283, 276),
)
LOWER_FACE = (234, 93, 132, 58, 172, 136, 150, 149, 176, 148, 152, 377, 400, 378, 379, 365, 397, 288, 361, 323, 454)
# Stable points used to fit the hair: eye corners, nose, forehead, chin and cheeks.
HAIR_ANCHORS = (33, 133, 362, 263, NOSE, FOREHEAD_TOP, CHIN, FACE_LEFT, FACE_RIGHT)

EYE_COLOR = np.array((175, 205, 40), np.float32)  # BGR teal-green.
BROW_COLOR = np.array((40, 200, 255), np.float32)  # BGR gold.
BROW_OPACITY = 0.6
HAIR_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".PNG", ".JPG", ".JPEG", ".WEBP")
HAIR_VIEWS = (("front", "look straight at the camera"),
              ("left", "turn your head a little to one side"),
              ("right", "turn your head a little to the other side"))

HAIR_PROMPT = (
    "Edit this photo: give the person Super Saiyan hair from Dragon Ball Z - bright golden yellow, spiky, standing "
    "up and slightly larger than their real hair, photorealistic, as if it were real hair. Keep exactly the same "
    "person, face, skin tone, eyes, expression, head pose, framing and image size. Plain mid-gray background. No "
    "aura, no glow, no lightning, no text, no other changes."
)


# ---------- helpers ----------

def points_from_landmarks(landmarks, width: int, height: int) -> np.ndarray:
    return np.array([(p.x * width, p.y * height) for p in landmarks], dtype=np.float32)


def usable_face(face: np.ndarray | None) -> bool:
    return (face is not None and face.ndim == 2 and face.shape[0] >= 478 and np.isfinite(face).all()
            and float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT])) >= 20.0)


def face_yaw(face: np.ndarray) -> float:
    """Where the head points, about -0.5..0.5: the nose relative to the middle of the cheeks."""
    width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    middle = (face[FACE_LEFT] + face[FACE_RIGHT]) * 0.5
    return float((face[NOSE][0] - middle[0]) / max(width, 1e-6))


def _box(points: np.ndarray, pad: float, shape) -> tuple[int, int, int, int]:
    x0, y0 = np.floor(points.min(axis=0) - pad).astype(int)
    x1, y1 = np.ceil(points.max(axis=0) + pad).astype(int)
    return max(0, x0), max(0, y0), min(shape[1], x1), min(shape[0], y1)


# ---------- eyes and eyebrows ----------

def tint_eyes(frame: np.ndarray, face: np.ndarray, strength: float) -> np.ndarray:
    """Teal-green irises, keeping the eye's own shading; the whites and the lids are untouched."""
    if strength <= 0.0 or not usable_face(face):
        return frame
    result = frame
    for (center_index, ring), opening in zip(IRISES, EYE_OPENINGS):
        center = face[center_index]
        radius = float(np.linalg.norm(face[list(ring)] - center, axis=1).mean())
        if radius < 1.5:
            continue
        outline = face[list(opening)]
        x0, y0, x1, y1 = _box(np.vstack([outline, center[None]]), radius + 2, frame.shape)
        if x1 <= x0 or y1 <= y0:
            continue
        region = np.zeros((y1 - y0, x1 - x0), np.float32)
        cv2.fillPoly(region, [np.round(outline - (x0, y0)).astype(np.int32)], 1.0, cv2.LINE_AA)
        disk = np.zeros_like(region)
        local = (float(center[0] - x0), float(center[1] - y0))
        cv2.circle(disk, (int(round(local[0])), int(round(local[1]))), int(round(radius * 1.05)), 1.0, -1, cv2.LINE_AA)
        pupil = np.zeros_like(region)
        cv2.circle(pupil, (int(round(local[0])), int(round(local[1]))), max(1, int(round(radius * 0.35))), 1.0, -1,
                   cv2.LINE_AA)
        alpha = region * disk * (1.0 - 0.75 * pupil) * (0.85 * min(1.0, strength))
        if not alpha.any():
            continue
        if result is frame:
            result = frame.copy()
        patch = result[y0:y1, x0:x1].astype(np.float32)
        light = cv2.cvtColor(result[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        tinted = np.clip(EYE_COLOR * (0.45 + 1.3 * light[:, :, None]), 0, 255)
        result[y0:y1, x0:x1] = (patch + (tinted - patch) * alpha[:, :, None]).astype(np.uint8)
    return result


def tint_brows(frame: np.ndarray, face: np.ndarray, strength: float) -> np.ndarray:
    """Golden eyebrows: only the brow hairs (darker than the skin around them) change color."""
    if strength <= 0.0 or not usable_face(face):
        return frame
    result = frame
    for brow in BROWS:
        outline = face[list(brow)]
        x0, y0, x1, y1 = _box(outline, 6, frame.shape)
        if x1 <= x0 or y1 <= y0:
            continue
        region = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(region, [np.round(outline - (x0, y0)).astype(np.int32)], 1)
        region = cv2.dilate(region, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        if not region.any():
            continue
        light = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
        skin = float(np.percentile(light, 80))  # The box is mostly skin around the brow.
        hairs = np.clip((skin - light) / 55.0, 0.0, 1.0) * region
        alpha = cv2.GaussianBlur(hairs, (0, 0), 1.2) * (BROW_OPACITY * min(1.0, strength))
        if not alpha.any():
            continue
        if result is frame:
            result = frame.copy()
        patch = result[y0:y1, x0:x1].astype(np.float32)
        # Brow hairs are dark: lift them towards gold, keeping their own shading (no flat painted bar).
        tinted = np.clip(BROW_COLOR * (0.35 + 1.3 * light[:, :, None] / 255.0), 0, 255)
        result[y0:y1, x0:x1] = (patch + (tinted - patch) * alpha[:, :, None]).astype(np.uint8)
    return result


# ---------- imported hair ----------

@dataclass
class HairView:
    """Golden hair cut out of one generated image, with the face points it was drawn around."""
    name: str
    rgba: np.ndarray  # BGRA, alpha = hair.
    anchors: np.ndarray  # HAIR_ANCHORS in rgba coordinates.
    yaw: float


def hair_mask(image: np.ndarray, face: np.ndarray) -> np.ndarray:
    """Golden hair around the face of a generated Super Saiyan image (uint8 0/1, image size)."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.int16)
    lightness, a, b = lab[:, :, 0], lab[:, :, 1] - 128, lab[:, :, 2] - 128
    # Gold is strongly yellow (b) and not reddish (a); skin is about as red as it is yellow.
    gold = ((b > 25) & (b - a > 22) & (lightness > 90)).astype(np.uint8)
    face_width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    face_height = float(np.linalg.norm(face[CHIN] - face[FOREHEAD_TOP]))
    # Safety: the eyes, nose, mouth and cheeks (below the brows) are never hair.
    lower = np.vstack([face[list(LOWER_FACE)], face[list(BROWS[1][5:])], face[list(BROWS[0][5:])][::-1]])
    cv2.fillPoly(gold, [cv2.convexHull(np.round(lower).astype(np.int32))], 0)
    gold = cv2.morphologyEx(gold, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    gold = cv2.morphologyEx(gold, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    # Keep only pieces that touch the head: a band around the face outline.
    head = np.zeros_like(gold)
    cv2.fillPoly(head, [cv2.convexHull(np.round(face).astype(np.int32))], 1)
    reach = max(3, int(0.35 * face_width)) | 1
    head = cv2.dilate(head, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (reach, reach)))
    contours, _ = cv2.findContours(gold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(gold)
    minimum = 0.01 * face_width * face_height
    for contour in contours:
        if cv2.contourArea(contour) < minimum:
            continue
        piece = np.zeros_like(gold)
        cv2.drawContours(piece, [contour], -1, 1, -1)  # Also fills the highlights inside the hair.
        if (piece & head).any():
            mask |= piece
    return mask


def extract_hair(image: np.ndarray, face: np.ndarray, name: str = "front") -> HairView | None:
    if not usable_face(face):
        return None
    mask = hair_mask(image, face)
    face_width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    face_height = float(np.linalg.norm(face[CHIN] - face[FOREHEAD_TOP]))
    if mask.sum() < 0.08 * face_width * face_height:
        return None
    x, y, w, h = cv2.boundingRect(mask)
    alpha = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.2)[y:y + h, x:x + w]
    rgba = cv2.cvtColor(image[y:y + h, x:x + w], cv2.COLOR_BGR2BGRA)
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    anchors = face[list(HAIR_ANCHORS)] - (x, y)
    return HairView(name, rgba, anchors.astype(np.float32), face_yaw(face))


def _save_view(view: HairView, cache: Path, source: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(cache / f"{source.stem}.png"), view.rgba)
    stat = source.stat()
    (cache / f"{source.stem}.json").write_text(json.dumps({
        "source_size": stat.st_size, "source_mtime": stat.st_mtime,
        "anchors": view.anchors.tolist(), "yaw": view.yaw,
    }))


def _load_cached(cache: Path, source: Path) -> HairView | None:
    meta_path, image_path = cache / f"{source.stem}.json", cache / f"{source.stem}.png"
    if not (meta_path.is_file() and image_path.is_file()):
        return None
    try:
        meta = json.loads(meta_path.read_text())
        stat = source.stat()
        if meta["source_size"] != stat.st_size or meta["source_mtime"] != stat.st_mtime:
            return None
        rgba = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
            return None
        return HairView(source.stem, rgba, np.array(meta["anchors"], np.float32), float(meta["yaw"]))
    except (OSError, ValueError, KeyError):
        return None


def hair_sources(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir()
                  if path.is_file() and path.name.startswith("ssj_") and path.suffix in HAIR_SUFFIXES)


def load_hair_views(folder: Path, detect_face: Callable[[np.ndarray], np.ndarray | None],
                    log: Callable[[str], None] = print) -> list[HairView]:
    """Hair from every `ssj_*` image in the folder; cut-outs are cached in `.cache` next to them."""
    views = []
    cache = folder / ".cache"
    for source in hair_sources(folder):
        view = _load_cached(cache, source)
        if view is None:
            image = cv2.imread(str(source), cv2.IMREAD_COLOR)
            if image is None:
                log(f"[Super Saiyan] Could not read {source.name}.")
                continue
            face = detect_face(image)
            if face is None:
                log(f"[Super Saiyan] No face found in {source.name}: use a photo where the whole face is visible.")
                continue
            view = extract_hair(image, face, source.stem)
            if view is None:
                log(f"[Super Saiyan] No golden hair found in {source.name}: the hair must be clearly yellow/gold.")
                continue
            _save_view(view, cache, source)
            log(f"[Super Saiyan] Hair imported from {source.name}.")
        views.append(view)
    return views


class HairOverlay:
    """Fits the imported hair on the live face: the view closest to where the head points, scaled and rotated."""

    def __init__(self, views: list[HairView]):
        self.views = views

    def pick(self, face: np.ndarray) -> HairView:
        yaw = face_yaw(face)
        return min(self.views, key=lambda view: abs(view.yaw - yaw))

    def place(self, face: np.ndarray | None, shape) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
        """The hair warped onto this face: BGRA patch and its (x0, y0, x1, y1) box in the frame."""
        if not self.views or not usable_face(face):
            return None
        view = self.pick(face)
        matrix, _ = cv2.estimateAffinePartial2D(view.anchors, face[list(HAIR_ANCHORS)], method=cv2.LMEDS)
        if matrix is None or not np.isfinite(matrix).all():
            return None
        height, width = view.rgba.shape[:2]
        corners = np.array([(0, 0), (width, 0), (0, height), (width, height)], np.float32)
        placed = corners @ matrix[:, :2].T + matrix[:, 2]
        x0, y0, x1, y1 = _box(placed, 1, shape)
        if x1 <= x0 or y1 <= y0:
            return None
        shifted = matrix.copy()
        shifted[:, 2] -= (x0, y0)
        warped = cv2.warpAffine(view.rgba, shifted, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        return warped, (x0, y0, x1, y1)

    def mask(self, face: np.ndarray | None, shape) -> np.ndarray | None:
        """Where the hair covers the frame, 0-1, so the aura can surround it."""
        placed = self.place(face, shape)
        if placed is None:
            return None
        warped, (x0, y0, x1, y1) = placed
        mask = np.zeros(shape[:2], np.float32)
        mask[y0:y1, x0:x1] = warped[:, :, 3] / np.float32(255.0)
        return mask

    def render(self, frame: np.ndarray, face: np.ndarray | None, strength: float) -> np.ndarray:
        if strength <= 0.0:
            return frame
        placed = self.place(face, frame.shape)
        if placed is None:
            return frame
        warped, (x0, y0, x1, y1) = placed
        alpha = warped[:, :, 3].astype(np.float32) * (min(1.0, strength) / 255.0)
        if not alpha.any():
            return frame
        result = frame.copy()
        area = result[y0:y1, x0:x1]
        result[y0:y1, x0:x1] = cv2.blendLinear(area, np.ascontiguousarray(warped[:, :, :3]), 1.0 - alpha, alpha)
        return result


def render_face(frame: np.ndarray, face: np.ndarray | None, strength: float,
                hair: HairOverlay | None = None, eyes: bool = True, brows: bool = True) -> np.ndarray:
    """Brows, eyes, then the hair on top (it may cover the brows, like a fringe).

    `eyes` / `brows` off: for people who already have green eyes or fair eyebrows.
    """
    if strength <= 0.0 or face is None:
        return frame
    output = tint_brows(frame, face, strength) if brows else frame
    output = tint_eyes(output, face, strength) if eyes else output
    if hair is not None:
        output = hair.render(output, face, strength)
    return output