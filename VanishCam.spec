"""PyInstaller one-file build for the Windows webcam app."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


root = Path(SPECPATH).resolve()
icon_file = root / "assets" / "vanish_icon.ico"
resources = [
    (root / "hand_landmarker.task", "."),
    (root / "face_landmarker.task", "."),
    (root / "models" / "gesture_recognizer.task", "models"),
    (root / "models" / "selfie_segmenter_landscape.tflite", "models"),
    (root / "assets" / "substitution_log.png", "assets"),
    (root / "assets" / "vanish.MP3", "assets"),
]
# Super Saiyan without this model keeps the aura and skips the golden hair.
optional = [
    (root / "models" / "selfie_multiclass_256x256.tflite", "models"),
]
missing = [str(path) for path, _ in resources if not path.is_file()]
if not icon_file.is_file():
    missing.append(str(icon_file))
if missing:
    raise SystemExit("Missing files required for the build:\n" + "\n".join(missing))
resources += [item for item in optional if item[0].is_file()]

a = Analysis(
    [str(root / "vanish_cam.py")],
    pathex=[str(root)],
    binaries=collect_dynamic_libs("mediapipe"),
    datas=collect_data_files("mediapipe") + [(str(path), destination) for path, destination in resources],
    hiddenimports=[
        "dragonball_effect", "mediapipe.tasks.c", "pygame.mixer",
        "pyvirtualcam", "super_saiyan_effect", "vanish_sound",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VanishCam",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(icon_file),
)
