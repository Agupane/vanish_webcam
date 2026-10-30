"""Render the Super Saiyan aura on a synthetic scene, for tuning without a camera.

The scene is drawn here (a wall, a high-back chair and a person with dark hair); no camera frame is read or written.
Rows: light wall, dark wall. Columns: two moments, then a close webcam that sees the shoulders above the chin (the
body must never be cut: no aura painted on it).

    .venv/bin/python tools/aura_preview.py aura.png          # write the grid
    .venv/bin/python tools/aura_preview.py --show            # open a window instead
    .venv/bin/python tools/aura_preview.py --style contour contour.png   # flames mapped along the outline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import super_saiyan_effect as ssj  # noqa: E402

LIGHT_WALL, DARK_WALL = (205, 208, 212), (60, 55, 50)


def scene(wall, shoulders: int = 340, height: int = 540, width: int = 960):
    """Live frame, segmenter-like mask (person + chair) and the head ellipse. `shoulders` is the shoulder top row."""
    chair = np.zeros((height, width), np.uint8)
    cv2.ellipse(chair, (430, 330), (150, 210), 0, 0, 360, 1, -1)
    background = np.full((height, width, 3), wall, np.uint8)
    background[chair > 0] = (40, 38, 40)
    person = np.zeros((height, width), np.uint8)
    cv2.ellipse(person, (430, 240), (75, 95), 0, 0, 360, 1, -1)
    cv2.rectangle(person, (400, 320), (460, 360), 1, -1)
    cv2.ellipse(person, (430, shoulders + 220), (230, 220), 0, 180, 360, 1, -1)
    cv2.rectangle(person, (200, shoulders + 60), (660, 540), 1, -1)
    frame = background.copy()
    frame[person > 0] = (200, 170, 80)  # Blue shirt.
    cv2.ellipse(frame, (430, 250), (62, 80), 0, 0, 360, (120, 150, 200), -1)  # Face.
    cv2.ellipse(frame, (430, 200), (75, 50), 0, 180, 360, (30, 30, 32), -1)  # Dark hair.
    mask = cv2.GaussianBlur(np.maximum(person, chair).astype(np.float32), (0, 0), 3)
    head = ((430, 225), (80, 100), 0.0)
    return frame, mask, head


def grid(times=(0.0, 0.37), style: str = "classic") -> np.ndarray:
    rows = []
    for wall in (LIGHT_WALL, DARK_WALL):
        frame, mask, head = scene(wall)
        aura = ssj.AuraRenderer(style=style)
        levels = ssj.PowerLevels(aura=1.0)
        cells = [ssj.render_super_saiyan(frame, mask, levels, t, aura, head) for t in times]
        close_frame, close_mask, _ = scene(wall, shoulders=280)
        cells.append(ssj.render_super_saiyan(close_frame, close_mask, levels, times[0],
                                             ssj.AuraRenderer(style=style), head))
        rows.append(np.hstack(cells))
    return np.vstack(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", nargs="?", help="PNG to write")
    parser.add_argument("--show", action="store_true", help="open a window instead of writing a file")
    parser.add_argument("--scale", type=float, default=0.6, help="output scale (default: 0.6)")
    parser.add_argument("--style", choices=ssj.AURA_STYLES, default="classic", help="aura style (default: classic)")
    args = parser.parse_args()
    image = cv2.resize(grid(style=args.style), None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_AREA)
    if args.show or not args.output:
        cv2.imshow("Aura preview", image)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    else:
        cv2.imwrite(args.output, image)
        print(f"Written {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
