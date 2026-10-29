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

try:
    from . import ssj_motion
except ImportError:
    import ssj_motion


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
# Fit weights for HAIR_ANCHORS: the chin moves when talking (it made the hair change size), the eye corners do not.
# The chin is weighted out rather than removed so the anchors cached in ssj_hair/.cache stay valid.
ANCHOR_WEIGHTS = (1.0, 1.0, 1.0, 1.0, 0.8, 0.6, 0.05, 0.7, 0.7)
# Hair motion: how far from the face the hair goes from fixed (roots) to free (tips), in face widths.
ROOT_BAND = 0.6
# Changing between the front and side pictures: only when another one is clearly closer, for a moment, with a fade.
VIEW_SWITCH_MARGIN = 0.04
VIEW_SWITCH_HOLD = 0.25
# Short: during the fade both pictures are see-through and their different spikes show double (owner's video).
VIEW_FADE_SECONDS = 0.1

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


@dataclass
class PlacedHair:
    """The hair for one frame: a BGRA patch and its (x0, y0, x1, y1) box. Shared by the aura and the drawing."""
    rgba: np.ndarray
    box: tuple[int, int, int, int]


def head_tracker() -> ssj_motion.HeadTracker:
    return ssj_motion.HeadTracker(HAIR_ANCHORS, ANCHOR_WEIGHTS, face_yaw, (FACE_LEFT, FACE_RIGHT))


def head_pose(face: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Centre (eyes and nose), roll angle (eye line) and width of a face, for the hair dynamics."""
    center = face[[33, 263, NOSE]].mean(axis=0)
    eyes = face[263] - face[33]
    width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    return center, float(np.arctan2(eyes[1], eyes[0])), width


def _smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


class HairOverlay:
    """Fits the imported hair on the live face: the view closest to where the head points, scaled and rotated.

    `place_live` keeps a little state across frames: which picture is shown (switching with hysteresis and a short
    fade, since the pictures are different drawings) and the tips warp for the hair motion. `place`, `mask` and
    `render` are the stateless rigid versions.
    """

    def __init__(self, views: list[HairView]):
        self.views = views
        self._roots: dict[int, np.ndarray] = {}
        self.reset()

    def reset(self) -> None:
        self._view: HairView | None = None
        self._previous: HairView | None = None
        self._fade_started = 0.0
        self._candidate: HairView | None = None
        self._candidate_since = 0.0

    def pick(self, face: np.ndarray) -> HairView:
        yaw = face_yaw(face)
        return min(self.views, key=lambda view: abs(view.yaw - yaw))

    def select(self, yaw: float, t: float) -> list[tuple[HairView, float]]:
        """The picture(s) to draw with their weights: one, or two while fading from the previous one."""
        nearest = min(self.views, key=lambda view: abs(view.yaw - yaw))
        if self._view is None:
            self._view, self._candidate = nearest, None
        elif nearest is not self._view and abs(nearest.yaw - yaw) + VIEW_SWITCH_MARGIN < abs(self._view.yaw - yaw):
            if nearest is not self._candidate:
                self._candidate, self._candidate_since = nearest, t
            elif t - self._candidate_since >= VIEW_SWITCH_HOLD:
                self._previous, self._view, self._candidate = self._view, nearest, None
                self._fade_started = t
        else:
            self._candidate = None
        if self._previous is None:
            return [(self._view, 1.0)]
        fade = _smoothstep((t - self._fade_started) / VIEW_FADE_SECONDS)
        if fade >= 1.0:
            self._previous = None
            return [(self._view, 1.0)]
        return [(self._previous, 1.0 - fade), (self._view, fade)]

    def _fit(self, view: HairView, face: np.ndarray) -> np.ndarray | None:
        matrix = ssj_motion.fit_similarity(view.anchors, face[list(HAIR_ANCHORS)], ANCHOR_WEIGHTS)
        if matrix is None or not np.isfinite(matrix).all():
            return None
        return matrix

    def _root_weights(self, view: HairView) -> np.ndarray:
        roots = self._roots.get(id(view))
        if roots is None:
            width = float(np.linalg.norm(view.anchors[-1] - view.anchors[-2]))  # FACE_LEFT, FACE_RIGHT.
            roots = ssj_motion.root_weights(view.rgba[:, :, 3], view.anchors, ROOT_BAND * width)
            self._roots[id(view)] = roots
        return roots

    def _warp(self, view: HairView, face: np.ndarray, shape, motion: ssj_motion.HairMotion | None = None,
              t: float = 0.0) -> PlacedHair | None:
        matrix = self._fit(view, face)
        if matrix is None:
            return None
        height, width = view.rgba.shape[:2]
        corners = np.array([(0, 0), (width, 0), (0, height), (width, height)], np.float32)
        placed = ssj_motion.apply(matrix, corners)
        face_width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
        if motion is None:
            pad = 1.0
        else:
            reach = float(np.linalg.norm(placed - placed.mean(axis=0), axis=1).max())
            pad = (2 * ssj_motion.MAX_TIP_LAG + motion.flutter) * face_width + abs(motion.roll) * reach + 2.0
        x0, y0, x1, y1 = _box(placed, pad, shape)
        if x1 <= x0 or y1 <= y0:
            return None
        if motion is None:
            shifted = matrix.copy()
            shifted[:, 2] -= (x0, y0)
            warped = cv2.warpAffine(view.rgba, shifted, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        else:
            up = face[FOREHEAD_TOP] - face[CHIN]
            pivot = face[FOREHEAD_TOP] + up * 0.15  # A little above the hairline.
            map_x, map_y = ssj_motion.hair_warp_maps(
                matrix, self._root_weights(view), (x0, y0, x1, y1), pivot, motion.offset * face_width,
                motion.roll, motion.flutter * face_width, t)
            warped = cv2.remap(view.rgba, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(0, 0, 0, 0))
        return PlacedHair(warped, (x0, y0, x1, y1))

    def place(self, face: np.ndarray | None, shape) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
        """The hair warped onto this face: BGRA patch and its (x0, y0, x1, y1) box in the frame (rigid, stateless)."""
        if not self.views or not usable_face(face):
            return None
        placed = self._warp(self.pick(face), face, shape)
        return None if placed is None else (placed.rgba, placed.box)

    def place_live(self, face: np.ndarray | None, shape, t: float,
                   motion: ssj_motion.HairMotion | None = None, yaw: float | None = None) -> PlacedHair | None:
        """The hair for this frame: view switching with a fade, and the tips moved by `motion`."""
        if not self.views or not usable_face(face):
            return None
        layers = []
        for view, weight in self.select(face_yaw(face) if yaw is None else yaw, t):
            placed = self._warp(view, face, shape, motion, t)
            if placed is not None:
                layers.append((placed, weight))
        if not layers:
            return None
        if len(layers) == 1:
            return layers[0][0]
        return _blend(layers)

    def mask(self, face: np.ndarray | None, shape) -> np.ndarray | None:
        """Where the hair covers the frame, 0-1, so the aura can surround it."""
        placed = self.place(face, shape)
        return None if placed is None else self.mask_from(PlacedHair(*placed), shape)

    @staticmethod
    def mask_from(placed: PlacedHair, shape) -> np.ndarray:
        x0, y0, x1, y1 = placed.box
        mask = np.zeros(shape[:2], np.float32)
        mask[y0:y1, x0:x1] = placed.rgba[:, :, 3] / np.float32(255.0)
        return mask

    def render(self, frame: np.ndarray, face: np.ndarray | None, strength: float) -> np.ndarray:
        if strength <= 0.0:
            return frame
        placed = self.place(face, frame.shape)
        return frame if placed is None else self.render_placed(frame, PlacedHair(*placed), strength)

    @staticmethod
    def render_placed(frame: np.ndarray, placed: PlacedHair, strength: float) -> np.ndarray:
        if strength <= 0.0:
            return frame
        x0, y0, x1, y1 = placed.box
        alpha = placed.rgba[:, :, 3].astype(np.float32) * (min(1.0, strength) / 255.0)
        if not alpha.any():
            return frame
        result = frame.copy()
        area = result[y0:y1, x0:x1]
        result[y0:y1, x0:x1] = cv2.blendLinear(area, np.ascontiguousarray(placed.rgba[:, :, :3]), 1.0 - alpha, alpha)
        return result


def _blend(layers: list[tuple[PlacedHair, float]]) -> PlacedHair:
    """Two pictures cross-faded in the union of their boxes (colors weighted by alpha)."""
    x0 = min(placed.box[0] for placed, _ in layers)
    y0 = min(placed.box[1] for placed, _ in layers)
    x1 = max(placed.box[2] for placed, _ in layers)
    y1 = max(placed.box[3] for placed, _ in layers)
    color = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
    alpha = np.zeros((y1 - y0, x1 - x0), np.float32)
    for placed, weight in layers:
        bx0, by0, bx1, by1 = placed.box
        area = np.s_[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0]
        a = placed.rgba[:, :, 3].astype(np.float32) * (weight / 255.0)
        color[area] += placed.rgba[:, :, :3].astype(np.float32) * a[:, :, None]
        alpha[area] += a
    rgba = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    rgba[:, :, :3] = np.clip(color / np.maximum(alpha, 1e-6)[:, :, None], 0, 255).astype(np.uint8)
    rgba[:, :, 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return PlacedHair(rgba, (x0, y0, x1, y1))


def render_face(frame: np.ndarray, face: np.ndarray | None, strength: float,
                hair: HairOverlay | None = None, eyes: bool = True, brows: bool = True,
                placed: PlacedHair | None = None) -> np.ndarray:
    """Brows, eyes, then the hair on top (it may cover the brows, like a fringe).

    `eyes` / `brows` off: for people who already have green eyes or fair eyebrows. `placed` is the hair already
    placed for this frame (with its motion); without it the hair is fitted rigidly here.
    """
    if strength <= 0.0 or face is None:
        return frame
    output = tint_brows(frame, face, strength) if brows else frame
    output = tint_eyes(output, face, strength) if eyes else output
    if placed is not None:
        output = HairOverlay.render_placed(output, placed, strength)
    elif hair is not None:
        output = hair.render(output, face, strength)
    return output