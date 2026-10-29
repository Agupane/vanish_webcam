"""Preload an effect sound and play it without blocking video frames."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


SOUND_PATH = Path(__file__).resolve().parent / "assets" / "vanish.MP3"


class VanishSound:
    def __init__(self, path: Path = SOUND_PATH):
        if not path.is_file():
            raise RuntimeError(f"Audio file not found: {path}")
        self.path = path

        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        self.process = None
        self.ffplay = None
        try:
            from pygame import mixer
        except ImportError:
            self.ffplay = shutil.which("ffplay")
            if self.ffplay is None:
                raise RuntimeError("Install pygame or ffplay to play audio.")
            return

        self.mixer = mixer
        self.owns_mixer = mixer.get_init() is None
        try:
            if self.owns_mixer:
                mixer.init(frequency=44100, size=-16, channels=2, buffer=256)
            self.sound = mixer.Sound(str(path))  # Decode once, before opening the webcam.
        except Exception as error:
            if self.owns_mixer:
                mixer.quit()
            raise RuntimeError(f"Could not open the audio: {error}") from error

    def play(self, loops: int = 0, fade_ms: int = 0) -> None:
        """Play from the start; loops=-1 repeats until stop()."""
        if self.ffplay is not None:
            self._stop_process()
            command = [self.ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet"]
            if loops:
                command += ["-loop", "0" if loops < 0 else str(loops + 1)]
            try:
                self.process = subprocess.Popen(
                    command + ["-i", str(self.path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as error:
                raise RuntimeError(f"Could not play the audio: {error}") from error
            return
        self.sound.stop()
        if self.sound.play(loops=loops, fade_ms=fade_ms) is None:
            raise RuntimeError("Could not play the audio: no free channels.")

    def stop(self, fade_ms: int = 0) -> None:
        if self.ffplay is not None:
            self._stop_process()
            return
        if fade_ms > 0:
            self.sound.fadeout(fade_ms)
        else:
            self.sound.stop()

    def set_volume(self, volume: float) -> None:
        # ffplay has no live volume control; only the pygame path honours it.
        if self.ffplay is None:
            self.sound.set_volume(max(0.0, min(1.0, volume)))

    def _stop_process(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def close(self) -> None:
        if self.ffplay is not None:
            self._stop_process()
            return
        if self.owns_mixer:
            self.mixer.quit()
            self.owns_mixer = False
