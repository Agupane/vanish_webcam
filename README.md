# VanishCam

[![tests](https://github.com/Agupane/vanish_webcam/actions/workflows/tests.yml/badge.svg)](https://github.com/Agupane/vanish_webcam/actions/workflows/tests.yml)

Disappearance effects for your webcam in Zoom, Google Meet or any video call app. Make a gesture and you vanish from the picture; repeat the gesture and you're back.

The default mode is **Dragon Ball**: rest your index and middle fingers together on your forehead for 1 second (Instant Transmission) and you're gone with comic speed lines and a flash. There is also **Normal** mode (two-finger V, you dissolve) and **Naruto** mode (palms together, smoke and a log).

Everything is processed on your computer: the video is not recorded or sent to any server.

## About this fork

This is a fork of [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) by Nicola Auriemma, who
created VanishCam with its Normal and Naruto modes; all credit for the original idea and app goes to them (original
README in [README_ORIGINAL.md](README_ORIGINAL.md)). This fork adds and changes:

- **Dragon Ball mode** as the default (Instant Transmission), with a **Super Saiyan** transformation (aura and golden hair).
- **Held, reversible gestures:** hold the pose to vanish, repeat it to come back, with reappear effects.
- **Better background capture** that waits until you are out of the frame.
- **Unmirrored output** to the virtual camera (the preview stays mirrored).
- **Installers** for Linux, macOS and Windows, plus a **virtual microphone** on Linux for the effect sounds.
- **SHA-256-verified model downloads** and a **pinned v4l2loopback** source build.
- **English UI** and docs, a **test suite**, and **CI** on Ubuntu, Windows, macOS arm64 and macOS Intel.

The full history is in [CHANGELOG.md](CHANGELOG.md).

## Installation

| System | Support | Virtual camera |
|---|---|---|
| **Ubuntu 22.04 / 24.04** (and Debian) | Full | v4l2loopback (installed by the installer) |
| **Windows 10 / 11** | Full | OBS Studio (installed by the installer) |
| **macOS on Apple silicon** (M1 or later) | Full | OBS Studio 30 or later |
| **macOS on Intel** | Experimental: uses older MediaPipe versions | OBS Studio 30 or later |

The installers download about 300 MB (Python, libraries and models) and do not touch your system Python.

### Ubuntu / Linux

```bash
curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
```

Or, if you'd rather review the code first:

```bash
git clone https://github.com/Agupane/vanish_webcam.git ~/VanishCam
cd ~/VanishCam
./install.sh
```

It asks for your `sudo` password to install the packages and the **VanishCam** virtual camera. If your Ubuntu's virtual camera package doesn't build for your kernel (this happens on 22.04 with 6.8 kernels), the installer builds the official version.

**Secure Boot:** if the installer asks for a one-time password to trust the virtual camera module, pick one and reboot. On startup a blue screen (MOK) appears: choose *Enroll MOK* → *Continue* → *Yes*, type that password and reboot. Then run the installer again.

#### Troubleshooting (Ubuntu)

The installer can be run again at any time; it skips what is already done.

To undo the Ubuntu integration (virtual camera, its DKMS module and the Applications menu entry), run `./uninstall-ubuntu.sh`. It keeps the app folder, `.venv`, `models/` and the shared Secure Boot key; delete the folder afterwards if you also want to remove those.

- **The preview is black or it picked the wrong camera.** You have more than one webcam (for example a disabled laptop camera and a USB one). Run `./vanishcam.sh --list-cameras` to see them, then start with `--camera 4` or `--camera /dev/video4`. Started without `--camera`, VanishCam opens a window with a live preview to choose the camera (`A`/`D` or arrows, `Enter`, `Q`).

- **`v4l2loopback-dkms` fails with "Bad return status for module build" (dpkg error code 10 or 1).** Ubuntu 22.04's package (0.12.7) does not build on kernels 6.8 or newer. The installer removes the broken package and builds upstream v4l2loopback 0.13.2 with DKMS instead. If apt keeps failing on it, clean it by hand and run the installer again: `sudo dpkg --purge --force-remove-reinstreq v4l2loopback-dkms && sudo dpkg --configure -a`. The build log is in `/var/lib/dkms/v4l2loopback/0.13.2/build/make.log`.
- **`modprobe: ERROR: could not insert 'v4l2loopback': Key was rejected by service`.** Secure Boot is on and the module's signing key (`/var/lib/shim-signed/mok/MOK.der`) is not enrolled. The installer registers it with `mokutil --import` and asks you for a one-time password. Reboot, choose *Enroll MOK* → *Continue* → *Yes* on the blue screen, type that password, and run the installer again. Check with `mokutil --test-key /var/lib/shim-signed/mok/MOK.der` (should say "is already enrolled") and `modinfo -F signer v4l2loopback` (should not be empty).
- **`linux-headers-… is not available` or "kernel headers are missing".** Your running kernel is older than the ones in the archive. Run `sudo apt update && sudo apt full-upgrade`, reboot, and run the installer again.
- **`NO_PUBKEY` / "repository is not signed" during `apt-get update`.** A third-party repository (yarn, etc.) has an expired or missing key. The installer continues anyway; to silence it, fix or remove that repository in `/etc/apt/sources.list.d/`.
- **After a kernel update the camera disappears.** DKMS rebuilds the module for the new kernel; if Secure Boot rejects it, run the installer again to sign it.
- **`OSError: libGLESv2.so.2` or `libEGL.so.1` when starting.** Install `libgles2 libegl1` (the installer does it).

### Windows

Open **PowerShell** (no need to run it as administrator) and paste:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.ps1 | iex"
```

Or download the repo (**Code → Download ZIP**), unzip it, right-click `install.ps1` → **Run with PowerShell**.

The installer puts everything in `%USERPROFILE%\VanishCam`, installs **OBS Studio** with `winget` if you don't have it (it may ask for administrator permission) and creates a **VanishCam** shortcut on the Desktop.

### macOS

Open **Terminal** and paste:

```bash
curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
```

If you have [Homebrew](https://brew.sh), the installer installs OBS Studio; otherwise it opens the download page. Then you need to **enable OBS's virtual camera once**:

1. Open OBS Studio.
2. Click **Start Virtual Camera** and accept the permission macOS asks for (System Settings → General → Login Items & Extensions → Camera Extensions).
3. Click **Stop Virtual Camera** and quit OBS.

The first time you open VanishCam, macOS asks for permission for Terminal to use the camera: allow it.

### Updating

On Ubuntu and macOS, run `./update.sh` in the app folder (`~/VanishCam/update.sh`). It downloads the latest code,
updates the Python dependencies and checks the models, keeping your `.venv`, `models/` and the virtual camera setup.
To install a specific version, use `VANISHCAM_REF=v1.0.0 ./update.sh`.

If your install predates `update.sh`, re-run the installer once (it also installs it):

```bash
curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
```

On Windows, run `install.ps1` again.

## Usage

| System | How to open it |
|---|---|
| Ubuntu | Applications menu → **VanishCam**, or `~/VanishCam/vanishcam.sh` |
| Windows | **VanishCam** on the Desktop, or `vanishcam.bat` |
| macOS | **VanishCam.command** on the Desktop, or `~/VanishCam/vanishcam.sh` |

1. A window with your camera opens. **Step out of the frame**: after 4 seconds it takes a photo of the empty background (the terminal tells you).
2. Step back in and make the gesture, **holding it**: you vanish.
3. To come back, **lower your hand and repeat the gesture**.

| Mode | Gesture | Hold |
|---|---|---|
| **Dragon Ball** (default) | Index and middle fingers together, straight, resting on your forehead | 1 s |
| **Normal** (`--mode normal`) | V with index and middle fingers | 0.3 s |
| **Naruto** (`--mode naruto`) | Palms together in front of the camera | 0.3 s |

Keys (with the VanishCam window focused): `V` vanish, `R` reappear (or restart the setup while calibrating), `SPACE` retake the background photo, `P` pause/resume, `F` fullscreen, `Q` quit. A side panel next to the video shows the next step, the keys and the recent events (use `--no-hud` to hide it); while the background is being captured it also outlines the person so you know whether the camera sees you.

**Several cameras?** When you start VanishCam and it finds more than one, it shows a window with a live preview: use `A`/`D` or the arrow keys to change camera, `Enter` to start and `Q` to cancel. You can also list them with `./vanishcam.sh --list-cameras` and force one with `./vanishcam.sh --camera 4` (or `--camera /dev/video4`).

**In Zoom or Meet**, open VanishCam first and then pick the camera in the video settings:

- Ubuntu: **VanishCam**.
- Windows and macOS: **OBS Virtual Camera**. If OBS is open, don't start its virtual camera: VanishCam uses it.

If it doesn't show up, quit Zoom completely (or reload Meet) and open it again.

The full guide (options, effects, troubleshooting) is in [GUIDE.md](GUIDE.md); almost all of it applies to Windows and macOS too.

## Effect sounds in the call

Effect sounds play through **your speakers**: the virtual camera carries video only. Others hear them only if your microphone picks them up, and Zoom/Meet noise suppression often removes them.

- **Ubuntu:** start with `./vanishcam.sh --call-audio`. It creates a virtual microphone **VanishCam-Mic** that mixes your real microphone with the effects (and you still hear them yourself). In Zoom/Meet pick that microphone and lower noise suppression (Zoom: Settings → Audio → Suppress background noise: Low, or enable "Original sound for musicians"). It is torn down automatically when VanishCam closes.
- **Windows:** install [VB-Cable](https://vb-audio.com/Cable/) and start VanishCam with `--audio-device "CABLE Input (VB-Audio Virtual Cable)"` (the name must match). In Windows' sound settings open the CABLE Input properties, **Listen** tab and enable "Listen to this device" with your real speakers as the target, so you still hear the effects. In Zoom/Meet pick **CABLE Output** as the microphone and lower noise suppression.
- **macOS:** install [BlackHole](https://github.com/ExistentialAudio/BlackHole) and start VanishCam with `--audio-device "BlackHole 2ch"`. To keep hearing the effects, create an Aggregate Device or a Multi-Output Device in *Audio MIDI Setup* that includes your speakers and BlackHole. In Zoom/Meet pick **BlackHole 2ch** as the microphone and lower noise suppression.

To list the exact device names, run this in the app folder (`.venv/bin/python` on Ubuntu/macOS, `.venv\Scripts\python.exe` on Windows):

```bash
.venv/bin/python -c "import pygame; pygame.init(); from pygame._sdl2 import audio; print(audio.get_audio_device_names(False))"
```

`--audio-device` only works when pygame plays the sounds; the `ffplay` fallback ignores it.

## Security and privacy

- Video is processed only on your computer; VanishCam doesn't save images or open network connections, except for the first download of the Google MediaPipe models, which is verified with SHA-256.
- On Linux, if the virtual camera has to be built, the installer verifies the exact source commit before building it.
- The one-line installers (`curl | bash`, `irm | iex`) run whatever is on this repo's `main` branch by default: if you prefer, clone the repo, review the scripts and run them by hand. Both accept `VANISHCAM_REF` (a tag or commit, e.g. `VANISHCAM_REF=v1.0.0`) to install an exact version and use a pinned uv installer whose SHA-256 is verified before running it.
- Dependencies install from `requirements.lock.txt`, pinned with hashes (`--require-hashes`).

Security problems: please report them privately as described in [SECURITY.md](SECURITY.md).

## Development

Context for agents and developers in [AGENTS.md](AGENTS.md). Tests:

```bash
.venv/bin/python -m unittest discover -p 'test_*.py'
```

After editing `requirements.txt`, regenerate the hashed lock the installers use:
`uv pip compile requirements.txt --universal --generate-hashes -o requirements.lock.txt`.

Packaging is experimental: `BUILD_WINDOWS.bat` and `BUILD_MACOS.sh` build a standalone app, and neither has been run
on real hardware yet.

## Contributing

Contributions are welcome: bug reports, ideas and pull requests. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
setup, the rules (no text drawn on the video, English only, no copyrighted anime assets...) and the pull request
process, and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Contributions are accepted under the MIT license.

## License

This fork's own code and docs are released under the [MIT license](LICENSE). The upstream project has no license, so
the code and assets inherited from it remain the copyright of their author and are not covered by the MIT license;
the MediaPipe models are Google's (Apache-2.0), and pyvirtualcam, a runtime dependency, is GPL-2.0. Details, file by
file, in [NOTICE.md](NOTICE.md).
