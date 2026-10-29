# VanishCam

Disappearance effects for your webcam in Zoom, Google Meet or any video call app. Make a gesture and you vanish from the picture; repeat the gesture and you're back.

The default mode is **Dragon Ball**: rest your index and middle fingers together on your forehead for 1 second (Instant Transmission) and you're gone with comic speed lines and a flash. There is also **Normal** mode (two-finger V, you dissolve) and **Naruto** mode (palms together, smoke and a log).

Everything is processed on your computer: the video is not recorded or sent to any server. This is a fork of [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) (original README in [README_ORIGINAL.md](README_ORIGINAL.md)).

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

**Secure Boot:** if `apt` asks for a password to sign the module, pick one and reboot. On startup a blue screen (MOK) appears: choose *Enroll MOK* → *Continue*, type that password and reboot. Then run the installer again.

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

Keys (with the VanishCam window focused): `V` vanish, `R` reappear, `SPACE` retake the background photo, `F` fullscreen, `Q` quit.

**In Zoom or Meet**, open VanishCam first and then pick the camera in the video settings:

- Ubuntu: **VanishCam**.
- Windows and macOS: **OBS Virtual Camera**. If OBS is open, don't start its virtual camera: VanishCam uses it.

If it doesn't show up, quit Zoom completely (or reload Meet) and open it again.

The full guide (options, effects, troubleshooting) is in [GUIDE.md](GUIDE.md); almost all of it applies to Windows and macOS too.

## Effect sounds in the call

Effect sounds play through **your speakers**: the virtual camera carries video only. Others hear them only if your microphone picks them up, and Zoom/Meet noise suppression often removes them.

- **Ubuntu:** start with `./vanishcam.sh --call-audio`. It creates a virtual microphone **VanishCam-Mic** that mixes your real microphone with the effects (and you still hear them yourself). In Zoom/Meet pick that microphone and lower noise suppression (Zoom: Settings → Audio → Suppress background noise: Low, or enable "Original sound for musicians"). It is torn down automatically when VanishCam closes.
- **Windows and macOS:** not automated yet. It needs a virtual audio cable ([VB-Cable](https://vb-audio.com/Cable/) on Windows, [BlackHole](https://github.com/ExistentialAudio/BlackHole) on macOS) with VanishCam playing the effects into it; it's on the to-do list.

## Security and privacy

- Video is processed only on your computer; VanishCam doesn't save images or open network connections, except for the first download of the Google MediaPipe models, which is verified with SHA-256.
- On Linux, if the virtual camera has to be built, the installer verifies the exact source commit before building it.
- The one-line installers (`curl | bash`, `irm | iex`) run whatever is on this repo's `main` branch: if you prefer, clone the repo, review the scripts and run them by hand.

## Development

Context for agents and developers in [AGENTS.md](AGENTS.md). Tests:

```bash
.venv/bin/python -m unittest discover -p 'test_*.py'
```
