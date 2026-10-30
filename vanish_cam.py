"""Local webcam with disappearance effects: Dragon Ball, V (dissolve) and Naruto."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from contextlib import ExitStack
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

try:
    from . import dragonball_effect as dragonball
    from . import frame_source
    from . import home_ui
    from . import ssj_face
    from . import ssj_motion
    from . import super_saiyan_effect as ssj
    from .naruto_effect import (
        EFFECT_SECONDS, REAPPEAR_SECONDS, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_reappearance, render_substitution, substitution_anchor,
    )
    from .vanish_sound import SOUND_PATH, VanishSound
except ImportError:
    import dragonball_effect as dragonball
    import frame_source
    import home_ui
    import ssj_face
    import ssj_motion
    import super_saiyan_effect as ssj
    from naruto_effect import (
        EFFECT_SECONDS, REAPPEAR_SECONDS, joined_hands_from_landmarks, landed_log_anchor,
        load_log, overlay_log, render_reappearance, render_substitution, substitution_anchor,
    )
    from vanish_sound import SOUND_PATH, VanishSound


APP_DIR = Path(__file__).resolve().parent
MODEL_DIR = APP_DIR / "models"
# Super Saiyan hair: the user's photos and the golden versions they made with an image model (gitignored).
HAIR_DIR = APP_DIR / "ssj_hair"
# Last effect and camera chosen in the home window (gitignored).
SETTINGS_PATH = APP_DIR / "vanishcam_settings.json"
WINDOW_NAME = "VanishCam - Preview"
CAMERA_WINDOW = "VanishCam - Choose camera"
PANEL_WIDTH = 380

SEGMENTER_MODEL = MODEL_DIR / "selfie_segmenter_landscape.tflite"
GESTURE_MODEL = MODEL_DIR / "gesture_recognizer.task"
HAND_MODEL = APP_DIR / "hand_landmarker.task"
FACE_MODEL = APP_DIR / "face_landmarker.task"
CUSTOM_SOUND_SUFFIXES = (".MP3", ".mp3", ".WAV", ".wav", ".OGG", ".ogg",
                         ".M4A", ".m4a", ".FLAC", ".flac", ".OPUS", ".opus")
SSJ_SOUNDS = {
    "ssj_charge": ssj.write_charge_sound,
    "ssj_transform": ssj.write_transform_sound,
    "ssj_aura": ssj.write_aura_hum,
}

MODEL_URLS = {
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


@lru_cache(maxsize=1)
def app_version() -> str:
    """The commit this copy runs from, shown in the windows so the user can tell an update arrived."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(APP_DIR), *args], capture_output=True, text=True,
                              timeout=3, check=True).stdout.strip()
    try:
        version = git("log", "-1", "--format=%h (%cs)")
        if git("status", "--porcelain", "--untracked-files=no"):
            version += " +changes"
        return version or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"  # Installed from a zip (no git history) or git missing.


def positive_fps(value: str) -> float:
    fps = float(value)
    if not np.isfinite(fps) or not 1 <= fps <= 120:
        raise argparse.ArgumentTypeError("FPS must be between 1 and 120.")
    return fps


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return number


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


def linux_camera_label(device: str, sysfs: Path = Path("/sys/class/video4linux")) -> str:
    """Human-readable name of a /dev/videoN node (empty when sysfs has no name)."""
    try:
        return (sysfs / Path(device).name / "name").read_text().strip()
    except OSError:
        return ""


# DirectShow cameras that are not a webcam. OBS Virtual Camera is VanishCam's own output: opening it
# would read our own video back. The Meta Quest entries come from the headset software.
VIRTUAL_CAMERA_WORDS = ("virtual", "obs", "unity video capture", "vanishcam", "meta quest")
WINDOWS_PROBE_INDICES = range(5)


def windows_camera_names() -> list[str] | None:
    """DirectShow video inputs in the order OpenCV numbers them with CAP_DSHOW; None if unavailable."""
    try:
        from pygrabber.dshow_graph import FilterGraph
        return list(FilterGraph().get_input_devices())
    except Exception:  # Missing package, COM error, or no media components (Windows "N" editions).
        return None


def is_virtual_camera(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in VIRTUAL_CAMERA_WORDS)


def find_windows_cameras(names: list[str] | None = None, probe=None) -> list[tuple[int, str]]:
    """Real Windows webcams as (OpenCV index, name). Without names, probes the first indices."""
    if names is None:
        names = windows_camera_names()
    if names is not None:
        return [(index, name) for index, name in enumerate(names) if not is_virtual_camera(name)]
    probe = probe or (lambda index: _open_capture(index, 640, 480, "Windows"))
    cameras = []
    for index in WINDOWS_PROBE_INDICES:
        capture = probe(index)
        if capture is not None:
            capture.release()
            cameras.append((index, f"Camera {index}"))
    return cameras


def find_cameras(system: str | None = None) -> list[tuple[int | str, str]]:
    """Real webcams for the current OS as (source for --camera, human-readable name)."""
    system = system or platform.system()
    if system == "Linux":
        return [(device, linux_camera_label(device)) for device in find_linux_cameras()]
    if system == "Windows":
        return find_windows_cameras()
    return []  # macOS: no picker yet (E5).


def camera_label(source: int | str, system: str | None = None) -> str:
    """Name of a webcam given by --camera (empty when unknown)."""
    system = system or platform.system()
    if isinstance(source, str):
        return linux_camera_label(source)
    if system == "Windows":
        names = windows_camera_names()
        if names and 0 <= source < len(names):
            return names[source]
    return ""


def camera_number(source: int | str) -> str:
    """What to pass to --camera: N for /dev/videoN on Linux, the index elsewhere."""
    return Path(source).name[5:] if isinstance(source, str) else str(source)


def list_cameras(system: str | None = None) -> None:
    system = system or platform.system()
    cameras = find_cameras(system)
    if not cameras:
        print("[Webcam] No real webcams found (virtual cameras are ignored).")
        if system == "Windows":
            for index, name in enumerate(windows_camera_names() or []):
                print(f"  {index}  {name}  (ignored: virtual camera)")
        return
    print("[Webcam] Cameras:")
    for source, label in cameras:
        print(f"  {source}  {label}  (use --camera {camera_number(source)})".replace("    ", "  "))
    if system == "Linux":
        print("[Webcam] On Linux, --camera N means /dev/videoN.")


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
        help="Webcam number or path: on Linux --camera 4 means /dev/video4 "
             "(default: the first real webcam, or ask when there are several)",
    )
    parser.add_argument(
        "--list-cameras", action="store_true",
        help="List the real webcams detected (Linux and Windows) and exit",
    )
    parser.add_argument("--width", type=int, default=960, help="Video width")
    parser.add_argument("--height", type=int, default=540, help="Video height")
    parser.add_argument(
        "--fullscreen", action="store_true", help="Start in fullscreen"
    )
    parser.add_argument(
        "--no-hud", action="store_true",
        help="Hide the side status panel (video only)",
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
        "--home", action="store_true",
        help="Show the home window (effect, camera, Super Saiyan hair) before starting; "
             "the launchers do this when started without options",
    )
    parser.add_argument(
        "--gesture-debug", action="store_true",
        help="Print the detected gesture in the terminal (no text on the video)",
    )
    parser.add_argument(
        "--ssj-hair-photos", action="store_true",
        help="Take the photos for the Super Saiyan hair (saved in ssj_hair/, never uploaded) and print what to do next",
    )
    parser.add_argument(
        "--no-ssj-eyes", dest="ssj_eyes", action="store_false",
        help="Super Saiyan: keep your own eye color (no teal irises)",
    )
    parser.add_argument(
        "--no-ssj-brows", dest="ssj_brows", action="store_false",
        help="Super Saiyan: keep your own eyebrows (no golden tint)",
    )
    parser.add_argument(
        "--no-ssj-hair", dest="ssj_hair", action="store_false",
        help="Super Saiyan: keep your own hair (no imported golden hair; aura only)",
    )
    parser.add_argument(
        "--capture-thread", action=argparse.BooleanOptionalAction, default=True,
        help="Read the webcam in a thread and always use its newest frame (default: on)",
    )
    parser.add_argument(
        "--input-video", metavar="PATH",
        help="Use a recorded clip instead of the webcam (played at its own speed, looping; never written)",
    )
    parser.add_argument(
        "--bench", type=positive_int, metavar="N",
        help="Measure N frames, print per-stage p50/p95 times and the CPU use, then exit",
    )
    parser.add_argument(
        "--bench-super-saiyan", action="store_true",
        help="With --bench in Dragon Ball mode: transform as soon as the background is ready",
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="No preview window (for --bench on a machine without a display); stop with Ctrl+C",
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
            hint = ("If /dev/video10 exists but is not usable, reload the module: "
                    "'sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback'. "
                    "If it is missing, run the installer again.")
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
        expected = MODEL_SHA256.get(destination.name)
        if destination.exists() and (
            file_sha256(destination) == expected if expected else destination.stat().st_size > 100_000
        ):
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


def _open_capture(index: int | str, width: int, height: int,
                  system: str | None = None) -> cv2.VideoCapture | None:
    """Open a webcam with the right backend; None if it cannot be opened."""
    system = system or platform.system()
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
        capture.release()
        return None
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _camera_preview(capture: cv2.VideoCapture | None, width: int, height: int,
                    mirrored: bool = True) -> np.ndarray:
    frame = None
    if capture is not None:
        ok, frame = capture.read()
        if not ok:
            frame = None
    if frame is None:
        frame = np.zeros((height, width, 3), np.uint8)
        frame[:] = (22, 25, 30)
        cv2.putText(frame, "Camera not available", (max(10, width // 2 - 130), height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (210, 215, 220), 2, cv2.LINE_AA)
        return frame
    if frame.shape[1] != width or frame.shape[0] != height:
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return cv2.flip(frame, 1) if mirrored else frame


def choose_camera_window(cameras: list[tuple[int | str, str]], width: int, height: int,
                         selected: int = 0) -> int | str | None:
    """Modal picker with a live preview: A/D or arrows change, Enter starts, Q cancels."""
    if not cameras:
        return None
    selected = selected if 0 <= selected < len(cameras) else 0
    panel_width = 360
    capture = _open_capture(cameras[selected][0], width, height)
    cv2.namedWindow(CAMERA_WINDOW, window_flags())
    cv2.resizeWindow(CAMERA_WINDOW, width + panel_width, height)
    try:
        while True:
            frame = _camera_preview(capture, width, height)
            panel = render_camera_panel(panel_width, frame.shape[0], cameras, selected)
            cv2.imshow(CAMERA_WINDOW, compose_dashboard(frame, panel))
            key = cv2.waitKey(30) & 0xFF
            if key in (10, 13, 32):
                return cameras[selected][0]
            if key in (ord("q"), ord("Q"), 27):
                return None
            next_index = selected
            if key in (ord("a"), ord("A"), 81, 2):
                next_index = (selected - 1) % len(cameras)
            elif key in (ord("d"), ord("D"), 83, 3):
                next_index = (selected + 1) % len(cameras)
            elif ord("1") <= key <= ord("9"):
                choice = key - ord("1")
                if choice < len(cameras):
                    next_index = choice
            if next_index != selected:
                selected = next_index
                if capture is not None:
                    capture.release()
                capture = _open_capture(cameras[selected][0], width, height)
            if cv2.getWindowProperty(CAMERA_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        if capture is not None:
            capture.release()
        cv2.destroyWindow(CAMERA_WINDOW)


def open_camera(index: int | str | None, width: int, height: int,
                info: dict | None = None) -> cv2.VideoCapture:
    system = platform.system()
    label = ""
    if index is None:
        cameras = find_cameras(system)
        if len(cameras) > 1:
            index = choose_camera_window(cameras, width, height)
            if index is None:
                raise RuntimeError("Camera selection cancelled.")
            label = dict(cameras)[index]
        elif cameras:
            index, label = cameras[0]
        elif system == "Windows" and windows_camera_names():
            list_cameras(system)
            raise RuntimeError(
                "Only virtual cameras were found. Connect a webcam, or pick one of the cameras above with --camera N."
            )
        else:
            index = 0
    else:
        label = camera_label(index, system)
    name = f"{index}" + (f" ({label})" if label else "")
    if info is not None:
        info["label"] = name
    print(f"[Webcam] Using webcam {name}.")

    capture = _open_capture(index, width, height, system)
    if capture is None:
        if system in ("Linux", "Windows"):
            list_cameras(system)
        hint = {
            "Linux": "list the webcams with 'v4l2-ctl --list-devices'",
            "Darwin": ("give Terminal camera access in System Settings → "
                       "Privacy & Security → Camera, or try --camera 1"),
        }.get(system, "try another --camera number from the list above")
        raise RuntimeError(
            f"Webcam {index} is not available. Close any other apps using it, or {hint}."
        )
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
    # Blur at the model resolution and upscale once: blurring 960x540 every
    # time was one of the most expensive steps in the loop.
    sigma = max(0.8, 2.2 * raw.shape[1] / max(width, 1))
    raw = cv2.GaussianBlur(raw, (0, 0), sigmaX=sigma, sigmaY=sigma)
    resized = cv2.resize(raw, (width, height), interpolation=cv2.INTER_LINEAR)
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

    x, y, width, height = cv2.boundingRect((mask > 0.01).astype(np.uint8))
    if width <= 0 or height <= 0:
        return background.copy()
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
    mask: np.ndarray | None = None,
) -> bool:
    """Whether someone is in the frame; pass `mask` to reuse a fresh one."""
    if mask is None:
        mask = person_mask(segmenter, image, timestamp_ms, width, height)
    return float((mask > 0.5).mean()) > PERSON_AREA_LIMIT


def custom_sound(name: str) -> Path | None:
    """User-provided sound in assets/<name>.<ext>, whatever the extension's case."""
    for suffix in CUSTOM_SOUND_SUFFIXES:
        path = APP_DIR / "assets" / f"{name}{suffix}"
        if path.is_file():
            return path
    return None


def teleport_sound_path() -> Path:
    custom = custom_sound("teleport")
    if custom is not None:
        return custom
    generated = MODEL_DIR / "teleport.wav"
    return generated if generated.is_file() else dragonball.write_teleport_sound(generated)


def ssj_sound_paths() -> tuple[Path, Path, Path]:
    """Charge, transformation and hum: assets/<name>.MP3 if present, otherwise generated."""
    paths = []
    for name, writer in SSJ_SOUNDS.items():
        custom = custom_sound(name)
        generated = MODEL_DIR / f"{name}.wav"
        if custom is not None:
            paths.append(custom)
        else:
            paths.append(generated if generated.is_file() else writer(generated))
    return tuple(paths)


def latest_faces(recognizer, timestamp_ms: int | None = None) -> list:
    """The detector's latest face, or a recent one when the hands hide it."""
    faces = getattr(recognizer, "last_faces", [])
    recent = getattr(recognizer, "recent_faces", None)
    if not faces and recent is not None and timestamp_ms is not None:
        faces = recent(timestamp_ms)
    return faces if isinstance(faces, list) else []


def face_detected_ms(recognizer) -> int | None:
    """When the detector last saw a face (its own timestamp), or None if it does not say."""
    value = getattr(recognizer, "last_good_face_ms", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def latest_hands(recognizer) -> list:
    hands = getattr(recognizer, "last_hands", [])
    return hands if isinstance(hands, list) else []


def power_active(recognizer, timestamp_ms: int | None = None) -> bool:
    """Ki-charging pose in the detector's latest inference (the teleport wins)."""
    if getattr(recognizer, "last_teleport", False):
        return False
    width, height = getattr(recognizer, "last_size", (0, 0))
    return ssj.charging_from_landmarks(
        getattr(recognizer, "last_hands", []), latest_faces(recognizer, timestamp_ms), width, height
    )


def set_fullscreen(enabled: bool) -> None:
    mode = cv2.WINDOW_FULLSCREEN if enabled else cv2.WINDOW_NORMAL
    cv2.setWindowProperty(WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, mode)


PHASE_STYLES = {
    "calibrating": ("CALIBRATING", (60, 190, 255)),
    "ready": ("READY", (110, 220, 120)),
    "vanishing": ("VANISHING", (220, 210, 90)),
    "vanished": ("VANISHED", (175, 175, 175)),
    "appearing": ("APPEARING", (220, 210, 90)),
    "charging": ("CHARGING KI", (60, 190, 255)),
    "super": ("SUPER SAIYAN", (60, 215, 255)),
    "paused": ("PAUSED", (185, 185, 185)),
}
MODE_LABELS = {"dragonball": "Dragon Ball", "normal": "Normal vanish", "naruto": "Naruto"}


def _wrap(text: str, chars: int) -> list[str]:
    return textwrap.wrap(text, width=chars) or [""]


def _panel_line(panel: np.ndarray, text: str, x: int, y: int,
                scale: float = 0.52, color=(196, 204, 210), thickness: int = 1) -> int:
    cv2.putText(panel, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)
    return y + int(round(24 * scale / 0.52))


PANEL_BUTTON_HEIGHT = 34
PANEL_BUTTON_GAP = 8


def panel_controls(super_saiyan: bool, eyes: bool, brows: bool,
                   hair: bool = True) -> list[tuple[str, str, bool | None]]:
    """Clickable buttons of the side panel: (name, label, toggle state or None for a plain button)."""
    controls: list[tuple[str, str, bool | None]] = [("recalibrate", "Recalibrate background (SPACE)", None)]
    if super_saiyan:
        controls += [("eyes", "Eyes (E)", eyes), ("brows", "Brows (B)", brows), ("hair", "Hair (G)", hair)]
    return controls


# Super Saiyan switches: setting name, args attribute, label for the log.
FACE_SWITCHES = {
    "eyes": ("ssj_eyes", "Teal eyes"),
    "brows": ("ssj_brows", "Golden eyebrows"),
    "hair": ("ssj_hair", "Golden hair"),
}


def panel_buttons(width: int, height: int, count: int) -> list[tuple[int, int, int, int]]:
    """Rectangles (x0, y0, x1, y1) of the panel buttons at the bottom of the panel: the first one on its own row,
    the switches side by side on the row below (keeps room for the log)."""
    if count <= 0:
        return []
    bottom = height - 12
    rects = []
    if count > 1:
        top = bottom - PANEL_BUTTON_HEIGHT
        span = (width - 24 - PANEL_BUTTON_GAP * (count - 2)) / (count - 1)
        for index in range(count - 1):
            x0 = int(round(12 + index * (span + PANEL_BUTTON_GAP)))
            rects.append((x0, top, int(round(x0 + span)), bottom))
        bottom = top - PANEL_BUTTON_GAP
    return [(12, bottom - PANEL_BUTTON_HEIGHT, width - 12, bottom)] + rects


def panel_hit(width: int, height: int, controls, x: int, y: int) -> str | None:
    for (name, _, _), (x0, y0, x1, y1) in zip(controls, panel_buttons(width, height, len(controls))):
        if x0 <= x <= x1 and y0 <= y <= y1:
            return name
    return None


def render_status_panel(width: int, height: int, mode: str, phase: str, camera: str,
                        action: str, lines: list[str], version: str = "", controls=()) -> np.ndarray:
    """Side panel with the current step, keys, the recent messages and the clickable `controls`."""
    phase_label, accent = PHASE_STYLES.get(phase, ("READY", (110, 220, 120)))
    panel = np.empty((height, width, 3), np.uint8)
    panel[:] = (24, 27, 32)
    cv2.line(panel, (0, 0), (0, height - 1), (70, 80, 90), 1)
    x = 18
    y = 34
    y = _panel_line(panel, "VanishCam", x, y, 0.82, (240, 244, 247), 2)
    y = _panel_line(panel, f"Mode: {MODE_LABELS.get(mode, mode)}", x, y, 0.5, (150, 165, 175))
    y = _panel_line(panel, f"Camera: {camera}", x, y, 0.5, (150, 165, 175))
    if version:
        y = _panel_line(panel, f"Version: {version}", x, y, 0.5, (150, 165, 175))
    y += 8
    y = _panel_line(panel, phase_label, x, y, 0.7, accent, 2)
    y += 10
    y = _panel_line(panel, "NEXT STEP", x, y, 0.46, (120, 135, 145))
    for line in _wrap(action, 40):
        y = _panel_line(panel, line, x, y, 0.56, (238, 242, 245))
    y += 10
    y = _panel_line(panel, "KEYS", x, y, 0.46, (120, 135, 145))
    for line in ("V vanish   R reappear   S Super Saiyan",
                 "P pause   SPACE background   F fullscreen",
                 "E eyes  B brows  G hair   Q quit"):
        y = _panel_line(panel, line, x, y, 0.48, (185, 195, 202))
    rects = panel_buttons(width, height, len(controls))
    bottom = (rects[0][1] - 10) if rects else height - 12
    y += 10
    y = _panel_line(panel, "LOG", x, y, 0.46, (120, 135, 145))
    room = max(0, (bottom - y) // 18)
    for message in list(lines)[-room:] if room else []:
        for line in _wrap(message, 44):
            if y > bottom:
                break
            y = _panel_line(panel, line, x, y, 0.46, (150, 160, 168))
    for (name, label, state), (x0, y0, x1, y1) in zip(controls, rects):
        lit = bool(state)
        cv2.rectangle(panel, (x0, y0), (x1, y1), (70, 104, 122) if lit else (48, 54, 62), -1)
        cv2.rectangle(panel, (x0, y0), (x1, y1), (60, 190, 255) if lit else (111, 142, 153), 1)
        text = label if state is None else f"{label}: {'on' if state else 'off'}"
        _panel_line(panel, text, x0 + 10, (y0 + y1) // 2 + 6, 0.46 if state is not None else 0.5, (236, 239, 242))
    return panel


def compose_dashboard(display: np.ndarray, panel: np.ndarray) -> np.ndarray:
    """Video on the left, status panel on the right. The video pixels are untouched."""
    if display.shape[0] != panel.shape[0]:
        panel = cv2.resize(panel, (panel.shape[1], display.shape[0]), interpolation=cv2.INTER_NEAREST)
    return np.hstack((display, panel))


def ascii_text(text: str) -> str:
    """OpenCV's Hershey fonts only draw ASCII."""
    return text.encode("ascii", "replace").decode("ascii")


def render_camera_panel(width: int, height: int, cameras: list[tuple[int | str, str]],
                        selected: int) -> np.ndarray:
    panel = np.empty((height, width, 3), np.uint8)
    panel[:] = (24, 27, 32)
    cv2.line(panel, (0, 0), (0, height - 1), (70, 80, 90), 1)
    x = 18
    y = 36
    y = _panel_line(panel, "Choose camera", x, y, 0.72, (240, 244, 247), 2)
    y += 8
    for index, (source, label) in enumerate(cameras):
        if index == selected:
            cv2.rectangle(panel, (8, y - 19), (width - 8, y + 7), (52, 68, 80), -1)
        color = (245, 248, 250) if index == selected else (170, 180, 188)
        y = _panel_line(panel, f"{index + 1}. {ascii_text(label) or source}"[:34], x, y, 0.54, color)
        if label and isinstance(source, str):
            y = _panel_line(panel, f"   {source}", x, y, 0.44, (135, 150, 160))
    y = max(y + 12, height - 96)
    for line in ("A / D or arrows: change", "Enter: start", "Q: cancel"):
        y = _panel_line(panel, line, x, y, 0.5, (190, 200, 208))
    return panel


def status_snapshot(state, mode: str, super_saiyan: bool, power, gesture_help: str,
                    remaining: int | None) -> tuple[str, str]:
    """Action to show in the panel and the phase style to use."""
    if state.phase == "calibrating":
        return f"SETUP: step out of the frame. Background photo in {remaining or 0} s.", "calibrating"
    if state.phase == "ready":
        if super_saiyan and power.transformed:
            # Call apps blur everything that is not the person, and the aura lives outside the person.
            return ("Super Saiyan! Repeat the pose or press S to power down. "
                    "Turn off background blur in your call app to see the aura."), "super"
        if super_saiyan and power.phase == "charging":
            return "Charging ki... keep both fists in front of your face.", "charging"
        if super_saiyan:
            return f"{gesture_help} Or both fists in front of your face: Super Saiyan.", "ready"
        return gesture_help, "ready"
    if state.phase == "vanished":
        return "You are vanished. Repeat the gesture or press R to come back.", "vanished"
    if state.phase == "vanishing":
        return "Vanishing...", "vanishing"
    return "Coming back...", "appearing"


def draw_setup_marks(frame: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """Outline the detected person while the background is being captured."""
    if mask is None:
        return frame
    x, y, w, h = cv2.boundingRect((mask > 0.5).astype(np.uint8))
    if w <= 0 or h <= 0:
        return frame
    cv2.rectangle(frame, (max(0, x - 8), max(0, y - 8)),
                  (min(frame.shape[1] - 1, x + w + 8), min(frame.shape[0] - 1, y + h + 8)),
                  (60, 190, 255), 2, cv2.LINE_AA)
    return frame


def window_flags() -> int:
    # GUI_NORMAL hides the Qt toolbar with its unreadable zoom/save buttons and tooltips.
    return cv2.WINDOW_NORMAL | getattr(cv2, "WINDOW_GUI_NORMAL", 0)


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
    print("[Webcam] Self-test passed: models, images and audio are present.")
    return 0


def detect_face_points(image: np.ndarray) -> np.ndarray | None:
    """Face landmarks in pixels on a still picture (an imported Super Saiyan image)."""
    options = vision.FaceLandmarkerOptions(
        base_options=base_options(FACE_MODEL), running_mode=vision.RunningMode.IMAGE, num_faces=1,
    )
    landmarker = vision.FaceLandmarker.create_from_options(options)
    try:
        rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        result = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    finally:
        landmarker.close()
    if not result.face_landmarks:
        return None
    return ssj_face.points_from_landmarks(result.face_landmarks[0], image.shape[1], image.shape[0])


def load_hair(log) -> ssj_face.HairOverlay | None:
    """The user's imported Super Saiyan hair, if any. A bad picture never stops the app."""
    try:
        views = ssj_face.load_hair_views(HAIR_DIR, detect_face_points, log)
    except Exception as error:
        log(f"[Super Saiyan] Could not import the hair: {error}")
        return None
    if views:
        log(f"[Super Saiyan] Golden hair ready ({len(views)} view{'s' if len(views) > 1 else ''}).")
        return ssj_face.HairOverlay(views)
    if not ssj_face.hair_sources(HAIR_DIR):
        log("[Super Saiyan] No golden hair yet: set it up in the home window (start VanishCam "
            "from its shortcut) or run with --ssj-hair-photos.")
    return None


def hair_instructions() -> str:
    return (
        f"\n[Super Saiyan] Photos saved in {HAIR_DIR}.\n"
        "Next steps (VanishCam never uploads anything; you choose the image tool):\n"
        "  1. Open ChatGPT or Gemini, attach one photo and paste this prompt:\n\n"
        f"     {ssj_face.HAIR_PROMPT}\n\n"
        f"  2. Save the result in {HAIR_DIR} as ssj_<name>.png (for example ssj_front.png).\n"
        "     Repeat for the other photos if you want the hair to follow your head when you turn it.\n"
        "  3. Start VanishCam: the hair is imported automatically and shows up when you go Super Saiyan.\n"
        f"The prompt is also in {HAIR_DIR / 'prompt.txt'}.\n"
    )


def take_hair_photos(camera: int | str | None, width: int, height: int, mirrored: bool) -> list[Path]:
    """Guided photos (front and both sides) to turn into Super Saiyan pictures with an image model.

    Closes only its own window (the home window may be open) and returns the saved photos.
    """
    capture = open_camera(camera, width, height)
    HAIR_DIR.mkdir(exist_ok=True)
    cv2.namedWindow(WINDOW_NAME, window_flags())
    taken: list[Path] = []
    try:
        for index, (name, hint) in enumerate(ssj_face.HAIR_VIEWS, start=1):
            action = (f"Golden hair photo {index}/{len(ssj_face.HAIR_VIEWS)}: {hint}, face fully visible, "
                      "good light. SPACE take it, S skip, Q quit.")
            print(f"[Super Saiyan] {action}")
            while True:
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("The webcam stopped sending frames.")
                if mirrored:
                    frame = cv2.flip(frame, 1)  # Same orientation as the live detection.
                panel = render_status_panel(PANEL_WIDTH, frame.shape[0], "dragonball", "ready", "photo", action, [],
                                            app_version())
                cv2.imshow(WINDOW_NAME, compose_dashboard(frame, panel))
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    return taken
                if key == ord("s"):
                    break
                if key == ord(" "):
                    path = HAIR_DIR / f"photo_{name}.jpg"
                    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    taken.append(path)
                    print(f"[Super Saiyan] Saved {path.name}.")
                    break
    finally:
        capture.release()
        cv2.destroyWindow(WINDOW_NAME)
        if taken:
            (HAIR_DIR / "prompt.txt").write_text(ssj_face.HAIR_PROMPT + "\n")
    return taken


def capture_hair_photos(args: argparse.Namespace) -> int:
    taken = take_hair_photos(args.camera, args.width, args.height, not args.no_mirror)
    if taken:
        print(hair_instructions())
    return 0 if taken else 1


def hair_status() -> str:
    pictures = len(ssj_face.hair_sources(HAIR_DIR))
    if pictures:
        return f"{pictures} golden picture{'s' if pictures > 1 else ''} in the folder. Check them with [H]."
    if HAIR_DIR.is_dir() and any(HAIR_DIR.glob("photo_*.jpg")):
        return "Photos taken. Copy the prompt, make the golden pictures, save them as ssj_front.png..."
    return "Not set up: take the photos first."


def check_hair_pictures() -> list[str]:
    messages: list[str] = []
    sources = ssj_face.hair_sources(HAIR_DIR)
    if not sources:
        return ["No golden pictures yet: save them in the folder as ssj_front.png, ssj_left.png, ssj_right.png."]
    views = ssj_face.load_hair_views(HAIR_DIR, detect_face_points, messages.append)
    messages.append(f"{len(views)} of {len(sources)} golden pictures ready."
                    + (" The hair shows up when you go Super Saiyan." if views else ""))
    return messages


def home_actions(args: argparse.Namespace, cameras: list[tuple[int | str, str]]) -> home_ui.HomeActions:
    def choose(settings: home_ui.HomeSettings):
        sources = [source for source, _ in cameras]
        selected = sources.index(settings.camera) if settings.camera in sources else 0
        source = choose_camera_window(cameras, args.width, args.height, selected)
        return None if source is None else (source, dict(cameras)[source])

    def photos(settings: home_ui.HomeSettings) -> list[str]:
        taken = take_hair_photos(settings.camera, args.width, args.height, not args.no_mirror)
        if not taken:
            return ["No photos taken."]
        return [f"Saved {len(taken)} photo{'s' if len(taken) > 1 else ''}. Next: [P] copy the prompt, give it to "
                "ChatGPT or Gemini with a photo, and save the result in the folder ([O]) as ssj_front.png."]

    def prompt() -> list[str]:
        if home_ui.copy_text(ssj_face.HAIR_PROMPT):
            return ["Prompt copied: paste it in ChatGPT or Gemini together with one of your photos."]
        return [f"Could not copy the prompt: it is in {HAIR_DIR / 'prompt.txt'}."]

    def folder() -> list[str]:
        if not (HAIR_DIR / "prompt.txt").exists():
            HAIR_DIR.mkdir(exist_ok=True)
            (HAIR_DIR / "prompt.txt").write_text(ssj_face.HAIR_PROMPT + "\n")
        if home_ui.open_folder(HAIR_DIR):
            return [f"Opened {HAIR_DIR}."]
        return [f"Could not open the folder: {HAIR_DIR}"]

    return home_ui.HomeActions(cameras=cameras, choose_camera=choose, take_photos=photos, copy_prompt=prompt,
                               open_folder=folder, check_pictures=check_hair_pictures, hair_status=hair_status)


def initial_home_settings(args: argparse.Namespace, saved: dict,
                          cameras: list[tuple[int | str, str]]) -> home_ui.HomeSettings:
    """Last effect and camera (by name); an explicit --camera wins."""
    mode = saved.get("mode") if saved.get("mode") in MODES else (args.mode or DEFAULT_MODE)
    settings = home_ui.HomeSettings(mode=mode)
    # The command line can only switch them off; otherwise the last choice in the window is kept.
    settings.eyes = bool(saved.get("eyes", True)) and getattr(args, "ssj_eyes", True)
    settings.brows = bool(saved.get("brows", True)) and getattr(args, "ssj_brows", True)
    settings.hair = bool(saved.get("hair", True)) and getattr(args, "ssj_hair", True)
    if args.camera is not None:
        settings.camera, settings.camera_label = args.camera, camera_label(args.camera)
    elif cameras:
        settings.camera, settings.camera_label = next(
            (camera for camera in cameras if camera[1] and camera[1] == saved.get("camera")), cameras[0])
    return settings


def run_home(args: argparse.Namespace) -> home_ui.HomeSettings | None:
    cameras = find_cameras()
    settings = initial_home_settings(args, home_ui.load_settings(SETTINGS_PATH), cameras)
    chosen = home_ui.run_home(settings, home_actions(args, cameras), app_version())
    if chosen is not None:
        home_ui.save_settings(SETTINGS_PATH, chosen)
    return chosen


def run() -> int:
    args = parse_args()
    print(f"[VanishCam] Version {app_version()}")
    if getattr(args, "list_cameras", False):
        list_cameras()
        return 0
    if getattr(args, "self_test", False):
        return self_test()
    if getattr(args, "ssj_hair_photos", False):
        return capture_hair_photos(args)
    if getattr(args, "home", False):
        chosen = run_home(args)
        if chosen is None:
            return 0
        args.camera, mode = chosen.camera, chosen.mode
        args.ssj_eyes, args.ssj_brows, args.ssj_hair = chosen.eyes, chosen.brows, chosen.hair
    else:
        mode = choose_mode() if getattr(args, "menu", False) else (args.mode or DEFAULT_MODE)
    if mode is None:
        return 0
    with ExitStack() as resources:
        return run_camera(args, resources, mode)


def run_camera(args: argparse.Namespace, resources: ExitStack, mode: str) -> int:
    download_models(mode)
    camera_info: dict[str, str] = {}
    input_video = getattr(args, "input_video", None)
    if input_video:
        capture = frame_source.VideoFileSource(input_video)
        camera_name = Path(input_video).name
        print(f"[Webcam] Using the clip {camera_name} instead of a webcam.")
    else:
        capture = open_camera(args.camera, args.width, args.height, camera_info)
        camera_name = camera_info.get("label", "auto")
        capture.set(cv2.CAP_PROP_FPS, args.fps)
    if getattr(args, "capture_thread", False):
        capture = frame_source.LatestFrameCapture(capture)
    resources.callback(capture.release)
    log_lines: deque[str] = deque(maxlen=24)

    def log(message: str) -> None:
        print(message)
        log_lines.append(message)
    bench = frame_source.StageBench(args.bench) if getattr(args, "bench", None) else None
    stage = bench.stage if bench is not None else frame_source.no_stage
    bench_super_saiyan = bench is not None and getattr(args, "bench_super_saiyan", False)
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
    # The face arrives ~12.5 times a second: the tracker gives one per frame, the dynamics make the hair move.
    head_tracker = ssj_face.head_tracker()
    hair_dynamics = ssj_motion.HairDynamics()
    last_face_seen: list = [None, None]  # Detection time (ms) and faces list of the last face fed to the tracker.
    charge_sound = transform_sound = hum_sound = None
    if super_saiyan:
        # Created after the teleport sound, which owns the mixer and is closed last.
        charge_sound, transform_sound, hum_sound = (
            VanishSound(path, device=audio_device) for path in ssj_sound_paths()
        )
        for extra in (charge_sound, transform_sound, hum_sound):
            resources.callback(extra.close)
    resources.callback(cv2.destroyAllWindows)
    headless = getattr(args, "headless", False)
    hud = not getattr(args, "no_hud", False) and not headless
    if not headless:
        cv2.namedWindow(WINDOW_NAME, window_flags())
        cv2.resizeWindow(WINDOW_NAME, args.width + (PANEL_WIDTH if hud else 0), args.height)

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
    log("[Webcam] Step out of the frame: the background photo is taken in 4 seconds.")
    log(f"[Webcam] {gesture_help}")
    hair = None
    if super_saiyan:
        log("[Webcam] Closed fists in front of your face, one on each side, for 1.5 seconds: Super Saiyan. "
            "Repeat (or press S) to go back to normal.")
        hair = load_hair(log)
    log("[Webcam] Keys in the window: V vanish, R reappear/restart setup, S Super Saiyan "
        "(E eyes, B brows, G hair), "
        "SPACE background, P pause, F fullscreen, Q quit.")

    def transform(now: float) -> None:
        power.transform(now)
        hair_dynamics.kick()  # The hair pops up with the flash.
        charge_sound.stop(80)
        transform_sound.play()
        hum_sound.play(loops=-1, fade_ms=400)
        log("[Dragon Ball] Super Saiyan!")

    def power_down(now: float) -> None:
        power.power_down(now)
        charge_sound.stop()
        hum_sound.stop(500)
        log("[Dragon Ball] Back to normal.")

    def stop_power() -> None:
        power.reset()
        power_hold.reset()
        head_tracker.reset()
        hair_dynamics.reset()
        last_face_seen[:] = [None, None]
        if hair is not None:
            hair.reset()
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

    paused = False
    last_display: np.ndarray | None = None
    panel_cache: dict[tuple, np.ndarray] = {}

    def controls() -> list:
        return panel_controls(super_saiyan, getattr(args, "ssj_eyes", True), getattr(args, "ssj_brows", True),
                              getattr(args, "ssj_hair", True))

    clicked: list[str | None] = [None]
    panel_origin = [0, 0]  # Where the panel starts in the window (the video width) and its height.

    def on_mouse(event, x, y, flags, userdata) -> None:
        # Act on press: with a touchpad the pointer often drifts off the button before the release.
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked[0] = panel_hit(PANEL_WIDTH, panel_origin[1], controls(), x - panel_origin[0], y)

    if hud:
        cv2.setMouseCallback(WINDOW_NAME, on_mouse)

    def toggle_face(name: str) -> None:
        attribute, label = FACE_SWITCHES[name]
        value = not getattr(args, attribute, True)
        setattr(args, attribute, value)
        home_ui.update_settings(SETTINGS_PATH, **{name: value})
        log(f"[Super Saiyan] {label} {'on' if value else 'off'}.")

    def status_panel(phase_key: str, action: str, height: int, lines) -> np.ndarray:
        """Render the side panel only when its content changes."""
        current = controls()
        key = (phase_key, action, camera_name, height, tuple(lines), tuple(current))
        panel = panel_cache.get(key)
        if panel is None:
            panel = render_status_panel(
                PANEL_WIDTH, height, mode, phase_key, camera_name, action, list(lines), app_version(), current
            )
            if len(panel_cache) >= 6:
                panel_cache.clear()
            panel_cache[key] = panel
        return panel
    try:
        while True:
            if bench is not None:
                bench.frame_started()
            with stage("capture"):
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

            if paused:
                frozen = last_display if last_display is not None else camera_frame
                panel = status_panel(
                    "paused", "Paused. Press P to continue, R to restart the setup.",
                    frozen.shape[0], log_lines,
                )
                if virtual_camera is not None:
                    send_virtual_frame(virtual_camera, cv2.flip(frozen, 1) if flip_output else frozen)
                cv2.imshow(WINDOW_NAME, compose_dashboard(frozen, panel) if hud else frozen)
                key = cv2.waitKey(30) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key in (ord("p"), ord("P")):
                    paused = False
                    log("[Webcam] Resumed.")
                elif key == ord("r"):
                    paused = False
                    begin_calibration(now)
                    log("[Webcam] Restarting the setup...")
                elif key == ord("f"):
                    state.fullscreen = not state.fullscreen
                    set_fullscreen(state.fullscreen)
                if virtual_camera is not None:
                    virtual_camera.sleep_until_next_frame()
                continue

            elapsed_ms = int((now - started) * 1000)
            mp_image = None

            def frame_image() -> mp.Image:
                nonlocal mp_image
                if mp_image is None:
                    rgb = cv2.cvtColor(camera_frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                return mp_image

            def update_mask(every: float) -> np.ndarray | None:
                nonlocal last_mask, last_mask_at
                if last_mask is None or now - last_mask_at >= every:
                    with stage("mask"):
                        last_mask = person_mask(segmenter, frame_image(), elapsed_ms, width, height)
                    last_mask_at = now
                return last_mask

            display = camera_frame
            if state.phase == "calibrating":
                elapsed = now - state.calibration_started
                remaining = max(0, int(np.ceil(CALIBRATION_SECONDS - elapsed)))
                if remaining != calibration_remaining:
                    log(f"[Webcam] Background photo in {remaining} seconds.")
                    calibration_remaining = remaining
                sampling = elapsed >= CALIBRATION_SECONDS - BACKGROUND_SAMPLE_SECONDS
                if sampling and now - last_person_check >= PERSON_CHECK_SECONDS:
                    last_person_check = now
                    if (calibration_retries < MAX_CALIBRATION_RETRIES
                            and person_in_frame(segmenter, frame_image(), elapsed_ms, width, height,
                                                update_mask(0.3))):
                        calibration_retries += 1
                        log("[Webcam] Someone is still in the frame: step out, waiting 2 more seconds.")
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
                        log("[Webcam] Could not capture the background with nobody in the frame; using it anyway. "
                            "Press SPACE to retry.")
                    background_samples.clear()
                    calibration_retries = 0
                    state.phase = "ready"
                    hold.reset()
                    log("[Webcam] Background ready. You can step back into the frame.")
                    if bench_super_saiyan and super_saiyan and not power.transformed:
                        transform(now)

            elif background is None:
                begin_calibration(now)

            else:
                if (state.phase in ("ready", "vanished")
                        and now - state.last_gesture_check >= gesture_interval):
                    state.last_gesture_check = now
                    debug = args.gesture_debug and now - last_gesture_report >= 1.0
                    if debug:
                        last_gesture_report = now
                    with stage("gestures"):
                        active = gesture_active(mode, recognizer, frame_image(), elapsed_ms, debug)
                    if hold.update(active, now):
                        hold_announced = False
                        start_effect("vanishing" if state.phase == "ready" else "appearing",
                                     time.perf_counter())
                    elif mode == "dragonball" and hold.since is not None and not hold_announced:
                        hold_announced = True
                        log(f"[Dragon Ball] Keep your fingers on your forehead for {HOLD_SECONDS[mode]:g} s...")
                    elif hold.since is None:
                        hold_announced = False
                    if super_saiyan and state.phase == "ready":
                        charging = power_active(recognizer, elapsed_ms)
                        if debug:
                            print(f"[Super Saiyan] hands={recognizer.last_hand_count}, "
                                  f"face={recognizer.last_face_found}, charging={charging}")
                        was_charging = power_hold.since is not None
                        if power_hold.update(charging, now):
                            if power.transformed:
                                power_down(now)
                            else:
                                transform(now)
                        elif power_hold.since is not None and not was_charging and power.phase == "off":
                            charge_sound.play()
                            log("[Dragon Ball] Charging ki...")
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
                        display = dragonball.render_teleport(camera_frame, background, mask, age)
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
                            camera_frame, background, mask,
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
                    mask = update_mask(0.1)
                    faces = latest_faces(recognizer, elapsed_ms)
                    seconds = elapsed_ms / 1000.0
                    # Feed the tracker only new detections (the stale face kept while fists hide it is not one).
                    detected_ms = face_detected_ms(recognizer)
                    if detected_ms is not None:
                        is_new = bool(faces) and detected_ms != last_face_seen[0]
                    else:  # A detector that does not timestamp its faces: a new list is a new detection.
                        is_new = bool(faces) and faces is not last_face_seen[1]
                    detection = None
                    if is_new:
                        last_face_seen[:] = [detected_ms, faces]
                        detection = ssj_face.points_from_landmarks(faces[0], width, height)
                    effect_started = time.perf_counter() if bench is not None else 0.0
                    face = head_tracker.update(
                        seconds, detection, None if detected_ms is None or not is_new else detected_ms / 1000.0)
                    placed = None
                    # Switched off: the user's own hair, aura only.
                    live_hair = hair if getattr(args, "ssj_hair", True) else None
                    if face is not None:
                        hair_dynamics.step(seconds, *ssj_face.head_pose(face))
                        if live_hair is not None:
                            placed = live_hair.place_live(face, camera_frame.shape, seconds,
                                                          hair_dynamics.motion(levels.aura), head_tracker.yaw)
                    # The head lets the aura drop the chair from the silhouette.
                    head = ssj.head_ellipse_from_points(face)
                    display = ssj.render_super_saiyan(camera_frame, mask, levels, now, aura, head,
                                                      face, live_hair, latest_hands(recognizer),
                                                      getattr(args, "ssj_eyes", True),
                                                      getattr(args, "ssj_brows", True), placed)
                    if bench is not None:
                        bench.samples["super"].append(time.perf_counter() - effect_started)

            output_started = time.perf_counter() if bench is not None else 0.0
            view_display = display
            if hud and state.phase == "calibrating":
                view_display = draw_setup_marks(display.copy(), update_mask(0.3))
            last_display = view_display
            if virtual_camera is not None:
                # Zoom and Meet already mirror the local preview: viewers see the image the right way round.
                send_virtual_frame(virtual_camera, cv2.flip(display, 1) if flip_output else display)
            action, phase_key = status_snapshot(
                state, mode, super_saiyan, power, gesture_help, calibration_remaining
            )
            panel = status_panel(phase_key, action, display.shape[0], log_lines)
            panel_origin[:] = [view_display.shape[1], display.shape[0]]
            if not headless:
                cv2.imshow(WINDOW_NAME, compose_dashboard(view_display, panel) if hud else view_display)
            key = cv2.waitKey(1) & 0xFF if not headless else 0xFF
            if bench is not None:
                bench.samples["output"].append(time.perf_counter() - output_started)
                if bench.frame_finished():
                    break
            button, clicked[0] = clicked[0], None
            if key in (ord("e"), ord("E")):
                button = "eyes"
            elif key in (ord("b"), ord("B")):
                button = "brows"
            elif key in (ord("g"), ord("G")):
                button = "hair"
            if button in FACE_SWITCHES and super_saiyan:
                toggle_face(button)
            if key in (ord("q"), 27):
                break
            if key in (ord("p"), ord("P")):
                paused = True
                log("[Webcam] Paused. Press P to continue.")
            elif key == ord(" ") or button == "recalibrate":
                begin_calibration(now)
                log("[Webcam] Step out of the frame: the new background photo is taken in 4 seconds.")
            elif key == ord("r") and (background is None or state.phase == "calibrating"):
                begin_calibration(now)
                log("[Webcam] Restarting the setup...")
            elif key == ord("r") and background is not None:
                log("[Webcam] Reappear (R).")
                if state.phase == "vanished":
                    start_effect("appearing", time.perf_counter())
                elif state.phase == "vanishing":
                    state.phase = "ready"
                    state.vanish_started = None
                    vanished_frame = None
                    log_anchor = None
            elif key == ord("v") and background is not None and state.phase in ("ready", "appearing"):
                log("[Webcam] Vanish (V).")
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
        if bench is not None:
            for line in bench.report():
                print(line)

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
