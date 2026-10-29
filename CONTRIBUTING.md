# Contributing to VanishCam

Thanks for helping! Bug reports, ideas and pull requests are welcome. By taking part you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## License of contributions

This fork is MIT licensed ([LICENSE](LICENSE)); upstream code it inherited is not (see [NOTICE.md](NOTICE.md)). By
submitting a pull request you agree that your contribution is licensed under the MIT license. Only submit work you
wrote or that comes from a source whose license allows it under MIT; never copy code or assets from sources without a
license (including the upstream repository's unlicensed parts into new files), and never add copyrighted anime audio,
frames or artwork.

## Development setup

You need Python 3.12 (the version CI uses) and a webcam for manual testing; the tests don't need one.

```bash
git clone https://github.com/Agupane/vanish_webcam.git
cd vanish_webcam
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip install -r requirements.txt
```

The installers and CI use `requirements.lock.txt` (pinned, with hashes). If you change `requirements.txt`, regenerate it
with `uv pip compile requirements.txt --universal --generate-hashes -o requirements.lock.txt`.

On Linux you can also run `./install-ubuntu.sh`, which sets up the virtual camera too. On a headless Linux box,
MediaPipe needs `libegl1` and `libgles2` (`sudo apt install libegl1 libgles2`).

Run the app with `.venv/bin/python vanish_cam.py` (`--help` lists the options). [AGENTS.md](AGENTS.md) explains the
layout, the main loop and the state machines; [ALGORITHMS.md](ALGORITHMS.md) maps the algorithms, their costs and the
optimization backlog.

## Tests

```bash
SDL_AUDIODRIVER=dummy .venv/bin/python -m unittest discover -p 'test_*.py'
.venv/bin/python vanish_cam.py --self-test    # downloads and verifies the models, loads every mode
```

CI ([.github/workflows/tests.yml](.github/workflows/tests.yml)) runs both on Ubuntu, Windows, macOS arm64 and macOS
Intel, plus a syntax check of the installer scripts. If you change an installer, run `bash -n` on it (or parse
`install.ps1` with PowerShell) and, if you can, try it on the platform it targets.

## Rules

These come from [AGENTS.md](AGENTS.md); pull requests that break them will be asked to change.

- **No text or UI drawn on the video**, neither in the preview nor in the virtual camera. Messages go to the terminal.
  The tests patch `cv2.putText` to fail.
- **English only**: terminal messages, docs, code comments, docstrings and tests.
- **No copyrighted anime assets.** Sounds are synthesized in code; users may drop their own files in `assets/`
  (`teleport.*`, `ssj_*.MP3`). The committed owner-supplied exceptions are `assets/teleport.mp3` (from
  `bernardocm10/vanish_webcam`) and `assets/ssj_transform.mp3`; both are not covered by the MIT license (see NOTICE.md).
  Do not add the golden-hair or GIF aura back without solving the "surround, don't paint, the person" rule.
- **MediaPipe timestamps:** VIDEO-mode tasks need strictly increasing timestamps, so run each task at most once per frame.
- **Keep the loop testable** through the patchable seams listed in AGENTS.md (`gesture_active`, `person_mask`,
  `open_camera`, `open_virtual_camera`, `VanishSound`, ...), and add tests for new behavior.
- **New model?** Add its URL to `MODEL_URLS` and its SHA-256 to `MODEL_SHA256` in `vanish_cam.py`, and list it in
  [NOTICE.md](NOTICE.md).
- **Privacy:** never write frames to disk or open network connections other than the model downloads.
- New dependencies, assets or files with a different license must be added to [NOTICE.md](NOTICE.md).

Style: follow the surrounding code. Python uses 4 spaces; shell and YAML use 2; `.bat`/`.ps1` files are CRLF (see
[.editorconfig](.editorconfig) and `.gitattributes`).

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Keep each pull request focused on one change; update `README.md`, `GUIDE.md`, `AGENTS.md` (and
   [ALGORITHMS.md](ALGORITHMS.md) for hot-path changes) and [CHANGELOG.md](CHANGELOG.md) (under *Unreleased*) when
   behavior changes.
3. Run the tests and fill in the pull request template: what changed, which tests you ran and on which platforms you
   checked it.
4. CI must pass. A maintainer reviews and merges.

For larger changes (new modes, new platforms, new dependencies) open an issue first to agree on the approach.
