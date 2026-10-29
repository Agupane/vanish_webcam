# VanishCam

[![tests](https://github.com/Agupane/vanish_webcam/actions/workflows/tests.yml/badge.svg)](https://github.com/Agupane/vanish_webcam/actions/workflows/tests.yml)

Disappearance effects for your webcam in Zoom, Google Meet or any video call app. Make a gesture and you vanish from the picture; repeat the gesture and you're back.

The default mode is **Dragon Ball**: rest your index and middle fingers together on your forehead for 1 second (Instant Transmission) and you're gone with comic speed lines and a flash. There is also **Normal** mode (two-finger V, you dissolve) and **Naruto** mode (palms together, smoke and a log).

Everything is processed on your computer: the video is not recorded or sent to any server.

## About this fork

This is a fork of [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) by Nicola Auriemma, who
created VanishCam with its Normal and Naruto modes; all credit for the original idea and app goes to them (original
README in [README_ORIGINAL.md](README_ORIGINAL.md)). This fork adds and changes:

- **Dragon Ball mode** as the default (Instant Transmission), with a **Super Saiyan** transformation: a procedural yellow aura that surrounds your silhouette.
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
- **`/dev/video10` exists but `/dev/video10 is not a video output device`.** A stale `v4l2loopback` 0.12.7 from the HWE stack can be loaded without the `Video Output` capability. Reload it: `sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback`; if it comes back stale, run the installer again so it builds 0.13.2.
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

Opened from the shortcut or the menu (no options), VanishCam starts with a **home window** where you do all the
setup with the mouse: the effect (Dragon Ball, Normal, Naruto), the camera (only when there are several; virtual
cameras such as OBS Virtual Camera are hidden) and the Super Saiyan golden hair. It remembers your last effect and
camera. Press **START** (or `Enter`).

1. A window with your camera opens. **Step out of the frame**: after 4 seconds it takes a photo of the empty background (the terminal tells you).
2. Step back in and make the gesture, **holding it**: you vanish.
3. To come back, **lower your hand and repeat the gesture**.

| Mode | Gesture | Hold |
|---|---|---|
| **Dragon Ball** (default) | Index and middle fingers together, straight, resting on your forehead | 1 s |
| **Normal** (`--mode normal`) | V with index and middle fingers | 0.3 s |
| **Naruto** (`--mode naruto`) | Palms together in front of the camera | 0.3 s |

### Super Saiyan (Dragon Ball mode)

Hold **both clenched fists in front of your face, one on each side of the nose**, for 1.5 seconds. A golden aura with
rising flames and sparks surrounds your silhouette, the room gets darker and the edge of your body catches the light;
your eyes turn teal, your eyebrows golden and, if you added it, your hair turns into golden spiky Super Saiyan hair
(it flickers in during the charge, like in the series). The image shakes and a hum plays. Repeat the pose or press `S`
to power down. Teleporting while transformed keeps the transformation.

**Golden hair (optional, once):** VanishCam does not draw the hair itself: you make it from your own photos with an
image tool you choose, and VanishCam never uploads anything.

1. In the home window (Dragon Ball selected), click **Take photos**. It takes three photos (front and a little
   turned to each side; `SPACE` take, `S` skip, `Q` quit) and saves them in the `ssj_hair` folder of the app.
   From a terminal: `./vanishcam.sh --ssj-hair-photos` (Windows: `vanishcam.bat --ssj-hair-photos`).
2. Click **Copy prompt**, open ChatGPT or Gemini (the free versions work), attach a photo and paste the prompt (it is
   also in `ssj_hair/prompt.txt`).
3. Click **Open folder** and save the result there as `ssj_front.png` (and `ssj_left.png`, `ssj_right.png` for the
   other photos, so the hair follows your head when you turn it). Click **Check pictures**: it says whether each
   picture works. Then **START**: the hair is imported automatically.

The picture must show the whole face and clearly golden hair on a plain background; if not, the terminal says why.
Your photos stay in `ssj_hair` until you delete them; uploading them to an image tool is your choice and follows that
tool's terms.

**Turn off background blur and virtual backgrounds in Zoom, Google Meet or Teams** while you use VanishCam. Those
features blur or replace everything that is not you, and the aura lives exactly there: with them on it turns into a
blurry smudge. If a chair or other furniture is right behind you, take the background photo with it in place: the aura
uses that photo to tell you apart from the chair.

Keys (with the VanishCam window focused): `V` vanish, `R` reappear (or restart the setup while calibrating), `S` Super
Saiyan on/off, `SPACE` retake the background photo, `P` pause/resume, `F` fullscreen, `Q` quit. A side panel next to
the video shows the next step, the keys and the recent events (use `--no-hud` to hide it); while the background is
being captured it also outlines the person so you know whether the camera sees you.

**Several cameras?** Click **Change** next to the camera in the home window (or start VanishCam without the home window and without `--camera`): a window with a live preview opens; use `A`/`D` or the arrow keys to change camera, `Enter` to pick it and `Q` to cancel. The cameras are listed by name on Ubuntu and Windows; virtual cameras (OBS Virtual Camera, the VanishCam device, Meta Quest headsets) are hidden so VanishCam never reads its own output. You can also list them with `--list-cameras` and force one with `--camera 4` (on Ubuntu also `--camera /dev/video4`).

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

- Video is processed only on your computer; VanishCam doesn't save images or open network connections, except for the first download of the Google MediaPipe models, which is verified with SHA-256. The only images it writes are the photos you take on purpose with `--ssj-hair-photos` (in `ssj_hair/`) and the hair cut-outs it makes from your Super Saiyan pictures (`ssj_hair/.cache/`).
- On Linux, if the virtual camera has to be built, the installer verifies the exact source commit before building it.
- The one-line installers (`curl | bash`, `irm | iex`) run whatever is on this repo's `main` branch by default: if you prefer, clone the repo, review the scripts and run them by hand. Both accept `VANISHCAM_REF` (a tag or commit, e.g. `VANISHCAM_REF=v1.0.0`) to install an exact version and use a pinned uv installer whose SHA-256 is verified before running it.
- Dependencies install from `requirements.lock.txt`, pinned with hashes (`--require-hashes`).

Security problems: please report them privately as described in [SECURITY.md](SECURITY.md).

## Development

Context for agents and developers in [AGENTS.md](AGENTS.md); the algorithm map, measured costs and optimization
backlog are in [ALGORITHMS.md](ALGORITHMS.md). Tests:

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
the code and assets inherited from it remain the copyright of their author and are not covered by the MIT license.
`assets/teleport.mp3` and `assets/ssj_transform.mp3` are owner-supplied third-party material and are not MIT either.
The MediaPipe models are Google's (Apache-2.0), and pyvirtualcam, a runtime dependency, is GPL-2.0. Details, file by
file, in [NOTICE.md](NOTICE.md).
