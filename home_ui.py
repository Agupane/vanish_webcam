"""Home window: choose the effect and the camera and set up the Super Saiyan hair, then start.

Drawn with OpenCV like the effect menu (ASCII text only). The actions (camera picker, photos, folder...)
are callbacks from vanish_cam, so this module can be tested without a webcam.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import textwrap
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

WINDOW = "VanishCam"
WIDTH = 720
HEIGHT = 690
MARGIN = 30
MODES = (("dragonball", "Dragon Ball"), ("normal", "Normal vanish"), ("naruto", "Naruto"))
MESSAGE_LINES = 4

BACKGROUND = (26, 29, 34)
BOX = (48, 54, 62)
BOX_SELECTED = (70, 104, 122)
BORDER = (111, 142, 153)
ACCENT = (60, 190, 255)
TEXT = (236, 239, 242)
DIM = (150, 165, 175)
HEADING = (120, 135, 145)
START = (58, 140, 70)


@dataclass
class Button:
    name: str
    label: str
    rect: tuple[int, int, int, int]  # x0, y0, x1, y1
    key: str = ""

    def contains(self, x: int, y: int) -> bool:
        x0, y0, x1, y1 = self.rect
        return x0 <= x <= x1 and y0 <= y <= y1


@dataclass
class HomeSettings:
    mode: str = "dragonball"
    camera: int | str | None = None
    camera_label: str = ""
    eyes: bool = True  # Super Saiyan teal irises.
    brows: bool = True  # Super Saiyan golden eyebrows.
    hair: bool = True  # Super Saiyan imported golden hair (off: aura only, the user's own hair).


@dataclass
class HomeActions:
    """What the buttons do. Each action returns the messages to show in the window."""
    cameras: list[tuple[int | str, str]] = field(default_factory=list)
    choose_camera: Callable[[HomeSettings], tuple[int | str, str] | None] = lambda settings: None
    take_photos: Callable[[HomeSettings], list[str]] = lambda settings: []
    copy_prompt: Callable[[], list[str]] = lambda: []
    open_folder: Callable[[], list[str]] = lambda: []
    check_pictures: Callable[[], list[str]] = lambda: []
    hair_status: Callable[[], str] = lambda: ""


# ---------- layout ----------

EFFECT_TOP = 112
CAMERA_TOP = 228
HAIR_TOP = 318
MESSAGES_TOP = 500
START_TOP = 610
# Super Saiyan switches: (setting, key) and their labels.
SWITCHES = (("eyes", "e"), ("brows", "b"), ("hair", "g"))
SWITCH_LABELS = {"eyes": "[E] Teal eyes", "brows": "[B] Gold brows", "hair": "[G] Gold hair"}


def layout(show_camera: bool, show_hair: bool) -> list[Button]:
    """Every clickable area; hidden sections have no buttons."""
    buttons = []
    inner = WIDTH - 2 * MARGIN
    gap = 15
    width = (inner - 2 * gap) // 3
    for index, (mode, label) in enumerate(MODES):
        x0 = MARGIN + index * (width + gap)
        buttons.append(Button(f"mode:{mode}", f"{index + 1}  {label}", (x0, EFFECT_TOP, x0 + width, EFFECT_TOP + 56),
                              str(index + 1)))
    if show_camera:
        buttons.append(Button("camera", "[W] Change", (WIDTH - MARGIN - 150, CAMERA_TOP, WIDTH - MARGIN,
                                                        CAMERA_TOP + 40), "w"))
    if show_hair:
        gap = 10
        width = (inner - 3 * gap) // 4
        top = HAIR_TOP + 48
        for index, (name, label, key) in enumerate((
                ("photos", "[T] Take photos", "t"), ("prompt", "[P] Copy prompt", "p"),
                ("folder", "[O] Open folder", "o"), ("check", "[H] Check pictures", "h"))):
            x0 = MARGIN + index * (width + gap)
            buttons.append(Button(name, label, (x0, top, x0 + width, top + 44), key))
        top += 56
        width = (inner - 2 * gap) // 3
        for index, (name, key) in enumerate(SWITCHES):
            x0 = MARGIN + index * (width + gap)
            buttons.append(Button(name, "", (x0, top, x0 + width, top + 38), key))
    buttons.append(Button("start", "START  (Enter)", (MARGIN, START_TOP, WIDTH - MARGIN, START_TOP + 56)))
    return buttons


def hit(buttons: list[Button], x: int, y: int) -> str | None:
    for button in buttons:
        if button.contains(x, y):
            return button.name
    return None


def key_action(buttons: list[Button], key: int) -> str | None:
    if key in (10, 13):
        return "start"
    if key in (ord("q"), ord("Q"), 27):
        return "quit"
    if 0 < key < 128:
        char = chr(key).lower()
        for button in buttons:
            if button.key and button.key == char:
                return button.name
    return None


# ---------- drawing ----------

def ascii_text(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _text(image: np.ndarray, text: str, x: int, y: int, scale: float = 0.52,
          color=TEXT, thickness: int = 1) -> None:
    cv2.putText(image, ascii_text(text), (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def _button(image: np.ndarray, button: Button, selected: bool = False, fill=None, hover: bool = False) -> None:
    x0, y0, x1, y1 = button.rect
    color = fill or (BOX_SELECTED if selected else BOX)
    if hover:
        color = tuple(min(255, channel + 28) for channel in color)
    cv2.rectangle(image, (x0, y0), (x1, y1), color, -1, cv2.LINE_AA)
    cv2.rectangle(image, (x0, y0), (x1, y1), ACCENT if selected or hover else BORDER, 2, cv2.LINE_AA)
    scale = 0.75 if button.name == "start" else 0.5
    thickness = 2 if button.name == "start" or selected else 1
    (width, height), _ = cv2.getTextSize(button.label, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    _text(image, button.label, (x0 + x1 - width) // 2, (y0 + y1 + height) // 2, scale, TEXT, thickness)


def _checkbox(image: np.ndarray, button: Button, checked: bool, hover: bool = False) -> None:
    """A toggle drawn as a button with a tick box on the left; highlighted while on."""
    x0, y0, x1, y1 = button.rect
    fill = BOX_SELECTED if checked else BOX
    if hover:
        fill = tuple(min(255, channel + 28) for channel in fill)
    cv2.rectangle(image, (x0, y0), (x1, y1), fill, -1, cv2.LINE_AA)
    cv2.rectangle(image, (x0, y0), (x1, y1), ACCENT if checked or hover else BORDER, 2, cv2.LINE_AA)
    side = (y1 - y0) - 18
    bx, by = x0 + 12, y0 + 9
    cv2.rectangle(image, (bx, by), (bx + side, by + side), TEXT, 2, cv2.LINE_AA)
    if checked:
        cv2.line(image, (bx + 4, by + side // 2), (bx + side // 2 - 1, by + side - 5), ACCENT, 3, cv2.LINE_AA)
        cv2.line(image, (bx + side // 2 - 1, by + side - 5), (bx + side - 3, by + 4), ACCENT, 3, cv2.LINE_AA)
    _text(image, f"{button.label}: {'on' if checked else 'off'}", bx + side + 14, (y0 + y1) // 2 + 6, 0.5, TEXT)


def render_home(settings: HomeSettings, buttons: list[Button], camera_count: int,
                hair_status: str, messages: list[str], hover: str | None = None, version: str = "") -> np.ndarray:
    image = np.empty((HEIGHT, WIDTH, 3), np.uint8)
    image[:] = BACKGROUND
    _text(image, "VanishCam", MARGIN, 52, 1.0, TEXT, 2)
    if version:
        label = f"Version {version}"
        (width, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        _text(image, label, WIDTH - MARGIN - width, 52, 0.45, DIM)
    _text(image, "Set everything up here, then press START.", MARGIN, 80, 0.5, DIM)
    names = {button.name for button in buttons}

    _text(image, "EFFECT", MARGIN, EFFECT_TOP - 12, 0.46, HEADING)
    for button in buttons:
        if button.name.startswith("mode:"):
            _button(image, button, button.name == f"mode:{settings.mode}", hover=button.name == hover)

    _text(image, "CAMERA", MARGIN, CAMERA_TOP - 12, 0.46, HEADING)
    if camera_count == 0:
        camera = "No webcam found (virtual cameras are hidden)"
    else:
        camera = settings.camera_label or f"Camera {settings.camera}"
    _text(image, camera[:48], MARGIN, CAMERA_TOP + 26, 0.6, TEXT)
    if "camera" in names:
        _button(image, next(button for button in buttons if button.name == "camera"), hover=hover == "camera")

    if "photos" in names:
        _text(image, "SUPER SAIYAN", MARGIN, HAIR_TOP, 0.46, HEADING)
        _text(image, hair_status, MARGIN, HAIR_TOP + 28, 0.55, TEXT)
        for button in buttons:
            if button.name in ("photos", "prompt", "folder", "check"):
                _button(image, button, hover=button.name == hover)
            elif button.name in SWITCH_LABELS:
                on = getattr(settings, button.name)
                _checkbox(image, replace(button, label=SWITCH_LABELS[button.name]), on, hover=button.name == hover)

    _text(image, "MESSAGES", MARGIN, MESSAGES_TOP, 0.46, HEADING)
    y = MESSAGES_TOP + 26
    for line in messages[-MESSAGE_LINES:]:
        _text(image, line, MARGIN, y, 0.48, DIM)
        y += 22

    _button(image, next(button for button in buttons if button.name == "start"), fill=START, hover=hover == "start")
    return image


def use_arrow_cursor(window: str) -> None:
    """OpenCV's Windows windows show a crosshair, which makes buttons look unclickable. Best effort."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        user32.GetWindow.restype = ctypes.c_void_p
        user32.LoadCursorW.restype = ctypes.c_void_p
        user32.SetClassLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
        frame = user32.FindWindowW(None, window)
        image = user32.GetWindow(ctypes.c_void_p(frame), 5) if frame else None  # GW_CHILD: the image area.
        arrow = user32.LoadCursorW(None, ctypes.c_void_p(32512))  # IDC_ARROW
        for handle in (frame, image):
            if handle:
                user32.SetClassLongPtrW(handle, -12, arrow)  # GCLP_HCURSOR
    except Exception:
        pass


# ---------- loop ----------

def _wrapped(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        line = line.replace("[Super Saiyan] ", "").replace("[Webcam] ", "")
        result.extend(textwrap.wrap(ascii_text(line), 80) or [""])
    return result


def run_home(settings: HomeSettings, actions: HomeActions, version: str = "") -> HomeSettings | None:
    """Shows the home window until START (returns the settings) or Q/ESC/close (returns None)."""
    messages: deque[str] = deque(maxlen=MESSAGE_LINES)
    clicked: list[str | None] = [None]
    hover: list[str | None] = [None]
    current: list[list[Button]] = [[]]

    def on_mouse(event, x, y, flags, userdata):
        # Act on press: with a touchpad or touch screen the pointer often drifts off the button before release.
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked[0] = hit(current[0], x, y)
        elif event == cv2.EVENT_MOUSEMOVE:
            hover[0] = hit(current[0], x, y)

    def call(action, *args) -> None:
        try:
            messages.extend(_wrapped(action(*args)))
        except Exception as error:  # A failed action never closes the window.
            messages.extend(_wrapped([f"Problem: {error}"]))

    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW, on_mouse)
    status = None
    shown = False
    try:
        while True:
            show_hair = settings.mode == "dragonball"
            if show_hair and status is None:
                status = actions.hair_status()
            current[0] = layout(len(actions.cameras) > 1, show_hair)
            cv2.imshow(WINDOW, render_home(settings, current[0], len(actions.cameras), status or "",
                                           list(messages), hover[0], version))
            if not shown:
                use_arrow_cursor(WINDOW)
                shown = True
            key = cv2.waitKey(30) & 0xFF
            name, clicked[0] = clicked[0] or key_action(current[0], key), None
            if name == "quit":
                return None
            if name == "start":
                return settings
            if name and name.startswith("mode:"):
                settings.mode = name[5:]
            elif name == "camera":
                try:
                    choice = actions.choose_camera(settings)
                except Exception as error:
                    choice = None
                    messages.extend(_wrapped([f"Problem: {error}"]))
                if choice is not None:
                    settings.camera, settings.camera_label = choice
                cv2.setMouseCallback(WINDOW, on_mouse)
            elif name in SWITCH_LABELS:
                setattr(settings, name, not getattr(settings, name))
            elif name == "photos":
                call(actions.take_photos, settings)
                status = None
            elif name == "prompt":
                call(actions.copy_prompt)
            elif name == "folder":
                call(actions.open_folder)
            elif name == "check":
                call(actions.check_pictures)
                status = None
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return None
    finally:
        cv2.destroyWindow(WINDOW)


# ---------- settings and OS helpers ----------

def load_settings(path: Path) -> dict:
    """Last effect and camera name; {} when missing or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(path: Path, settings: HomeSettings) -> None:
    """The camera is remembered by name: indices change when webcams are plugged in or out."""
    try:
        data = {"mode": settings.mode, "camera": settings.camera_label, "eyes": settings.eyes,
                "brows": settings.brows, "hair": settings.hair}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def update_settings(path: Path, **values) -> None:
    """Change some saved settings (the live window's eye/brow/hair switches), keeping the others."""
    data = load_settings(path)
    data.update(values)
    try:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def copy_text(text: str, system: str | None = None) -> bool:
    """Put text on the clipboard with the OS tool; False if none worked."""
    system = system or platform.system()
    if system == "Windows":
        commands = [["clip"]]
    elif system == "Darwin":
        commands = [["pbcopy"]]
    else:
        commands = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for command in commands:
        if system != "Windows" and not shutil.which(command[0]):
            continue
        try:
            subprocess.run(command, input=ascii_text(text).encode("ascii"), check=True, timeout=5,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def open_folder(path: Path, system: str | None = None) -> bool:
    """Show a folder in the file manager without waiting for it."""
    system = system or platform.system()
    path.mkdir(parents=True, exist_ok=True)
    try:
        if system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if system == "Darwin" else "xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
