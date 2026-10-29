"""PyInstaller macOS .app build (experimental: it has not been run on a Mac yet).

Build with BUILD_MACOS.sh, which installs the dependencies and the models first.
The app still needs OBS Studio 30 or later for its virtual camera.
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


root = Path(SPECPATH).resolve()
# PyInstaller needs .icns on macOS; the repo only ships a .ico, so use it if someone adds it.
icon_file = root / "assets" / "vanish_icon.icns"
resources = [
    (root / "hand_landmarker.task", "."),
    (root / "face_landmarker.task", "."),
    (root / "models" / "gesture_recognizer.task", "models"),
    (root / "models" / "selfie_segmenter_landscape.tflite", "models"),
    (root / "assets" / "substitution_log.png", "assets"),
    (root / "assets" / "vanish.MP3", "assets"),
]
optional = [
    (root / "models" / "selfie_multiclass_256x256.tflite", "models"),
]
missing = [str(path) for path, _ in resources if not path.is_file()]
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
    [],
    exclude_binaries=True,
    name="VanishCam",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VanishCam",
)
app = BUNDLE(
    coll,
    name="VanishCam.app",
    icon=str(icon_file) if icon_file.is_file() else None,
    bundle_identifier="com.agupane.vanishcam",
    info_plist={
        "CFBundleName": "VanishCam",
        "CFBundleDisplayName": "VanishCam",
        "CFBundleShortVersionString": "0.0.0",
        "NSCameraUsageDescription": "VanishCam needs the camera to apply the disappearance effects.",
        "NSHighResolutionCapable": True,
    },
)
