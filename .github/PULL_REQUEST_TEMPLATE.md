## Summary

<!-- What does this change and why? Link the issue if there is one. -->

## Tests run

<!-- e.g. `python -m unittest discover -p 'test_*.py'`, `python vanish_cam.py --self-test`, manual run with a webcam -->

## Platforms checked

- [ ] Ubuntu / Linux
- [ ] Windows
- [ ] macOS (Apple silicon)
- [ ] macOS (Intel)
- [ ] Only CI

## Checklist

- [ ] No text or UI is drawn on the video (preview or virtual camera); messages go to the terminal.
- [ ] Everything is in English (messages, docs, comments, tests).
- [ ] No copyrighted anime audio, frames or artwork, and no code or assets copied from unlicensed sources.
- [ ] MediaPipe VIDEO-mode tasks still run at most once per frame (strictly increasing timestamps).
- [ ] New behavior is covered by tests through the patchable seams.
- [ ] New models have their SHA-256 in `MODEL_SHA256`; new models, assets or dependencies are listed in `NOTICE.md`.
- [ ] Docs (`README.md`, `GUIDE.md`, `AGENTS.md`) and `CHANGELOG.md` are updated if behavior changed.
- [ ] I agree that this contribution is licensed under the MIT license.
