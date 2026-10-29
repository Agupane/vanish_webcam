# VanishCam guide

Fork of [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) adapted to Ubuntu 22.04 and 24.04.
The video goes out through a virtual camera (`v4l2loopback`) that you can pick in Zoom, Google Meet or any other app.
Installation for every system is in [README.md](README.md); this guide covers Ubuntu, and almost all of it applies to Windows and macOS too.

## Installation

```bash
git clone https://github.com/Agupane/vanish_webcam.git
cd vanish_webcam
./install-ubuntu.sh
```

The script installs the following:

- **System packages:** `v4l2loopback-dkms`, `v4l-utils`, `ffmpeg` and the graphics libraries.
- **Virtual camera:** creates it as `VanishCam` (`/dev/video10`) and configures it to come back after every reboot.
- **Python environment:** creates `.venv` and installs the dependencies.
- **MediaPipe models:** downloads them once (about 10 MB).
- **Applications menu:** adds a launcher called **VanishCam**.

**Secure Boot:** if `apt` asks for a password to sign the module, pick one and reboot. On startup a blue screen (MOK) appears: choose *Enroll MOK* and type that password. Then run `./install-ubuntu.sh` again.

**Updating:** run `./update.sh` in the app folder. It updates the code, the Python dependencies and the models, keeping `.venv`, `models/` and the virtual camera setup.

## Usage

```bash
./vanishcam.sh                   # Dragon Ball mode (default)
./vanishcam.sh --mode normal     # V with index and middle fingers: dissolve
./vanishcam.sh --mode naruto     # palms together: smoke and log
./vanishcam.sh --menu            # choose the mode in a window
```

1. If there is more than one webcam, a window with a live preview lets you choose one (`A`/`D` or arrows, `Enter` to start, `Q` to cancel). Then the preview window (**VanishCam - Preview**) opens. **Step out of the frame**: after 4 seconds it takes a photo of the empty background. If it still sees you in the frame, it tells you in the terminal and waits 2 more seconds.
2. Step back in and make the mode's gesture, **holding it**. You vanish with the effect.
3. While you're gone, the call sees the background photo. To come back, **lower your hand and repeat the same gesture**: you reappear with the effect in reverse.

| Mode | Gesture | How long to hold it | Effect |
|---|---|---|---|
| **Dragon Ball** | Index and middle fingers together and straight, resting on your forehead (Instant Transmission) | 1 second | Vertical comic lines over your silhouette, a flash and you're gone (almost 1 second) |
| **Normal** | V with index and middle fingers | a moment (0.3 s) | You dissolve from the bottom up (3.6 s); coming back, you build up from the top down |
| **Naruto** | Palms together in front of the camera | a moment (0.3 s) | A cloud of smoke and a falling log (1.5 s); coming back, the log goes away in a cloud of smoke |

A stray single-frame gesture no longer makes you vanish, and after each effect you have to lower your hand before the gesture counts again.

### Super Saiyan (Dragon Ball mode)

1. Make fists and hold them **at chest or belly height, one on each side of your body**, as if charging ki. Both fists and your face must be visible.
2. Hold the pose for **1.5 seconds**: the image shakes, a small aura appears and the charge sound plays. If you let go early, it's cancelled.
3. A white flash and you're **Super Saiyan**: golden hair and a yellow aura with rising flames and sparks, with a background hum.
4. To go back to normal, repeat the pose for 1.5 seconds or press `S`.

- **Teleport:** if you teleport while transformed, you come back transformed.
- **Golden hair:** uses an extra Google model downloaded the first time (16 MB). Without it, or if you're bald or wearing a cap, you only get the aura.
- **Your own sounds:** put `assets/ssj_charge.MP3`, `assets/ssj_transform.MP3` or `assets/ssj_aura.MP3` and those are used instead of the generated ones.
- **The sound plays through your speakers:** it doesn't travel through the virtual camera. Others in the call only hear it if your microphone picks it up (on Ubuntu, `--call-audio` fixes that; on Windows and macOS send it to a virtual cable with `--audio-device`; see [README.md](README.md)).

| Key (with the preview window focused) | Action |
|---|---|
| `V` | vanish manually |
| `R` | reappear manually |
| `S` | Super Saiyan on / off (Dragon Ball mode) |
| `SPACE` | retake the background photo |
| `F` | fullscreen |
| `Q` / `ESC` | quit |

In the preview you see yourself mirrored, like in a mirror. Zoom and Meet get the image the right way round, so any text behind you reads correctly. If you'd rather send it mirrored, use `--mirror-output`.

### Zoom

Settings → Video → Camera → **VanishCam**. If it doesn't show up, quit Zoom completely and open it after starting `vanishcam.sh`.

### Google Meet (Chrome or Firefox)

Start `vanishcam.sh` first and then open Meet. In Settings → Video pick **VanishCam**.
Chrome only lists the camera once it's receiving video, so the app has to be started before Meet.

## Useful options

```bash
./vanishcam.sh --camera /dev/video2          # another webcam (list them with v4l2-ctl --list-devices)
./vanishcam.sh --list-cameras                # show the real webcams and their names
./vanishcam.sh --width 640 --height 360      # less load on older PCs
./vanishcam.sh --no-mirror                   # no mirroring, not even in the preview
./vanishcam.sh --mirror-output               # send the mirrored image to Zoom/Meet
./vanishcam.sh --gesture-debug               # print the detected gesture in the terminal
./vanishcam.sh --call-audio                  # virtual microphone with your voice + the effects
./vanishcam.sh --audio-device "BlackHole 2ch" # play the effects into a virtual cable (Windows/macOS)
```

If you don't pass `--camera`, the first real webcam is used and the virtual camera is ignored.

## Troubleshooting

- **"Virtual camera not available":** run `sudo modprobe v4l2loopback`. If that fails, check the Secure Boot note.
- **The webcam is busy:** close any other app using it (Zoom, Meet, Cheese) before starting VanishCam. In Zoom or Meet, *VanishCam* must be selected, not your webcam.
- **The preview is black or the wrong camera opens:** run `./vanishcam.sh --list-cameras`, then pick the USB camera with `--camera 4` (or its `/dev/videoN` path). Without `--camera`, VanishCam shows a window with a live preview: `A`/`D` or arrows change camera, `Enter` starts, `Q` cancels.
- **It erases you badly or leaves smudges:** use a static, well-lit background. If the camera moved, press `SPACE`.
- **The Dragon Ball gesture doesn't register:** your face must be visible (even if the hand covers part of the forehead), with the index and middle fingers together and the ring and pinky fingers folded. With `--gesture-debug` the terminal shows whether it sees the hand, the face and the pose.
- **It's slow:** it runs on the CPU only. Lower the resolution with `--width 640 --height 360`.
- **To uninstall (Ubuntu):** run `./uninstall-ubuntu.sh`. It removes the virtual camera configuration, the DKMS module built by the installer and the Applications menu entry, but keeps the app folder.

## Differences from the original

- **Dragon Ball mode (new, default):** the original README described it as *Goku*, but it wasn't in the code. It's implemented here; `--mode goku` also works. The teleport sound is generated on the fly; if you add your own `assets/teleport.MP3`, that one is used.
- **Held gestures:** previously a single frame with the gesture was enough, which made you vanish by accident.
- **Reappear with the gesture and with an effect:** previously it was only possible with `R`, without an effect.
- **Better background photo:** collects 1.5 seconds of frames instead of half a second, and waits if someone is still there.
- **Unmirrored image in the call:** only the preview is mirrored.
- **English messages** in the terminal, and the preview window is called **VanishCam - Preview** (upstream: *Webcam - Anteprima*).
- **Real webcam:** on Linux it's detected automatically, opened with V4L2 in MJPG and not confused with the virtual camera. `--camera` also accepts paths like `/dev/video2`.
- **New scripts:** `install-ubuntu.sh` and `vanishcam.sh` replace the Windows `.bat` files.
- **Tests:** run from the repo root with `python -m unittest`.
- **Still missing:** the original README's *Particles* mode.
- **Sound:** effect sounds play through your speakers and don't enter the call, unless you use `--call-audio` on Ubuntu.
