"""Local webcam with disappearance effects: Dragon Ball, V (dissolve) and Naruto."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from contextlib import ExitStack
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

try:
    from . import dragonball_effect as dragonball
    from . import super_saiyan_effect as ssj
    from .naruto_effect import (
        EFFECT_SECONDS, REAPPEAR_SECONDS, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_reappearance, render_substitution, substitution_anchor,
    )
    from .vanish_sound import SOUND_PATH, VanishSound
except ImportError:
    import dragonball_effect as dragonball
    import super_saiyan_effect as ssj
    from naruto_effect import (
        EFFECT_SECONDS, REAPPEAR_SECONDS, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_reappearance, render_substitution, substitution_anchor,
    )
    from vanish_sound import SOUND_PATH, VanishSound


APP_DIR = Path(__file__).resolve().parent
MODEL_DIR = APP_DIR / "models"
WINDOW_NAME = "VanishCam - Preview"

SEGMENTER_MODEL = MODEL_DIR / "selfie_segmenter_landscape.tflite"
GESTURE_MODEL = MODEL_DIR / "gesture_recognizer.task"
HAND_MODEL = APP_DIR / "hand_landmarker.task"
FACE_MODEL = APP_DIR / "face_landmarker.task"
TELEPORT_SOUND_FILES = (APP_DIR / "assets" / "teleport.MP3", MODEL_DIR / "teleport.wav")
# Multiclass segmentation (class 1 = hair) for the Super Saiyan's golden hair.
MULTICLASS_MODEL = MODEL_DIR / "selfie_multiclass_256x256.tflite"
SSJ_SOUNDS = {
    "ssj_charge": ssj.write_charge_sound,
    "ssj_transform": ssj.write_transform_sound,
    "ssj_aura": ssj.write_aura_hum,
}

MODEL_URLS = {
    MULTICLASS_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_multiclass_256x256/float32/1/selfie_multiclass_256x256.tflite"
    ),
    SEGMENTER_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/image_segmenter/"
        "selfie_segmenter_landscape/float16/1/"
        "selfie_segmenter_landscape.tflite"
    ),
    GESTURE_MODEL: (
        "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
        "gesture_recognizer/float16/1/gesture_recognizer.task"
    ),
}
# Hashes of the verified official models: a download that differs is discarded.
MODEL_SHA256 = {
    "selfie_segmenter_landscape.tflite": "490e9ea734313e0de10fa0cd9e3c6133e36ea4db2b7a49bde9ef019f72796b8e",
    "gesture_recognizer.task": "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482",
    "selfie_multiclass_256x256.tflite": "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0",
}

MODES = ("dragonball", "normal", "naruto")
MODE_ALIASES = {"goku": "dragonball"}
DEFAULT_MODE = "dragonball"

CALIBRATION_SECONDS = 4.0
# Background samples are taken during the last 1.5 s, every other frame.
BACKGROUND_SAMPLE_SECONDS = 1.5
BACKGROUND_MAX_SAMPLES = 24
PERSON_CHECK_SECONDS = 0.3
PERSON_AREA_LIMIT = 0.02
CALIBRATION_RETRY_SECONDS = 2.0
MAX_CALIBRATION_RETRIES = 3
VANISH_SECONDS = 3.6
APPEAR_SECONDS = 1.8
GESTURE_INTERVAL_SECONDS = 0.14
FAST_GESTURE_INTERVAL_SECONDS = 0.08
# The gesture must be held: avoids accidental vanishing while talking.
HOLD_SECONDS = {"normal": 0.3, "naruto": 0.3, "dragonball": dragonball.HOLD_SECONDS}
# A single missed frame does not reset the held-gesture count.
GESTURE_GRACE_SECONDS = 0.25


@dataclass
class AppState:
    phase: str = "calibrating"
    calibration_started: float = 0.0
    vanish_started: float | None = None
    last_gesture_check: float = 0.0
    fullscreen: bool = False


@dataclass
class GestureHold:
    """Fires when the gesture stays active for hold_seconds.

    After it fires, the hand must be lowered before it can fire again: the same
    gesture makes the person vanish and then reappear without retriggering itself.
    """
    hold_seconds: float
    grace_seconds: float = GESTURE_GRACE_SECONDS
    since: float | None = None
    last_seen: float | None = None
    armed: bool = True

    def update(self, active: bool, now: float) -> bool:
        if active:
            self.last_seen = now
            if not self.armed:
                return False
            if self.since is None:
                self.since = now
            if now - self.since >= self.hold_seconds:
                self.since = None
                self.armed = False
                return True
            return False
        if self.last_seen is None or now - self.last_seen > self.grace_seconds:
            self.since = None
            self.armed = True
        return False

    def reset(self) -> None:
        self.since = None
        self.last_seen = None
        self.armed = True


def positive_fps(value: str) -> float:
    fps = float(value)
    if not np.isfinite(fps) or not 1 <= fps <= 120:
        raise argparse.ArgumentTypeError("FPS must be between 1 and 120.")
    return fps


def camera_source(value: str) -> int | str:
    """Webcam index (0, 1...) or a path such as /dev/video0 on Linux."""
    return int(value) if value.isdigit() else value


def find_linux_cameras(sysfs: Path = Path("/sys/class/video4linux")) -> list[str]:
    """Real webcams, excluding v4l2loopback virtual outputs.

    USB webcams often expose two nodes (video + metadata): only the one with
    index 0 is kept. v4l2loopback devices live in /sys/devices/virtual.
    """
    cameras = []
    for node in sorted(sysfs.glob("video*"), key=lambda path: int(path.name[5:] or 0)):
        try:
            if "virtual" in node.resolve().parts:
                continue
            if (node / "index").read_text().strip() != "0":
                continue
        except (OSError, ValueError):
            continue
        cameras.append(f"/dev/{node.name}")
    return cameras


def mode_name(value: str) -> str:
    mode = MODE_ALIASES.get(value.lower(), value.lower())
    if mode not in MODES:
        raise argparse.ArgumentTypeError(
            f"Unknown mode: {value}. Options: {', '.join(MODES)} (or goku)."
        )
    return mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Disappearance effects for your webcam: Dragon Ball, Normal (V) or Naruto."
    )
    parser.add_argument(
        "--camera", type=camera_source, default=None,
        help="Webcam number or /dev/videoN path (default: 0; on Linux, the first real webcam)",
    )
    parser.add_argument("--width", type=int, default=960, help="Video width")
    parser.add_argument("--height", type=int, default=540, help="Video height")
    parser.add_argument(
        "--fullscreen", action="store_true", help="Start in fullscreen"
    )
    parser.add_argument(
        "--no-mirror", action="store_true", help="Do not mirror the webcam"
    )
    parser.add_argument(
        "--mirror-output", action="store_true",
        help="Mirror the virtual camera too (by default only the preview is mirrored)",
    )
    parser.add_argument("--fps", type=positive_fps, default=30.0, help="Maximum virtual camera FPS (default: 30)")
    parser.add_argument(
        "--virtual-camera", action=argparse.BooleanOptionalAction, default=None,
        help="Require the virtual camera; by default it is used if available. --no-virtual-camera disables it",
    )
    parser.add_argument(
        "--virtual-backend", choices=("obs", "unitycapture", "v4l2loopback"),
        help="Virtual camera driver",
    )
    parser.add_argument("--virtual-device", help="Virtual device name or path")
    parser.add_argument(
        "--audio-device",
        help="Audio output device for the effect sounds (pygame/SDL device name; default: the system one)",
    )
    parser.add_argument(
        "--mode", type=mode_name, default=DEFAULT_MODE,
        help="dragonball (default, alias goku), normal or naruto",
    )
    parser.add_argument(
        "--menu", action="store_true", help="Show the menu to choose the effect",
    )
    parser.add_argument(
        "--gesture-debug", action="store_true",
        help="Print the detected gesture in the terminal (no text on the video)",
    )
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def choose_mode() -> str | None:
    """Simple keyboard/mouse menu shown before the clean camera feed."""
    title = "Choose effect"
    selected = [None]
    window = np.zeros((540, 700, 3), dtype=np.uint8)
    window[:] = (26, 29, 34)
    cv2.putText(window, "CHOOSE YOUR EFFECT", (68, 88),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (236, 239, 242), 2, cv2.LINE_AA)
    buttons = (
        ("dragonball", "1  DRAGON BALL", "Two fingers on forehead 1 s  /  teleport", 140),
        ("normal", "2  NORMAL VANISH", "Two-finger V  /  dissolve", 260),
        ("naruto", "3  NARUTO VANISH", "Palms together  /  log and smoke", 380),
    )
    for mode, heading, detail, top in buttons:
        cv2.rectangle(window, (65, top), (635, top + 94), (48, 54, 62), -1, cv2.LINE_AA)
        cv2.rectangle(window, (65, top), (635, top + 94), (111, 142, 153), 2, cv2.LINE_AA)
        cv2.putText(window, heading, (90, top + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.77, (240, 245, 247), 2, cv2.LINE_AA)
        cv2.putText(window, detail, (90, top + 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.53, (179, 195, 201), 1, cv2.LINE_AA)

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONUP and 65 <= x <= 635:
            for mode, _, _, top in buttons:
                if top <= y <= top + 94:
                    selected[0] = mode

    cv2.namedWindow(title, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(title, on_mouse)
    try:
        while selected[0] is None:
            cv2.imshow(title, window)
            key = cv2.waitKey(30) & 0xFF
            if ord("1") <= key < ord("1") + len(buttons):
                selected[0] = buttons[key - ord("1")][0]
            elif key in (ord("q"), 27):
                return None
            if cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                return None
        return selected[0]
    finally:
        cv2.destroyWindow(title)


def open_virtual_camera(args: argparse.Namespace, width: int, height: int):
    if args.virtual_camera is False:
        return None
    try:
        import pyvirtualcam

        camera = pyvirtualcam.Camera(
            width=width, height=height, fps=args.fps,
            fmt=pyvirtualcam.PixelFormat.BGR,
            backend=args.virtual_backend, device=args.virtual_device,
        )
    except (ImportError, RuntimeError, OSError, ValueError) as error:
        system = platform.system()
        if system == "Linux":
            hint = ("Run the installer again or load v4l2loopback with "
                    "'sudo modprobe v4l2loopback exclusive_caps=1'.")
        elif system == "Darwin":
            hint = ("Install OBS Studio 30 or later, open it, click 'Start Virtual Camera' and "
                    "then 'Stop Virtual Camera' once, and close it.")
        else:
            hint = ("Install OBS Studio (it includes the 'OBS Virtual Camera') or Unity Capture. "
                    "If OBS is open, stop its virtual camera.")
        message = f"Virtual camera not available. {hint} Details: {error}"
        if args.virtual_camera is True or args.virtual_backend or args.virtual_device:
            raise RuntimeError(message) from error
        print(f"[Webcam] {message}\n[Webcam] Continuing with the preview only.")
        return None
    print(f"[Webcam] Virtual camera active: {camera.device} ({width}x{height}, {args.fps:g} FPS max)")
    return camera


def send_virtual_frame(camera, frame: np.ndarray) -> None:
    if frame.shape[:2] != (camera.height, camera.width):
        frame = cv2.resize(frame, (camera.width, camera.height), interpolation=cv2.INTER_LINEAR)
    camera.send(np.ascontiguousarray(frame))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def download_models(mode: str = "normal") -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for destination, url in MODEL_URLS.items():
        if mode != "normal" and destination == GESTURE_MODEL:
            continue
        if mode == "naruto" and destination == MULTICLASS_MODEL:
            continue
        expected = MODEL_SHA256.get(destination.name)
        if destination.exists() and (
            file_sha256(destination) == expected if expected else destination.stat().st_size > 100_000
        ):
            continue
        if destination == MULTICLASS_MODEL:
            # Optional: without it, Super Saiyan only gets the aura.
            try:
                download_model(destination, url, expected)
            except RuntimeError as error:
                print(f"[Super Saiyan] {error} Continuing without the golden hair.")
            continue
        download_model(destination, url, expected)


def download_model(destination: Path, url: str, expected: str | None = None) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"[Vanish Lab] Downloading {destination.name}...")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Vanish-Lab/1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length", 0))
            received = 0
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 256):
                    output.write(chunk)
                    received += len(chunk)
                    if total:
                        percent = int(received * 100 / total)
                        print(f"\r  {percent:3d}%", end="", flush=True)
        print()
        if total and received != total:
            raise OSError(f"incomplete download ({received} of {total} bytes)")
    except (OSError, urllib.error.URLError) as error:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            "Could not download the MediaPipe models. "
            "Check your internet connection and try again."
        ) from error
    if expected and file_sha256(temporary) != expected:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"The downloaded model {destination.name} is not the expected one (hash mismatch). "
            "Not using it. If Google published a new version, MODEL_SHA256 needs updating."
        )
    os.replace(temporary, destination)


def open_camera(index: int | str | None, width: int, height: int) -> cv2.VideoCapture:
    system = platform.system()
    if index is None:
        cameras = find_linux_cameras() if system == "Linux" else []
        index = cameras[0] if cameras else 0
        if cameras:
            print(f"[Webcam] Using webcam {index}.")

    if system == "Windows":
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(index)
    elif system == "Linux":
        capture = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(index)
        # In YUYV many USB webcams drop to 5-10 FPS above 640x480.
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    elif system == "Darwin":
        capture = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    else:
        capture = cv2.VideoCapture(index)

    if not capture.isOpened():
        hint = {
            "Linux": "list the webcams with 'v4l2-ctl --list-devices'",
            "Darwin": ("give Terminal camera access in System Settings → "
                       "Privacy & Security → Camera, or try --camera 1"),
        }.get(system, "try --camera 1")
        raise RuntimeError(
            f"Webcam {index} is not available. Close any other apps using it, or {hint}."
        )

    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def base_options(model: Path) -> python.BaseOptions:
    # Force the CPU: on macOS MediaPipe otherwise reaches for Metal and aborts
    # when no GPU service is available ("Check failed: service_").
    return python.BaseOptions(model_asset_path=str(model), delegate=python.BaseOptions.Delegate.CPU)


def create_dragonball_detector() -> dragonball.InstantTransmissionDetector:
    for path in (HAND_MODEL, FACE_MODEL):
        if not path.is_file():
            raise RuntimeError(f"Model not found: {path}")
    hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=base_options(HAND_MODEL),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.5,
    ))
    try:
        faces = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=base_options(FACE_MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            # The hand on the forehead covers part of the face: low thresholds.
            min_face_detection_confidence=0.3,
            min_face_presence_confidence=0.3,
            min_tracking_confidence=0.3,
        ))
    except Exception:
        hands.close()
        raise
    return dragonball.InstantTransmissionDetector(hands, faces)


def create_tasks(mode: str = "normal") -> tuple[
    vision.ImageSegmenter,
    MultiViewGestureRecognizer | MultiViewHandLandmarker | dragonball.InstantTransmissionDetector,
]:
    segmenter_options = vision.ImageSegmenterOptions(
        base_options=base_options(SEGMENTER_MODEL),
        running_mode=vision.RunningMode.VIDEO,
        output_confidence_masks=True,
        output_category_mask=False,
    )
    if mode == "dragonball":
        segmenter = vision.ImageSegmenter.create_from_options(segmenter_options)
        try:
            return segmenter, create_dragonball_detector()
        except Exception:
            segmenter.close()
            raise
    if mode == "naruto":
        if not HAND_MODEL.is_file():
            raise RuntimeError(f"Hand model not found: {HAND_MODEL}")
        options = vision.HandLandmarkerOptions(
            base_options=base_options(HAND_MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.35,
            min_hand_presence_confidence=0.35,
            min_tracking_confidence=0.45,
        )
        task_class = vision.HandLandmarker
        wrapper_class = MultiViewHandLandmarker
    else:
        classifier_options = mp.tasks.components.processors.ClassifierOptions(
            score_threshold=0.55,
            category_allowlist=["Victory"],
        )
        options = vision.GestureRecognizerOptions(
            base_options=base_options(GESTURE_MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.35,
            min_hand_presence_confidence=0.35,
            min_tracking_confidence=0.5,
            canned_gesture_classifier_options=classifier_options,
        )
        task_class = vision.GestureRecognizer
        wrapper_class = MultiViewGestureRecognizer

    segmenter = vision.ImageSegmenter.create_from_options(segmenter_options)
    try:
        primary = task_class.create_from_options(options)
        try:
            alternate = task_class.create_from_options(
                replace(options, running_mode=vision.RunningMode.IMAGE)
            )
        except Exception:
            primary.close()
            raise
    except Exception:
        segmenter.close()
        raise
    return segmenter, wrapper_class(primary, alternate)


def smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    values = np.clip((values - edge0) / max(edge1 - edge0, 1e-6), 0.0, 1.0)
    return values * values * (3.0 - 2.0 * values)


def ease_in_out_cubic(value: float) -> float:
    if value < 0.5:
        return 4.0 * value * value * value
    return 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0


def make_dissolve_fields(height: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(7391)
    y, x = np.mgrid[0:height, 0:width]
    y_normal = y.astype(np.float32) / max(height - 1, 1)
    x_normal = x.astype(np.float32) / max(width - 1, 1)
    low_noise = rng.random((max(2, height // 10), max(2, width // 10)), dtype=np.float32)
    low_noise = cv2.resize(low_noise, (width, height), interpolation=cv2.INTER_CUBIC)
    fine_noise = rng.random((height, width), dtype=np.float32)
    field = (
        (1.0 - y_normal) * 0.72
        + low_noise * 0.17
        + fine_noise * 0.08
        + np.sin(x_normal * 18.0) * 0.025
    )
    return np.clip(field, 0.0, 1.0), fine_noise


def person_mask(
    segmenter: vision.ImageSegmenter,
    image: mp.Image,
    timestamp_ms: int,
    width: int,
    height: int,
) -> np.ndarray:
    result = segmenter.segment_for_video(image, timestamp_ms)
    if not result.confidence_masks:
        return np.zeros((height, width), dtype=np.float32)
    raw = np.squeeze(result.confidence_masks[0].numpy_view()).astype(np.float32)
    resized = cv2.resize(raw, (width, height), interpolation=cv2.INTER_LINEAR)
    resized = cv2.GaussianBlur(resized, (0, 0), sigmaX=2.2, sigmaY=2.2)
    return np.clip((resized - 0.12) / 0.68, 0.0, 1.0)


def alpha_composite(person: np.ndarray, background: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    alpha_3 = alpha[:, :, None]
    return (
        person.astype(np.float32) * alpha_3
        + background.astype(np.float32) * (1.0 - alpha_3)
    ).astype(np.uint8)


def apply_dissolve(
    frame: np.ndarray,
    background: np.ndarray,
    mask: np.ndarray,
    progress: float,
    field: np.ndarray,
    sparkle_noise: np.ndarray,
) -> np.ndarray:
    if progress <= 0.002:
        return alpha_composite(frame, background, mask)
    if progress >= 0.999:
        return background.copy()

    points = cv2.findNonZero((mask > 0.01).astype(np.uint8))
    if points is None:
        return background.copy()
    x, y, width, height = cv2.boundingRect(points)
    left, top = max(0, x - 18), max(0, y - 18)
    right = min(mask.shape[1], x + width + 18)
    bottom = min(mask.shape[0], y + height + 18)
    area = np.s_[top:bottom, left:right]
    mask = mask[area]
    field = field[area]
    sparkle_noise = sparkle_noise[area]
    eased = ease_in_out_cubic(progress)
    survival = smoothstep(eased - 0.055, eased + 0.055, field)
    alpha = mask * survival
    output = alpha_composite(frame[area], background[area], alpha)
    edge = (
        (np.abs(field - eased) < 0.018)
        & (mask > 0.48)
        & (sparkle_noise > 0.54)
    ).astype(np.float32)
    glow = cv2.GaussianBlur(edge, (0, 0), sigmaX=5.0, sigmaY=5.0)
    glow = np.clip(glow * 5.0 + edge, 0.0, 1.0)[:, :, None]
    cyan = np.full_like(output, (255, 228, 92), dtype=np.uint8)
    result = np.clip(
        output.astype(np.float32) * (1.0 - glow * 0.8)
        + cyan.astype(np.float32) * glow * 0.8,
        0,
        255,
    ).astype(np.uint8)
    canvas = background.copy()
    canvas[area] = result
    return canvas


def victory_landmark_score(points: np.ndarray) -> float:
    """Recognize extended index and middle fingers using 3D distances, not orientation."""
    if points.shape != (21, 3) or not np.isfinite(points).all():
        return 0.0

    straightness = []
    extended = []
    folded = []
    lengths = []
    # MCP, PIP, DIP and tip: index, middle, ring, pinky.
    for index, base in enumerate((5, 9, 13, 17)):
        finger = points[base : base + 4]
        length = float(np.linalg.norm(np.diff(finger, axis=0), axis=1).sum())
        if length < 1e-6:
            if index < 2:
                return 0.0
            straightness.append(0.0)
            lengths.append(0.0)
            extended.append(False)
            folded.append(True)
            continue
        ratio = float(np.linalg.norm(finger[3] - finger[0])) / length
        tip_distance = float(np.linalg.norm(finger[3] - points[0]))
        joint_distance = float(np.linalg.norm(finger[1] - points[0]))
        straightness.append(ratio)
        lengths.append(length)
        extended.append(ratio >= 0.82 and tip_distance > joint_distance * 1.10)
        folded.append(ratio < 0.78 or tip_distance <= joint_distance * 1.05)

    # Seen from the side, folded fingers can look straight but very short:
    # do not require clearly visible joints for the ring and pinky fingers.
    reference_length = min(lengths[:2])
    for index, base in ((2, 13), (3, 17)):
        reach = float(np.linalg.norm(points[base + 3] - points[base]))
        folded[index] = folded[index] or reach < reference_length * 0.65
    if not (extended[0] and extended[1] and folded[2] and folded[3]):
        return 0.0
    # The two tips must be apart; the thumb may stay hidden.
    separation = float(np.linalg.norm(points[8] - points[12]))
    if separation < min(lengths[:2]) * 0.20:
        return 0.0
    # Geometric quality of the extended fingers, not a classifier probability.
    return float(np.clip(min(straightness[:2]), 0.0, 1.0))


def classify_gesture_result(
    result: vision.GestureRecognizerResult,
    image: mp.Image,
) -> tuple[str, float]:
    # Landmarks are returned even when the classifier does not recognize
    # "Victory" (for example with the back of the hand facing the webcam).
    for landmarks in result.hand_world_landmarks:
        points = np.array([(point.x, point.y, point.z) for point in landmarks])
        score = victory_landmark_score(points)
        if score:
            return "Victory", score
    # ALWAYS check the visible geometry too: the estimated depth can be
    # inaccurate when the palm and folded fingers are hidden.
    for landmarks in result.hand_landmarks:
        points = np.array([(point.x * image.width, point.y * image.height, 0.0)
                           for point in landmarks])
        score = victory_landmark_score(points)
        if score:
            return "Victory", score
    for categories in result.gestures:
        for category in categories:
            if category.category_name == "Victory" and category.score >= 0.62:
                return "Victory", float(category.score)
    if result.hand_landmarks or result.hand_world_landmarks:
        return "Hand_Detected", 0.0
    return "No_Hand", 0.0


class MultiViewGestureRecognizer:
    """Retry detection on rotated frames without disturbing the tracking."""

    def __init__(self, primary, alternate):
        self.primary = primary
        self.alternate = alternate
        self.preferred_rotation: int | None = None
        self.preferred_crop: str | None = None
        self.next_retry_ms = 0
        self.retry_cursor = 0

    def recognize_gesture(self, image: mp.Image, timestamp_ms: int) -> tuple[str, float]:
        result = self.primary.recognize_for_video(image, timestamp_ms)
        best = classify_gesture_result(result, image)
        if best[0] == "Victory":
            self.preferred_rotation = None
            self.preferred_crop = None
            return best
        if timestamp_ms < self.next_retry_ms:
            return best

        # IMAGE forces a fresh detection; the VIDEO model stays on the original
        # frame. Avoids inconsistent timestamps/tracking across rotations.
        rgb = image.numpy_view()
        height, width = rgb.shape[:2]
        # In the sideways pose the palm is often too small in the full frame.
        # The two lower crops overlap and cover both hands, even when the
        # image is mirrored.
        crops = {
            "full": rgb,
            "lower_left": rgb[int(height * 0.28):, :int(width * 0.78)],
            "lower_right": rgb[int(height * 0.28):, int(width * 0.22):],
        }
        views = [("full", rotation) for rotation in (0, 1, 3, 2)]
        views += [(crop, rotation) for crop in ("lower_left", "lower_right")
                  for rotation in (0, 1, 3)]
        preferred = (self.preferred_crop, self.preferred_rotation)
        selected = []
        if preferred in views:
            selected.append(preferred)
        # Spread the expensive IMAGE attempts over successive video frames.
        while len(selected) < 3:
            view = views[self.retry_cursor % len(views)]
            self.retry_cursor += 1
            if view not in selected:
                selected.append(view)
        for crop, rotation in selected:
            rotated = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(np.rot90(crops[crop], rotation)),
            )
            result = self.alternate.recognize(rotated)
            candidate = classify_gesture_result(result, rotated)
            if candidate[0] == "Victory":
                self.preferred_rotation = rotation
                self.preferred_crop = crop
                self.next_retry_ms = timestamp_ms + int(GESTURE_INTERVAL_SECONDS * 1000)
                return candidate
            if candidate[0] == "Hand_Detected":
                best = candidate
        self.preferred_rotation = None
        self.preferred_crop = None
        self.next_retry_ms = timestamp_ms + int(GESTURE_INTERVAL_SECONDS * 1000)
        return best

    def close(self) -> None:
        try:
            self.primary.close()
        finally:
            self.alternate.close()


class MultiViewHandLandmarker:
    """Track two hands in video and retry difficult views with the hand model."""

    def __init__(self, primary, alternate):
        self.primary = primary
        self.alternate = alternate
        self.preferred_view: tuple[str, int] | None = None
        self.next_retry_ms = 0
        self.last_hand_count = 0
        self.retry_cursor = 0

    def recognize_joined_hands(self, image: mp.Image, timestamp_ms: int) -> bool:
        result = self.primary.detect_for_video(image, timestamp_ms)
        self.last_hand_count = len(result.hand_landmarks)
        if joined_hands_from_landmarks(result.hand_landmarks, image.width, image.height):
            self.preferred_view = None
            return True
        if timestamp_ms < self.next_retry_ms:
            return False

        rgb = image.numpy_view()
        height, width = rgb.shape[:2]
        views = {
            "full": rgb,
            "center": rgb[int(height * 0.18):, int(width * 0.12):int(width * 0.88)],
            "lower_left": rgb[int(height * 0.22):, :int(width * 0.78)],
            "lower_right": rgb[int(height * 0.22):, int(width * 0.22):],
        }
        attempts = [("full", rotation) for rotation in (1, 3, 2)]
        attempts += [("center", rotation) for rotation in (0, 1, 3)]
        attempts += [("lower_left", 0), ("lower_right", 0)]
        selected = []
        if self.preferred_view in attempts:
            selected.append(self.preferred_view)
        while len(selected) < 2:
            view = attempts[self.retry_cursor % len(attempts)]
            self.retry_cursor += 1
            if view not in selected:
                selected.append(view)
        for crop, rotation in selected:
            rotated = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(np.rot90(views[crop], rotation)),
            )
            result = self.alternate.detect(rotated)
            self.last_hand_count = max(self.last_hand_count, len(result.hand_landmarks))
            if joined_hands_from_landmarks(result.hand_landmarks, rotated.width, rotated.height):
                self.preferred_view = (crop, rotation)
                self.next_retry_ms = timestamp_ms + 90
                return True
        self.preferred_view = None
        self.next_retry_ms = timestamp_ms + 80
        return False

    def close(self) -> None:
        try:
            self.primary.close()
        finally:
            self.alternate.close()


def recognize_gesture(
    recognizer: MultiViewGestureRecognizer,
    image: mp.Image,
    timestamp_ms: int,
) -> tuple[str, float]:
    if isinstance(recognizer, MultiViewGestureRecognizer):
        return recognizer.recognize_gesture(image, timestamp_ms)
    return classify_gesture_result(recognizer.recognize_for_video(image, timestamp_ms), image)


def gesture_active(
    mode: str,
    recognizer,
    image: mp.Image,
    timestamp_ms: int,
    debug: bool = False,
) -> bool:
    """Whether the mode's gesture is present in this frame (no hold time)."""
    if mode == "normal":
        name, score = recognize_gesture(recognizer, image, timestamp_ms)
        if debug:
            print(f"[Gesture] {name}, score={score:.2f}, crop={recognizer.preferred_crop or 'full'}, "
                  f"rotation={recognizer.preferred_rotation or 0}")
        return name == "Victory" and score >= 0.62
    if mode == "naruto":
        joined = recognizer.recognize_joined_hands(image, timestamp_ms)
        if debug:
            print(f"[Hands] detected={recognizer.last_hand_count}, joined={joined}, "
                  f"view={recognizer.preferred_view or 'full'}")
        return joined
    pose = recognizer.detect(image, timestamp_ms)
    if debug:
        print(f"[Dragon Ball] hands={recognizer.last_hand_count}, face={recognizer.last_face_found}, "
              f"fingers on forehead={pose}")
    return pose


def person_in_frame(
    segmenter: vision.ImageSegmenter,
    image: mp.Image,
    timestamp_ms: int,
    width: int,
    height: int,
) -> bool:
    mask = person_mask(segmenter, image, timestamp_ms, width, height)
    return float((mask > 0.5).mean()) > PERSON_AREA_LIMIT


def teleport_sound_path() -> Path:
    for path in TELEPORT_SOUND_FILES:
        if path.is_file():
            return path
    return dragonball.write_teleport_sound(TELEPORT_SOUND_FILES[-1])


def ssj_sound_paths() -> tuple[Path, Path, Path]:
    """Charge, transformation and hum: assets/<name>.MP3 if present, otherwise generated."""
    paths = []
    for name, writer in SSJ_SOUNDS.items():
        custom = APP_DIR / "assets" / f"{name}.MP3"
        generated = MODEL_DIR / f"{name}.wav"
        if custom.is_file():
            paths.append(custom)
        else:
            paths.append(generated if generated.is_file() else writer(generated))
    return tuple(paths)


def create_hair_tracker() -> ssj.HairTracker | None:
    if not MULTICLASS_MODEL.is_file():
        print("[Super Saiyan] The hair model is missing: the transformation will only have the aura.")
        return None
    try:
        segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=base_options(MULTICLASS_MODEL),
            running_mode=vision.RunningMode.IMAGE,
            output_confidence_masks=True,
            output_category_mask=False,
        ))
    except Exception as error:
        print(f"[Super Saiyan] Could not load the hair model ({error}): aura only.")
        return None
    return ssj.HairTracker(segmenter)


def power_active(recognizer) -> bool:
    """Ki-charging pose in the detector's latest inference (the teleport wins)."""
    if getattr(recognizer, "last_teleport", False):
        return False
    width, height = getattr(recognizer, "last_size", (0, 0))
    return ssj.charging_from_landmarks(
        getattr(recognizer, "last_hands", []), getattr(recognizer, "last_faces", []), width, height
    )


def hair_mask(tracker: ssj.HairTracker | None, recognizer, frame: np.ndarray,
              now: float) -> np.ndarray | None:
    if tracker is None:
        return None
    width, height = getattr(recognizer, "last_size", (0, 0))
    face = ssj.face_points(getattr(recognizer, "last_faces", []), width, height)
    if face is not None and (width, height) != (frame.shape[1], frame.shape[0]):
        face = None
    return tracker.update(frame, face, now)


def set_fullscreen(enabled: bool) -> None:
    mode = cv2.WINDOW_FULLSCREEN if enabled else cv2.WINDOW_NORMAL
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, mode)


def self_test() -> int:
    """Check bundled resources and model initialization without opening a webcam."""
    required = (SEGMENTER_MODEL, GESTURE_MODEL, HAND_MODEL, FACE_MODEL, SOUND_PATH)
    missing = [path.name for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Missing files: {', '.join(missing)}")
    load_log()
    teleport_sound_path()
    ssj_sound_paths()
    import pygame.mixer  # The distributed build must contain its MP3 decoder.
    for mode in MODES:
        segmenter, recognizer = create_tasks(mode)
        try:
            recognizer.close()
        finally:
            segmenter.close()
    hair = create_hair_tracker()
    if hair is not None:
        hair.close()
    print("[Webcam] Self-test passed: models, images and audio are present.")
    return 0


def run() -> int:
    args = parse_args()
    if getattr(args, "self_test", False):
        return self_test()
    mode = choose_mode() if getattr(args, "menu", False) else (args.mode or DEFAULT_MODE)
    if mode is None:
        return 0
    with ExitStack() as resources:
        return run_camera(args, resources, mode)


def run_camera(args: argparse.Namespace, resources: ExitStack, mode: str) -> int:
    download_models(mode)
    capture = open_camera(args.camera, args.width, args.height)
    resources.callback(capture.release)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    segmenter, recognizer = create_tasks(mode)
    resources.callback(segmenter.close)
    resources.callback(recognizer.close)
    log_sprite = load_log() if mode == "naruto" else None
    sound = None
    audio_device = getattr(args, "audio_device", None)
    if mode == "naruto":
        sound = VanishSound(device=audio_device)
    elif mode == "dragonball":
        sound = VanishSound(teleport_sound_path(), device=audio_device)
    if sound is not None:
        resources.callback(sound.close)
    # Super Saiyan: Dragon Ball only; reuses the teleport detector's inference.
    super_saiyan = mode == "dragonball"
    power = ssj.PowerState()
    power_hold = GestureHold(ssj.CHARGE_SECONDS)
    aura = ssj.AuraRenderer() if super_saiyan else None
    hair_tracker = None
    charge_sound = transform_sound = hum_sound = None
    if super_saiyan:
        hair_tracker = create_hair_tracker()
        if hair_tracker is not None:
            resources.callback(hair_tracker.close)
        # Created after the teleport sound, which owns the mixer and is closed last.
        charge_sound, transform_sound, hum_sound = (
            VanishSound(path, device=audio_device) for path in ssj_sound_paths()
        )
        for extra in (charge_sound, transform_sound, hum_sound):
            resources.callback(extra.close)
    resources.callback(cv2.destroyAllWindows)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, args.width, args.height)

    state = AppState(
        calibration_started=time.perf_counter(), fullscreen=args.fullscreen
    )
    if state.fullscreen:
        set_fullscreen(True)

    hold = GestureHold(HOLD_SECONDS[mode])
    gesture_interval = GESTURE_INTERVAL_SECONDS if mode == "normal" else FAST_GESTURE_INTERVAL_SECONDS
    mirrored = not args.no_mirror
    flip_output = mirrored and not getattr(args, "mirror_output", False)
    background: np.ndarray | None = None
    background_samples: list[np.ndarray] = []
    calibration_retries = 0
    last_person_check = float("-inf")
    frame_index = 0
    last_mask: np.ndarray | None = None
    last_mask_at = float("-inf")
    dissolve_field: np.ndarray | None = None
    sparkle_noise: np.ndarray | None = None
    log_anchor: tuple[int, int, int] | None = None
    log_cache: dict[int, np.ndarray] = {}
    vanished_frame: np.ndarray | None = None
    virtual_camera = None
    virtual_camera_initialized = False
    calibration_remaining = None
    last_gesture_report = 0.0
    hold_announced = False
    started = time.perf_counter()
    gesture_help = {
        "dragonball": "Index and middle fingers together on your forehead for 1 second: you vanish. Repeat to come back.",
        "normal": "V with index and middle fingers (hold it for a moment): you vanish. Repeat to come back.",
        "naruto": "Palms together (for a moment): you vanish. Repeat to come back.",
    }[mode]
    print("[Webcam] Step out of the frame: the background photo is taken in 4 seconds.")
    print(f"[Webcam] {gesture_help}")
    if super_saiyan:
        print("[Webcam] Closed fists at chest height, one on each side, for 1.5 seconds: Super Saiyan. "
              "Repeat (or press S) to go back to normal.")
    print("[Webcam] Keys in the window: SPACE new background, R reappear, V vanish, F fullscreen, Q quit.")

    def transform(now: float) -> None:
        power.transform(now)
        charge_sound.stop(80)
        transform_sound.play()
        hum_sound.play(loops=-1, fade_ms=400)
        print("[Dragon Ball] Super Saiyan!")

    def power_down(now: float) -> None:
        power.power_down(now)
        charge_sound.stop()
        hum_sound.stop(500)
        print("[Dragon Ball] Back to normal.")

    def stop_power() -> None:
        power.reset()
        power_hold.reset()
        if super_saiyan:
            for extra in (charge_sound, transform_sound, hum_sound):
                extra.stop()

    def begin_calibration(now: float) -> None:
        nonlocal calibration_remaining, last_person_check, vanished_frame, log_anchor
        nonlocal last_mask, last_mask_at
        stop_power()
        state.phase = "calibrating"
        state.calibration_started = now
        state.vanish_started = None
        background_samples.clear()
        calibration_remaining = None
        last_person_check = float("-inf")
        vanished_frame = None
        log_anchor = None
        last_mask = None
        last_mask_at = float("-inf")
        hold.reset()

    def start_effect(phase: str, now: float) -> None:
        nonlocal last_mask, last_mask_at, vanished_frame
        state.phase = phase
        state.vanish_started = now
        last_mask = None
        last_mask_at = float("-inf")
        if phase == "vanishing":
            vanished_frame = None
        if sound is not None:
            sound.play()
        if super_saiyan:
            # A half-done charge is cancelled; if already transformed, they leave and return transformed.
            if power.phase == "charging":
                power.reset()
                charge_sound.stop(150)
            power_hold.reset()
            if power.transformed:
                if phase == "vanishing":
                    hum_sound.stop(300)
                else:
                    hum_sound.play(loops=-1, fade_ms=400)

    try:
        while True:
            ok, camera_frame = capture.read()
            if not ok:
                raise RuntimeError("The webcam stopped sending frames.")
            frame_index += 1

            if mirrored:
                camera_frame = cv2.flip(camera_frame, 1)

            height, width = camera_frame.shape[:2]
            if not virtual_camera_initialized:
                virtual_camera = open_virtual_camera(args, width, height)
                virtual_camera_initialized = True
                if virtual_camera is not None:
                    resources.callback(virtual_camera.close)
            if mode == "normal" and (dissolve_field is None or dissolve_field.shape != (height, width)):
                dissolve_field, sparkle_noise = make_dissolve_fields(height, width)
            now = time.perf_counter()

            elapsed_ms = int((now - started) * 1000)
            mp_image = None

            def frame_image() -> mp.Image:
                nonlocal mp_image
                if mp_image is None:
                    rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                return mp_image

            def golden(frame: np.ndarray, now: float) -> np.ndarray:
                """With Super Saiyan active, the teleport carries the golden hair along."""
                if not (super_saiyan and power.transformed):
                    return frame
                return ssj.recolor_hair(frame, hair_mask(hair_tracker, recognizer, frame, now), 1.0)

            def update_mask(every: float) -> np.ndarray | None:
                nonlocal last_mask, last_mask_at
                if last_mask is None or now - last_mask_at >= every:
                    last_mask = person_mask(segmenter, frame_image(), elapsed_ms, width, height)
                    last_mask_at = now
                return last_mask

            display = camera_frame
            if state.phase == "calibrating":
                elapsed = now - state.calibration_started
                remaining = max(0, int(np.ceil(CALIBRATION_SECONDS - elapsed)))
                if remaining != calibration_remaining:
                    print(f"[Webcam] Background photo in {remaining} seconds.")
                    calibration_remaining = remaining
                sampling = elapsed >= CALIBRATION_SECONDS - BACKGROUND_SAMPLE_SECONDS
                if sampling and now - last_person_check >= PERSON_CHECK_SECONDS:
                    last_person_check = now
                    if (calibration_retries < MAX_CALIBRATION_RETRIES
                            and person_in_frame(segmenter, frame_image(), elapsed_ms, width, height)):
                        calibration_retries += 1
                        print("[Webcam] Someone is still in the frame: step out, waiting 2 more seconds.")
                        # Go back to before the sampling window.
                        state.calibration_started = (
                            now - (CALIBRATION_SECONDS - BACKGROUND_SAMPLE_SECONDS) + CALIBRATION_RETRY_SECONDS
                        )
                        background_samples.clear()
                        calibration_remaining = None
                        sampling = False
                        elapsed = now - state.calibration_started
                if sampling and frame_index % 2 == 0:
                    background_samples.append(camera_frame.copy())
                    del background_samples[:-BACKGROUND_MAX_SAMPLES]
                if elapsed >= CALIBRATION_SECONDS:
                    if background_samples:
                        background = np.median(np.stack(background_samples), axis=0).astype(np.uint8)
                    else:
                        background = camera_frame.copy()
                    if calibration_retries >= MAX_CALIBRATION_RETRIES:
                        print("[Webcam] Could not capture the background with nobody in the frame; using it anyway. "
                              "Press SPACE to retry.")
                    background_samples.clear()
                    calibration_retries = 0
                    state.phase = "ready"
                    hold.reset()
                    print("[Webcam] Background ready. You can step back into the frame.")

            elif background is None:
                begin_calibration(now)

            else:
                if (state.phase in ("ready", "vanished")
                        and now - state.last_gesture_check >= gesture_interval):
                    state.last_gesture_check = now
                    debug = args.gesture_debug and now - last_gesture_report >= 1.0
                    if debug:
                        last_gesture_report = now
                    active = gesture_active(mode, recognizer, frame_image(), elapsed_ms, debug)
                    if hold.update(active, now):
                        hold_announced = False
                        start_effect("vanishing" if state.phase == "ready" else "appearing",
                                     time.perf_counter())
                    elif mode == "dragonball" and hold.since is not None and not hold_announced:
                        hold_announced = True
                        print(f"[Dragon Ball] Keep your fingers on your forehead for {HOLD_SECONDS[mode]:g} s...")
                    elif hold.since is None:
                        hold_announced = False
                    if super_saiyan and state.phase == "ready":
                        charging = power_active(recognizer)
                        was_charging = power_hold.since is not None
                        if power_hold.update(charging, now):
                            if power.transformed:
                                power_down(now)
                            else:
                                transform(now)
                        elif power_hold.since is not None and not was_charging and power.phase == "off":
                            charge_sound.play()
                            print("[Dragon Ball] Charging ki...")
                        elif was_charging and power_hold.since is None and power.phase == "charging":
                            charge_sound.stop(150)
                if super_saiyan:
                    power.update(now, power_hold.since if state.phase == "ready" else None)

                age = 0.0
                if state.vanish_started is not None:
                    age = max(0.0, time.perf_counter() - state.vanish_started)

                if state.phase == "vanished":
                    if vanished_frame is None:
                        vanished_frame = background.copy()
                        if mode == "naruto" and log_anchor is not None:
                            overlay_log(vanished_frame, log_sprite, landed_log_anchor(log_anchor, height),
                                        cache=log_cache)
                    display = vanished_frame

                elif state.phase == "vanishing":
                    if mode == "normal":
                        mask = update_mask(0.05)
                        progress = min(1.0, age / VANISH_SECONDS)
                        display = apply_dissolve(
                            camera_frame, background, mask, progress, dissolve_field, sparkle_noise
                        )
                        done = progress >= 1.0
                    elif mode == "naruto":
                        # The silhouette is only needed while the person is visible.
                        mask = update_mask(0.0) if (log_anchor is None or age < 0.13) else last_mask
                        if log_anchor is None:
                            log_anchor = substitution_anchor(mask)
                        display = render_substitution(
                            camera_frame, background, mask, log_sprite, log_anchor, max(0.04, age), log_cache
                        )
                        done = age >= EFFECT_SECONDS
                    else:
                        # After vanishing, the lines stay on the frozen silhouette.
                        mask = update_mask(0.05) if age < dragonball.VANISH_AT else last_mask
                        display = dragonball.render_teleport(golden(camera_frame, now), background, mask, age)
                        done = age >= dragonball.EFFECT_SECONDS
                    if done:
                        state.phase = "vanished"
                        vanished_frame = display

                elif state.phase == "appearing":
                    mask = update_mask(0.05)
                    if mode == "normal":
                        progress = min(1.0, age / APPEAR_SECONDS)
                        display = apply_dissolve(
                            camera_frame, background, mask, 1.0 - progress, dissolve_field, sparkle_noise
                        )
                        done = progress >= 1.0
                    elif mode == "naruto":
                        display = render_reappearance(
                            camera_frame, background, mask, log_sprite, log_anchor, age, log_cache
                        )
                        done = age >= REAPPEAR_SECONDS
                    else:
                        display = dragonball.render_teleport(
                            golden(camera_frame, now), background, mask,
                            max(0.0, dragonball.EFFECT_SECONDS - age),
                        )
                        done = age >= dragonball.EFFECT_SECONDS
                    if done:
                        state.phase = "ready"
                        state.vanish_started = None
                        vanished_frame = None
                        log_anchor = None
                        display = camera_frame

                if super_saiyan and state.phase == "ready" and power.phase != "off":
                    levels = power.levels(now)
                    hair = hair_mask(hair_tracker, recognizer, camera_frame, now) if levels.hair > 0 else None
                    display = ssj.render_super_saiyan(
                        camera_frame, update_mask(0.05), hair, levels, now, aura
                    )

            if virtual_camera is not None:
                # Zoom and Meet already mirror the local preview: viewers see the image the right way round.
                send_virtual_frame(virtual_camera, cv2.flip(display, 1) if flip_output else display)
            cv2.imshow(WINDOW_NAME, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                begin_calibration(now)
                print("[Webcam] Step out of the frame: the new background photo is taken in 4 seconds.")
            elif key == ord("r") and background is not None:
                if state.phase == "vanished":
                    start_effect("appearing", time.perf_counter())
                elif state.phase == "vanishing":
                    state.phase = "ready"
                    state.vanish_started = None
                    vanished_frame = None
                    log_anchor = None
            elif key == ord("v") and background is not None and state.phase in ("ready", "appearing"):
                log_anchor = None
                start_effect("vanishing", time.perf_counter())
            elif key == ord("s") and super_saiyan and background is not None and state.phase == "ready":
                if power.transformed:
                    power_down(now)
                else:
                    transform(now)
                power_hold.reset()
            elif key == ord("f"):
                state.fullscreen = not state.fullscreen
                set_fullscreen(state.fullscreen)
            if virtual_camera is not None:
                virtual_camera.sleep_until_next_frame()
    finally:
        resources.close()

    return 0


def main() -> int:
    try:
        return run()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"\n[Vanish Lab] ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
