"""Super Saiyan transformation: charge-ki pose, yellow aura and sounds."""

from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    from . import ssj_face
except ImportError:
    import ssj_face


CHARGE_SECONDS = 1.5
FLASH_SECONDS = 0.45
POWER_DOWN_SECONDS = 0.6
AURA_SCALE = 0.5
# Sizes below are in pixels at AURA_SCALE (half resolution).
AURA_RADIUS = 10.0
FLAME_RISE = 4.5  # How far the flames climb above the body, in radii.
GLOW = 0.55  # Soft additive light around the cel shapes: makes them read as light, not paint.
MAX_RADIUS_SCALE = 2.5 * 1.15  # Flash radius times the pulse: sizes the crop.
RIM_WIDTH = 6.0
RIM_ALPHA = 0.45
DARKEN = 0.28  # Surroundings at full power.

# Static furniture (a high-back chair) that the segmenter calls "person": above this line, in face heights over
# the chin (about the eyes), only the head is the person.
EYE_LINE = 0.6
# Below the line the allowed width grows from the head's this much per pixel down, so a chair is cut along a
# shoulder-like slope instead of a flat shelf (which the aura turned into a box). Steep: shoulders are never cut.
BODY_SLOPE = 3.0

# Face Landmarker.
NOSE, CHIN, FOREHEAD_TOP = 1, 152, 10
FACE_LEFT, FACE_RIGHT = 234, 454

# Cel shading: (start of the tone in the flame field, BGR color, opacity).
AURA_TONES = ((0.22, (0, 190, 255), 0.4), (0.45, (20, 230, 255), 0.65), (0.72, (170, 255, 255), 0.9))
RIM_COLOR = (120, 235, 255)
HALO_COLOR = (40, 200, 255, 0)  # BGR(A) for cv2.multiply with a scalar.

# Aura styles: "classic" (scrolling noise around a distance ring, the default) and "contour" (a procedural flame
# strip mapped along the outline by arc length; off by default until the owner approves it).
AURA_STYLES = ("classic", "contour")
# Contour flames. The strip is one horizontally tileable tile: columns run along the outline, rows away from it.
STRIP_WIDTH = 256
STRIP_HEIGHT = 48  # Rows from the outline (row 0) to the tip of the tallest tongue.
STRIP_TONGUES = 6  # Flame tongues per tile.
STRIP_BASE = 0.38  # Height of the band between the tongues, as a fraction of STRIP_HEIGHT.
CONTOUR_TILE = 180.0  # Outline length of one tile, in pixels at AURA_SCALE.
CONTOUR_REACH = 6.0 * AURA_RADIUS  # Tallest tongue on a vertical side, at AURA_SCALE and radius scale 1.
CONTOUR_FLASH = 0.5  # Share of the flash radius growth the tongues follow (they are already long).
CONTOUR_LEAN = 0.5  # Upward shear: flames lean up on the sides and are 1 / (1 - lean) taller on top.


def _tone_luts(tones, edge: float = 0.025) -> tuple[np.ndarray, np.ndarray]:
    """Flat tones with short anti-aliased steps, indexed by the field (0-255)."""
    x = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    # Start from the first tone: the anti-aliased edge must not fade through black.
    colors = np.tile(np.array(tones[0][1], np.float32), (256, 1))
    alpha = np.zeros(256, np.float32)
    for start, color, opacity in tones:
        step = np.clip((x - start) / edge, 0.0, 1.0)[:, None]
        colors = colors * (1.0 - step) + np.array(color, np.float32) * step
        alpha = np.maximum(alpha, step[:, 0] * opacity)
    return colors.astype(np.uint8), alpha


TONE_COLORS, TONE_ALPHA = _tone_luts(AURA_TONES)
# Index 255 is reserved for the inside of the silhouette: rim color, no aura.
COLOR_LUT = TONE_COLORS.copy()
COLOR_LUT[255] = RIM_COLOR
COLOR_LUT = COLOR_LUT.reshape(1, 256, 3)
ALPHA_LUT = TONE_ALPHA.copy()
ALPHA_LUT[255] = 0.0


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


# ---------- silhouette ----------

HAND_PAD = 1.35  # Hand hull scaled around its centre: covers the fingertips and the edge of the palm.


def hands_mask(hands, segmenter: np.ndarray) -> np.ndarray | None:
    """The detected hands, where the segmenter sees the person: part of the silhouette even above the eyes.

    Raised fists (the charge pose, to power down) are outside the head ellipse; without this the aura
    painted over them and the user could not see their own hands.
    """
    height, width = segmenter.shape[:2]
    mask = np.zeros((height, width), np.float32)
    for hand in hands:
        if len(hand) != 21:
            continue
        points = _points(hand, width, height)
        if not np.isfinite(points).all():
            continue
        centre = points.mean(axis=0)
        hull = cv2.convexHull(((points - centre) * HAND_PAD + centre).astype(np.int32))
        cv2.fillConvexPoly(mask, hull, 1.0, cv2.LINE_AA)
    if not mask.any():
        return None
    return np.minimum(mask, segmenter)

def head_ellipse(faces, width: int, height: int):
    """Head and hair around the first face as ((cx, cy), (rx, ry), angle) in pixels, or None."""
    if not faces:
        return None
    return head_ellipse_from_points(_points(faces[0], width, height))


def head_ellipse_from_points(face: np.ndarray | None):
    """`head_ellipse` for face points already in pixels (the tracked face)."""
    if face is None or face.shape[0] <= max(FACE_RIGHT, CHIN) or not np.isfinite(face).all():
        return None
    top, chin = face[FOREHEAD_TOP], face[CHIN]
    face_height = float(np.linalg.norm(chin - top))
    face_width = float(np.linalg.norm(face[FACE_RIGHT] - face[FACE_LEFT]))
    if face_height < 10.0 or face_width < 10.0:
        return None
    up = (top - chin) / face_height
    # Shifted up and enlarged: the hair sits above the forehead landmark.
    center = (top + chin) * 0.5 + up * 0.15 * face_height
    angle = math.degrees(math.atan2(float(up[0]), float(-up[1])))
    return ((int(round(center[0])), int(round(center[1]))),
            (int(round(0.8 * face_width)), int(round(0.85 * face_height))), angle)


def body_region(head, size: tuple[int, int], scale: tuple[float, float]) -> np.ndarray:
    """Where the person can be: the head ellipse, and below the eye line a region that widens fast.

    `size` is (width, height) of the output grid and `scale` maps frame pixels to it. Returns uint8 0/1.
    """
    (cx, cy), (rx, ry), angle = head
    fx, fy = scale
    face_height = ry / 0.85  # Inverse of head_ellipse.
    up = (math.sin(math.radians(angle)), -math.cos(math.radians(angle)))
    # head_ellipse is centred 0.65 face heights above the chin.
    line = (cx - up[0] * (0.65 - EYE_LINE) * face_height, cy - up[1] * (0.65 - EYE_LINE) * face_height)
    xs = (np.arange(size[0], dtype=np.float32) + 0.5) / fx - line[0]
    ys = (np.arange(size[1], dtype=np.float32) + 0.5) / fy - line[1]
    below = -(ys[:, None] * up[1] + xs[None, :] * up[0])
    across = np.abs(xs[None, :] * -up[1] + ys[:, None] * up[0])
    region = ((below >= 0) & (across <= rx + BODY_SLOPE * below)).astype(np.uint8)
    cv2.ellipse(region, (int(round(cx * fx)), int(round(cy * fy))),
                (max(1, int(round(rx * fx))), max(1, int(round(ry * fy)))), angle, 0, 360, 1, -1)
    return region


def refine_person_mask(mask: np.ndarray, head) -> np.ndarray:
    """Drop the high-back chair the segmenter calls "person" around the head.

    Above the eye line only the head ellipse is kept; below it the mask is untouched, so the body is
    never cut (aura painted on it otherwise). Earlier versions used the calibrated background photo,
    which failed in a dark room, with a swivel chair that moves, with a black hoodie in front of a
    black chair, and with a close webcam that sees the shoulders above the chin. Unchanged without a face.
    """
    if head is None:
        return mask
    height, width = mask.shape
    size = (max(8, width // 4), max(8, height // 4))
    allowed = body_region(head, size, (size[0] / width, size[1] / height))
    soft = cv2.GaussianBlur(allowed.astype(np.float32), (0, 0), 1.5)
    return np.minimum(mask, cv2.resize(soft, (width, height), interpolation=cv2.INTER_LINEAR))


# ---------- aura ----------

@dataclass
class AuraGeometry:
    """Everything that only depends on the person mask, recomputed when a new mask arrives."""
    area: tuple
    inside_full: np.ndarray  # Person pixels inside the crop at full resolution: never darkened.
    person: np.ndarray  # Refined mask inside the crop, at AURA_SCALE.
    inside: np.ndarray  # Boolean version of `person`.
    inside_index: np.ndarray  # 255 inside the person, 0 outside: selects the rim entry of the LUTs.
    aura_weight: np.ndarray  # Where the aura may paint: outside the person, softened at the edge.
    outside_distance: np.ndarray
    rim: np.ndarray  # Rim light opacity at full power.
    fade: np.ndarray
    edge: np.ndarray  # Contour points, for the sparks.
    origin: tuple  # Crop corner at AURA_SCALE: noise is sampled in frame coordinates.
    strip_x: np.ndarray | None = None  # Contour style: strip column (arc length along the outline) per pixel.
    strip_y: np.ndarray | None = None  # Contour style: strip row at radius scale 1 (distance from the outline).


def contour_scale(radius_scale: float) -> float:
    """Tongue length factor for a radius scale (the flash grows the aura)."""
    return 1.0 + (radius_scale - 1.0) * CONTOUR_FLASH


def contour_strip_maps(binary: np.ndarray, distance: np.ndarray, contours) -> tuple[np.ndarray, np.ndarray]:
    """Where each pixel samples the flame strip: column from the arc length of its nearest outline point, row from
    its distance to the outline.

    Each outline is cut into a whole number of tiles, so the strip wraps around it without a seam. The maps are
    sheared upward (`CONTOUR_LEAN`): a pixel takes the strip coordinates of a point below it, so the flames lean up on
    the sides and grow taller above the head and shoulders.
    """
    rows, cols = binary.shape
    seeds = np.ones((rows, cols), np.uint8)
    for contour in contours:
        points = contour.reshape(-1, 2)
        seeds[points[:, 1], points[:, 0]] = 0
    # Every pixel gets the label of its nearest outline pixel; a seed pixel keeps its own label.
    _, labels = cv2.distanceTransformWithLabels(seeds, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    column_of = np.zeros(int(labels.max()) + 1, np.float32)
    for contour in contours:
        points = contour.reshape(-1, 2)
        steps = np.linalg.norm(np.diff(points, axis=0, append=points[:1]), axis=1)
        length = float(steps.sum())
        if length <= 0.0:
            continue
        arc = np.concatenate(([0.0], np.cumsum(steps)[:-1]))
        tiles = max(1, int(round(length / CONTOUR_TILE)))
        column_of[labels[points[:, 1], points[:, 0]]] = (arc / length * tiles * STRIP_WIDTH) % STRIP_WIDTH
    columns = column_of[labels]
    xs = np.tile(np.arange(cols, dtype=np.float32), (rows, 1))
    ys = np.arange(rows, dtype=np.float32)[:, None] + np.float32(CONTOUR_LEAN) * distance
    ys = np.minimum(ys, np.float32(rows - 1))
    # The column wraps: interpolate it as an angle (cos, sin), or the wrap would sweep through the whole strip.
    angle = columns * np.float32(2 * math.pi / STRIP_WIDTH)
    cos = cv2.remap(np.cos(angle), xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    sin = cv2.remap(np.sin(angle), xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    strip_x = cv2.phase(cos, sin) * np.float32(STRIP_WIDTH / (2 * math.pi))
    strip_y = cv2.remap(distance, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return strip_x, strip_y * np.float32(STRIP_HEIGHT / CONTOUR_REACH)


class AuraRenderer:
    """Cel-shaded aura with rising flame tongues, rim light and darker surroundings.

    The aura is painted outside the silhouette only; inside it there is just a thin band of light
    along the edge. The geometry is cached per mask (10 Hz) and the flames move every frame.
    `style="contour"` maps a procedural flame strip along the outline instead of the scrolling noise
    (`contour_strip_maps`, `strip`); the rim light, darkening, sparks and glow are the same.
    """

    def __init__(self, seed: int = 77, sparks: int = 36, style: str = "classic"):
        if style not in AURA_STYLES:
            raise ValueError(f"Unknown aura style {style!r}: use one of {', '.join(AURA_STYLES)}")
        self.style = style
        rng = np.random.default_rng(seed)
        self.noise = []
        for rows, cols in ((6, 28), (10, 44)):
            # Much taller than wide: big vertical tongues of fire, with a little fine detail.
            coarse = cv2.resize(rng.random((rows, cols), dtype=np.float32), (256, 256), interpolation=cv2.INTER_CUBIC)
            fine = cv2.resize(rng.random((32, 96), dtype=np.float32), (256, 256), interpolation=cv2.INTER_CUBIC)
            self.noise.append(np.clip(coarse * 0.8 + fine * 0.2, 0.0, 1.0))
        self.sparks = sparks
        # Per spark and cycle: edge point, sideways drift, rise speed, size. Cycles repeat after 64.
        self.spark_table = np.random.default_rng(seed + 1).random((sparks, 64, 4))
        if style == "contour":
            self._init_strip(np.random.default_rng(seed + 2))
        self.geometry_updates = 0
        self._mask: np.ndarray | None = None
        self._geometry: AuraGeometry | None = None

    def geometry(self, frame: np.ndarray, mask: np.ndarray, head=None, extra=None,
                 cover=None) -> AuraGeometry | None:
        """`extra` returns more body (the hands) and `cover` what the aura must go around without treating it as
        the body (the golden hair: the room behind its see-through tips is darkened and gets no rim light, or it
        shows as pale patches). Both are called only when a new mask arrives."""
        if mask is not self._mask:
            self._mask = mask
            self._geometry = self._prepare(frame, mask, head, extra, cover)
            self.geometry_updates += 1
        return self._geometry

    def _prepare(self, frame, mask, head, extra=None, cover=None) -> AuraGeometry | None:
        body = refine_person_mask(mask, head).astype(np.float32)
        added = extra() if extra is not None else None
        if added is not None:
            body = np.maximum(body, added)
        covered = cover() if cover is not None else None
        refined = body if covered is None else np.maximum(body, covered)
        x, y, w, h = cv2.boundingRect((refined > 0.3).astype(np.uint8))
        if w <= 0 or h <= 0:
            return None
        height, width = refined.shape
        reach = AURA_RADIUS * MAX_RADIUS_SCALE
        side = int(math.ceil((2.3 * reach + 2) / AURA_SCALE))
        rise = int(math.ceil(FLAME_RISE * reach / AURA_SCALE))
        if self.style == "contour":
            # The tallest tongue at the flash radius, on the sides and (sheared up) above the head.
            tongue = CONTOUR_REACH * contour_scale(MAX_RADIUS_SCALE)
            side = max(side, int(math.ceil((tongue + 10) / AURA_SCALE)))
            rise = max(rise, int(math.ceil(tongue / (1.0 - CONTOUR_LEAN) / AURA_SCALE)) - side)
        left, top = max(0, x - side), max(0, y - side - rise)
        right, bottom = min(width, x + w + side), min(height, y + h + side)
        small_size = (max(2, int((right - left) * AURA_SCALE)), max(2, int((bottom - top) * AURA_SCALE)))
        person = cv2.resize(refined[top:bottom, left:right], small_size, interpolation=cv2.INTER_AREA)
        inside = person > 0.5
        binary = inside.astype(np.uint8)
        outside_distance = cv2.distanceTransform(1 - binary, cv2.DIST_L2, 3)
        body_small = person if covered is None else cv2.resize(body[top:bottom, left:right], small_size,
                                                               interpolation=cv2.INTER_AREA)
        body_inside = body_small > 0.5
        inside_distance = cv2.distanceTransform(body_inside.astype(np.uint8), cv2.DIST_L2, 3)
        rim = np.clip(1.0 - inside_distance / RIM_WIDTH, 0.0, 1.0) ** 2 * body_inside
        # The light comes from the aura around: stronger at the top of the body.
        rim *= np.linspace(1.0, 0.4, rim.shape[0], dtype=np.float32)[:, None]
        # Fade out before the crop border, except where the crop is the frame border.
        fade = np.ones_like(person)
        ramp = 8
        rows, cols = fade.shape
        steps = np.linspace(0.0, 1.0, ramp, dtype=np.float32)
        if left > 0:
            fade[:, :ramp] *= steps[None, :min(ramp, cols)]
        if right < width:
            fade[:, -ramp:] *= steps[::-1][None, -min(ramp, cols):]
        if top > 0:
            fade[:ramp] *= steps[:min(ramp, rows), None]
        # The body continues below the frame: soften the bottom instead of a flat bar of fire.
        fade[-min(ramp * 2, rows):] *= np.linspace(1.0, 0.0, min(ramp * 2, rows), dtype=np.float32)[:, None]
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        edge = (np.concatenate([contour.reshape(-1, 2) for contour in contours])
                if contours else np.zeros((0, 2), np.int32))
        strip_x = strip_y = None
        if self.style == "contour" and contours:
            strip_x, strip_y = contour_strip_maps(binary, outside_distance, contours)
        return AuraGeometry(
            area=np.s_[top:bottom, left:right], inside_full=body[top:bottom, left:right] > 0.5,
            person=person, inside=inside, inside_index=binary * np.uint8(255),
            aura_weight=((1.0 - person) * ~inside).astype(np.float32),
            outside_distance=outside_distance, rim=(rim * RIM_ALPHA).astype(np.float32), fade=fade,
            edge=edge, origin=(int(left * AURA_SCALE), int(top * AURA_SCALE)), strip_x=strip_x, strip_y=strip_y,
        )

    def _init_strip(self, rng: np.random.Generator) -> None:
        """Fixed shape of the contour flame strip: tongue positions, sizes and flicker, and a tileable detail noise."""
        self.strip_columns = (np.arange(STRIP_WIDTH, dtype=np.float32) + 0.5) / STRIP_WIDTH
        tongues = STRIP_TONGUES
        self.tongue_center = (np.arange(tongues) + 0.5 + rng.uniform(-0.25, 0.25, tongues)) / tongues
        self.tongue_width = rng.uniform(0.7, 1.1, tongues)  # Half width, in tongue spacings.
        self.tongue_height = rng.uniform(0.6, 1.0, tongues)
        self.tongue_rate = rng.uniform(1.6, 3.4, tongues)  # Flicker, Hz.
        self.tongue_phase = rng.random(tongues)
        # Detail noise that tiles in both directions (whole cycles of a tiled grid): streaks along the flames.
        grid_rows, grid_cols, factor = 4, 32, 16
        grid = np.tile(rng.random((grid_rows, grid_cols), dtype=np.float32), (3, 3))
        big = cv2.resize(grid, (3 * STRIP_WIDTH, 3 * grid_rows * factor), interpolation=cv2.INTER_CUBIC)
        self.strip_noise = big[grid_rows * factor:2 * grid_rows * factor, STRIP_WIDTH:2 * STRIP_WIDTH]

    def strip(self, t: float) -> np.ndarray:
        """The flame strip at time `t`: field 0-1, bright at the outline (row 0), pointed tongues that flicker and
        detail that flows outward. One extra column (a copy of the first) lets `cv2.remap` wrap without a seam; the
        rows past the tips are 0."""
        tongues = STRIP_TONGUES
        flicker = 0.7 + 0.3 * np.sin(2 * math.pi * (self.tongue_rate * t + self.tongue_phase))
        sway = 0.12 * np.sin(2 * math.pi * (0.5 * self.tongue_rate * t + 2 * self.tongue_phase))
        offset = (self.strip_columns[None, :] - (self.tongue_center + sway / tongues)[:, None] + 0.5) % 1.0 - 0.5
        across = np.abs(offset) * tongues / self.tongue_width[:, None]
        # Concave sides: pointed tips, like hand-drawn flames.
        bumps = (self.tongue_height * flicker)[:, None] * np.clip(1.0 - across, 0.0, 1.0) ** 1.6
        height = np.maximum(np.float32(STRIP_BASE), bumps.max(axis=0)).astype(np.float32)
        rows = np.arange(STRIP_HEIGHT, dtype=np.float32)[:, None] / STRIP_HEIGHT
        shape = np.clip(1.0 - rows / height[None, :], 0.0, 1.0)
        size = self.strip_noise.shape[0]
        flow = (np.arange(STRIP_HEIGHT) - int(t * 90.0)) % size  # The detail moves away from the body.
        field = np.zeros((STRIP_HEIGHT + 1, STRIP_WIDTH + 1), np.float32)
        # The detail grows away from the outline: the core next to the body stays solid.
        detail = (self.strip_noise[flow] - 0.5) * np.minimum(1.0, rows * 4.0) * 0.8
        field[:STRIP_HEIGHT, :STRIP_WIDTH] = np.clip(shape * (1.0 + detail), 0.0, 1.0)
        field[:, STRIP_WIDTH] = field[:, 0]
        return field

    def _contour_field(self, geometry: AuraGeometry, t: float, radius_scale: float) -> np.ndarray:
        if geometry.strip_x is None:
            return np.zeros_like(geometry.person)
        scale = contour_scale(radius_scale) * (1.0 + 0.12 * math.sin(2 * math.pi * 3.0 * t))
        rows = geometry.strip_y * np.float32(1.0 / scale)
        return cv2.remap(self.strip(t), geometry.strip_x, rows, cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=0)

    def _noise(self, geometry: AuraGeometry, t: float) -> np.ndarray:
        rows, cols = geometry.person.shape
        left, top = geometry.origin
        layers = []
        for texture, speed in zip(self.noise, (140.0, 230.0)):
            size = texture.shape[0]
            offset = int(t * speed)  # The texture scrolls up: the flames rise.
            row_index = (top + np.arange(rows) + offset) % size
            col_index = (left + np.arange(cols)) % size
            layers.append(texture[np.ix_(row_index, col_index)])
        return layers[0] * 0.6 + layers[1] * 0.4

    def render(self, frame: np.ndarray, mask: np.ndarray | None, intensity: float, t: float,
               radius_scale: float = 1.0, head=None, extra=None, cover=None) -> np.ndarray:
        if mask is None or intensity <= 0.0:
            return frame
        geometry = self.geometry(frame, mask, head, extra, cover)
        if geometry is None:
            return frame
        power = min(1.0, intensity)

        # Darker surroundings: what gives the aura its contrast, even on a light wall.
        result = cv2.convertScaleAbs(frame, alpha=1.0 - DARKEN * power)
        area = geometry.area
        np.copyto(result[area], frame[area], where=geometry.inside_full[:, :, None])

        if self.style == "contour":
            field = self._contour_field(geometry, t, radius_scale) * (geometry.fade * np.float32(255.0 * intensity))
        else:
            radius = AURA_RADIUS * radius_scale * (1.0 + 0.12 * math.sin(2 * math.pi * 3.0 * t))
            ring = cv2.exp(geometry.outside_distance * np.float32(-1.0 / radius))
            # The flames rise: each row takes light from the rows below (two boxes ~ a decaying kernel).
            rows = max(2, int(FLAME_RISE * radius))
            rising = (cv2.blur(ring, (1, rows), anchor=(0, 0), borderType=cv2.BORDER_REPLICATE)
                      + cv2.blur(ring, (1, max(2, rows // 2)), anchor=(0, 0),
                                 borderType=cv2.BORDER_REPLICATE)) * 0.5
            ring = np.maximum(ring, rising * 1.6)
            field = ring * (self._noise(geometry, t) * 1.3 + 0.1) * (geometry.fade * np.float32(255.0 * intensity))
        index = np.clip(field, 0, 254).astype(np.uint8)
        # Inside the silhouette there is only the rim light (LUT entry 255).
        index = cv2.max(index, geometry.inside_index)
        color = cv2.LUT(cv2.merge((index, index, index)), COLOR_LUT)
        alpha = ALPHA_LUT[index] * geometry.aura_weight + geometry.rim * np.float32(power)
        self._draw_sparks(color, alpha, geometry, t, power)
        # A soft halo of light around the flat shapes, kept off the person like the aura.
        glow = cv2.GaussianBlur(alpha, (0, 0), 4.0) * geometry.aura_weight * np.float32(GLOW * 255.0 * power)
        glow = np.clip(glow, 0, 255).astype(np.uint8)
        halo = cv2.multiply(cv2.merge((glow, glow, glow)), HALO_COLOR, scale=1.0 / 255.0)

        roi = result[area]
        size = (roi.shape[1], roi.shape[0])
        color = cv2.resize(color, size, interpolation=cv2.INTER_LINEAR)
        alpha = cv2.resize(alpha, size, interpolation=cv2.INTER_LINEAR)
        halo = cv2.resize(halo, size, interpolation=cv2.INTER_LINEAR)
        result[area] = cv2.add(cv2.blendLinear(roi, color, 1.0 - alpha, alpha), halo)
        return result

    def _draw_sparks(self, color: np.ndarray, alpha: np.ndarray, geometry: AuraGeometry, t: float,
                     power: float) -> None:
        edge = geometry.edge
        if not len(edge):
            return
        life = 0.45
        shifted = t + np.arange(self.sparks) * life / self.sparks
        cycle = (shifted // life).astype(int) % self.spark_table.shape[1]
        ages = (shifted % life) / life
        pick, drift, speed, size = self.spark_table[np.arange(self.sparks), cycle].T
        points = edge[(pick * len(edge)).astype(int)]
        xs = (points[:, 0] + drift * 12.0 - 6.0).astype(int)
        ys = (points[:, 1] - (120.0 + 140.0 * speed) * AURA_SCALE * ages * life).astype(int)
        rows, cols = alpha.shape
        spark_color = AURA_TONES[-1][1]
        for x, y, small, age in zip(xs, ys, size, ages):
            if not (0 <= x < cols and 0 <= y < rows) or geometry.inside[y, x]:
                continue
            center, radius = (int(x), int(y)), 1 if small < 0.5 else 2
            cv2.circle(color, center, radius, spark_color, -1, cv2.LINE_AA)
            cv2.circle(alpha, center, radius, float((1.0 - age) * power), -1, cv2.LINE_AA)


# ---------- transformation state ----------

@dataclass
class PowerLevels:
    aura: float = 0.0
    flash: float = 0.0
    shake: float = 0.0
    radius: float = 1.0
    hair: float = 0.0  # Golden hair, teal eyes and golden brows.


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
            # Late in the charge the hair and eyes flicker between normal and golden, like in the series.
            hair = 0.9 if charge >= 0.45 and int(age * 12.0) % 2 == 0 else 0.0
            return PowerLevels(aura=0.6 * charge, shake=2.0 + 6.0 * charge, hair=hair)
        if self.phase == "flash":
            progress = min(1.0, age / FLASH_SECONDS)
            flash = 0.9 * age / 0.08 if age < 0.08 else 0.9 * math.exp(-(age - 0.08) * 8.0)
            return PowerLevels(aura=1.0, flash=flash, shake=6.0 * (1.0 - progress),
                               radius=2.5 - 1.5 * progress, hair=1.0)
        if self.phase == "super":
            return PowerLevels(aura=1.0, hair=1.0)
        if self.phase == "powering_down":
            left = max(0.0, 1.0 - age / POWER_DOWN_SECONDS)
            return PowerLevels(aura=left, hair=left)
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
                        levels: PowerLevels, t: float, aura: AuraRenderer | None, head=None,
                        face: np.ndarray | None = None, hair: ssj_face.HairOverlay | None = None,
                        hands=(), eyes: bool = True, brows: bool = True,
                        placed: ssj_face.PlacedHair | None = None) -> np.ndarray:
    """`hands` are the latest hand landmarks (normalized), kept out of the aura. `placed` is the hair already
    placed for this frame (with its motion): the aura and the drawing then share it instead of fitting it twice.
    """
    output = frame
    if aura is not None and mask is not None:
        def extra() -> np.ndarray | None:
            return hands_mask(hands, mask)  # The hands are body: never painted over.

        def cover() -> np.ndarray | None:
            # The golden hair, once it is in: the flames rise from the spikes instead of being covered by them.
            if levels.hair < 0.5:
                return None
            if placed is not None:
                return ssj_face.HairOverlay.mask_from(placed, frame.shape)
            return hair.mask(face, frame.shape) if hair is not None and face is not None else None
        output = aura.render(output, mask, levels.aura, t, levels.radius, head, extra, cover)
    # Eyes, brows and the imported hair, on top of the aura (spikes may stick out of the silhouette).
    output = ssj_face.render_face(output, face, levels.hair, hair, eyes, brows, placed)
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
