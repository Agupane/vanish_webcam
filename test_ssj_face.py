import argparse
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

import ssj_face
import super_saiyan_effect as ssj
import vanish_cam as app

SKIN = (120, 150, 200)
GOLD = (40, 200, 255)


def synthetic_face(cx=320.0, cy=260.0, width=160.0, angle=0.0, scale=1.0):
    """478 face points around (cx, cy); only the indices VanishCam uses are placed precisely."""
    w = width * scale
    angles = np.linspace(0, 2 * np.pi, 478, endpoint=False)
    points = np.stack([cx + 0.45 * w * np.cos(angles), cy + 0.6 * w * np.sin(angles)], axis=1)

    def put(index, x, y):
        points[index] = (cx + x * w, cy + y * w)

    put(ssj_face.FACE_LEFT, -0.5, 0.0)
    put(ssj_face.FACE_RIGHT, 0.5, 0.0)
    put(ssj_face.FOREHEAD_TOP, 0.0, -0.75)
    put(ssj_face.CHIN, 0.0, 0.65)
    put(ssj_face.NOSE, 0.0, 0.05)
    lower = ssj_face.LOWER_FACE
    for index, theta in zip(lower, np.linspace(np.pi, 0.0, len(lower))):
        put(index, 0.5 * np.cos(theta), 0.65 * np.sin(theta))
    for side, (center, ring), opening, brow in zip((-1, 1), ssj_face.IRISES, ssj_face.EYE_OPENINGS, ssj_face.BROWS):
        ex, ey = 0.2 * side, -0.15
        for index, theta in zip(opening, np.linspace(0, 2 * np.pi, len(opening), endpoint=False)):
            put(index, ex + 0.11 * np.cos(theta), ey + 0.045 * np.sin(theta))
        put(center, ex, ey)
        for index, theta in zip(ring, (0, np.pi / 2, np.pi, 3 * np.pi / 2)):
            put(index, ex + 0.045 * np.cos(theta), ey + 0.045 * np.sin(theta))
        xs = np.linspace(0.32, 0.08, 5) * side
        for index, x in zip(brow[:5], xs):
            put(index, x, -0.3)
        for index, x in zip(brow[5:], xs[::-1]):
            put(index, x, -0.26)
    if angle:
        matrix = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        points = points @ matrix[:, :2].T + matrix[:, 2]
    return points.astype(np.float32)


def face_picture(face, hair=True, height=520, width=640):
    """A generated-looking Super Saiyan picture: gray background, skin, eyes, brows and golden spiky hair."""
    image = np.full((height, width, 3), 128, np.uint8)
    cx, cy = face[ssj_face.NOSE]
    w = float(np.linalg.norm(face[ssj_face.FACE_RIGHT] - face[ssj_face.FACE_LEFT]))
    if hair:
        spikes = [(cx - 0.75 * w, cy - 0.2 * w)]
        for i, x in enumerate(np.linspace(-0.7, 0.7, 9)):
            spikes.append((cx + x * w, cy - (1.45 if i % 2 == 0 else 0.95) * w))
        spikes.append((cx + 0.75 * w, cy - 0.2 * w))
        cv2.fillPoly(image, [np.round(np.array(spikes)).astype(np.int32)], GOLD)
        cv2.line(image, (int(cx - 0.2 * w), int(cy - 0.9 * w)), (int(cx), int(cy - 0.6 * w)), (230, 250, 255), 3)
    cv2.ellipse(image, (int(cx), int(cy)), (int(0.48 * w), int(0.62 * w)), 0, 0, 360, SKIN, -1)
    for (center, ring), brow in zip(ssj_face.IRISES, ssj_face.BROWS):
        cv2.circle(image, tuple(np.round(face[center]).astype(int)), int(0.05 * w), (40, 60, 90), -1)
        cv2.polylines(image, [np.round(face[list(brow[:5])]).astype(np.int32)], False, (30, 30, 30), 4)
    return image


class EyesAndBrowsTests(unittest.TestCase):
    def setUp(self):
        self.face = synthetic_face()
        self.frame = np.full((520, 640, 3), SKIN, np.uint8)
        for (center, _), opening in zip(ssj_face.IRISES, ssj_face.EYE_OPENINGS):
            cv2.fillPoly(self.frame, [np.round(self.face[list(opening)]).astype(np.int32)], (235, 235, 235))
            cv2.circle(self.frame, tuple(np.round(self.face[center]).astype(int)), 7, (40, 60, 90), -1)
        for brow in ssj_face.BROWS:
            cv2.polylines(self.frame, [np.round(self.face[list(brow[:5])]).astype(np.int32)], False,
                          (30, 30, 30), 4)

    def test_irises_turn_teal_and_the_rest_stays(self):
        output = ssj_face.tint_eyes(self.frame, self.face, 1.0).astype(int)
        cx, cy = np.round(self.face[468]).astype(int)
        iris = output[cy, cx + 5]
        self.assertGreater(iris[1], iris[2] + 20)  # Green over red.
        self.assertGreater(iris[0], iris[2] + 20)  # Blue over red: teal.
        corner = np.round(self.face[33]).astype(int)
        np.testing.assert_array_equal(output[corner[1], corner[0] + 3], self.frame[corner[1], corner[0] + 3])
        np.testing.assert_array_equal(output[cy + 40, cx], self.frame[cy + 40, cx])  # Cheek.

    def test_brows_turn_golden_but_not_the_skin(self):
        output = ssj_face.tint_brows(self.frame, self.face, 1.0).astype(int)
        x, y = np.round(self.face[ssj_face.BROWS[0][2]]).astype(int)
        self.assertGreater(output[y, x, 2], output[y, x, 0] + 40)  # Golden: red over blue.
        np.testing.assert_array_equal(output[y - 10, x], self.frame[y - 10, x])

    def test_nothing_without_strength_or_face(self):
        self.assertIs(ssj_face.render_face(self.frame, self.face, 0.0), self.frame)
        self.assertIs(ssj_face.render_face(self.frame, None, 1.0), self.frame)
        self.assertIs(ssj_face.tint_eyes(self.frame, np.zeros((10, 2), np.float32), 1.0), self.frame)


class HairImportTests(unittest.TestCase):
    def test_extracts_the_golden_hair_only(self):
        face = synthetic_face()
        image = face_picture(face)
        cv2.circle(image, (40, 40), 25, GOLD, -1)  # A yellow lamp far from the head.
        mask = ssj_face.hair_mask(image, face)
        cx, cy = face[ssj_face.NOSE]
        self.assertEqual(mask[int(cy - 1.2 * 160), int(cx)], 1)  # A spike.
        self.assertEqual(mask[int(cy - 0.75 * 160), int(cx - 0.1 * 160)], 1)  # The highlight inside the hair.
        self.assertEqual(mask[int(cy), int(cx)], 0)  # The face.
        self.assertEqual(mask[40, 40], 0)  # The lamp.
        view = ssj_face.extract_hair(image, face)
        self.assertEqual(view.rgba.shape[2], 4)
        self.assertEqual(view.anchors.shape, (len(ssj_face.HAIR_ANCHORS), 2))
        self.assertAlmostEqual(view.yaw, 0.0, places=3)

    def test_no_hair_no_view(self):
        face = synthetic_face()
        self.assertIsNone(ssj_face.extract_hair(face_picture(face, hair=False), face))

    def test_import_caches_and_reports_problems(self):
        face = synthetic_face()
        detect = Mock(return_value=face)
        messages = []
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            cv2.imwrite(str(folder / "ssj_front.png"), face_picture(face))
            cv2.imwrite(str(folder / "ssj_bald.png"), face_picture(face, hair=False))
            cv2.imwrite(str(folder / "photo_front.jpg"), face_picture(face, hair=False))  # Not an import.
            views = ssj_face.load_hair_views(folder, detect, messages.append)
            self.assertEqual([view.name for view in views], ["ssj_front"])
            self.assertEqual(detect.call_count, 2)
            self.assertTrue(any("No golden hair found in ssj_bald.png" in line for line in messages))
            again = ssj_face.load_hair_views(folder, Mock(return_value=None), messages.append)
            self.assertEqual([view.name for view in again], ["ssj_front"])  # From the cache.
            np.testing.assert_array_equal(again[0].rgba, views[0].rgba)
            np.testing.assert_allclose(again[0].anchors, views[0].anchors, atol=1e-4)

    def test_no_face_is_reported(self):
        messages = []
        with tempfile.TemporaryDirectory() as folder:
            cv2.imwrite(str(Path(folder) / "ssj_front.png"), face_picture(synthetic_face()))
            views = ssj_face.load_hair_views(Path(folder), Mock(return_value=None), messages.append)
        self.assertEqual(views, [])
        self.assertTrue(any("No face found" in line for line in messages))


class HairOverlayTests(unittest.TestCase):
    def setUp(self):
        self.source = synthetic_face()
        self.view = ssj_face.extract_hair(face_picture(self.source), self.source)

    def test_follows_the_live_face(self):
        overlay = ssj_face.HairOverlay([self.view])
        frame = np.full((520, 640, 3), 90, np.uint8)
        live = synthetic_face(cx=300, cy=300, angle=12.0, scale=0.8)
        output = overlay.render(frame, live, 1.0)
        # A spike of the source picture, mapped through the same similarity as the face.
        matrix, _ = cv2.estimateAffinePartial2D(self.source[list(ssj_face.HAIR_ANCHORS)],
                                                live[list(ssj_face.HAIR_ANCHORS)])
        spike = np.array([320.0, 260.0 - 1.2 * 160]) @ matrix[:, :2].T + matrix[:, 2]
        x, y = np.round(spike).astype(int)
        self.assertGreater(int(output[y, x, 2]), 200)  # Golden.
        np.testing.assert_array_equal(output[500, 20], frame[500, 20])
        np.testing.assert_array_equal(output[300, 300], frame[300, 300])  # The face itself is not covered.

    def test_picks_the_view_closest_to_the_head_turn(self):
        turned = ssj_face.HairView("ssj_left", self.view.rgba, self.view.anchors, -0.2)
        overlay = ssj_face.HairOverlay([self.view, turned])
        face = synthetic_face()
        face[ssj_face.NOSE, 0] -= 0.18 * 160
        self.assertIs(overlay.pick(face), turned)
        self.assertIs(overlay.pick(synthetic_face()), self.view)

    def test_strength_fades_it(self):
        overlay = ssj_face.HairOverlay([self.view])
        frame = np.full((520, 640, 3), 90, np.uint8)
        full = overlay.render(frame, synthetic_face(), 1.0).astype(int)
        half = overlay.render(frame, synthetic_face(), 0.5).astype(int)
        x, y = 320, int(260 - 1.2 * 160)
        self.assertGreater(full[y, x, 2], half[y, x, 2])
        self.assertGreater(half[y, x, 2], 90)
        self.assertIs(overlay.render(frame, synthetic_face(), 0.0), frame)


class TransformationTimelineTests(unittest.TestCase):
    def test_hair_flickers_late_in_the_charge_then_stays(self):
        power = ssj.PowerState()
        power.update(0.0, 0.0)
        self.assertEqual(power.levels(0.3).hair, 0.0)  # Early in the charge: normal hair.
        late = {power.levels(t).hair for t in np.arange(0.8, 1.5, 1 / 30)}
        self.assertEqual(late, {0.0, 0.9})  # Flickers between normal and golden.
        power.transform(1.5)
        self.assertEqual(power.levels(1.6).hair, 1.0)
        power.update(1.5 + ssj.FLASH_SECONDS + 0.01, None)
        self.assertEqual(power.levels(3.0).hair, 1.0)
        power.power_down(4.0)
        self.assertLess(power.levels(4.3).hair, 1.0)

    def test_render_super_saiyan_draws_the_face(self):
        face = synthetic_face()
        frame = np.full((520, 640, 3), SKIN, np.uint8)
        cv2.circle(frame, tuple(np.round(face[468]).astype(int)), 7, (40, 60, 90), -1)
        output = ssj.render_super_saiyan(frame, None, ssj.PowerLevels(hair=1.0), 0.0, None, face=face)
        self.assertTrue(np.any(output != frame))
        untouched = ssj.render_super_saiyan(frame, None, ssj.PowerLevels(), 0.0, None, face=face)
        np.testing.assert_array_equal(untouched, frame)


class HairPhotoTests(unittest.TestCase):
    def test_guided_photos_skip_and_prompt(self):
        frames = iter([np.full((48, 64, 3), value, np.uint8) for value in range(10, 200, 10)])
        capture = Mock()
        capture.read.side_effect = lambda: (True, next(frames))
        keys = iter([0, ord(" "), ord("s"), 0, ord(" ")])
        printed = []
        args = argparse.Namespace(camera=0, width=64, height=48, no_mirror=False)
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(app, "HAIR_DIR", Path(folder)), \
                patch.object(app, "open_camera", return_value=capture), \
                patch.object(app, "render_status_panel",
                             side_effect=lambda width, height, *a: np.zeros((height, width, 3), np.uint8)), \
                patch.object(app.cv2, "namedWindow"), patch.object(app.cv2, "imshow"), \
                patch.object(app.cv2, "destroyAllWindows"), \
                patch.object(app.cv2, "waitKey", side_effect=lambda _: next(keys)), \
                patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            self.assertEqual(app.capture_hair_photos(args), 0)
            names = sorted(path.name for path in Path(folder).iterdir())
            self.assertEqual(names, ["photo_front.jpg", "photo_right.jpg", "prompt.txt"])
            self.assertIn("Super Saiyan hair", (Path(folder) / "prompt.txt").read_text())
        capture.release.assert_called_once()
        self.assertTrue(any("ChatGPT or Gemini" in line for line in printed))

    def test_load_hair_without_pictures_gives_a_hint(self):
        messages = []
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "HAIR_DIR", Path(folder) / "missing"):
            self.assertIsNone(app.load_hair(messages.append))
        self.assertTrue(any("--ssj-hair-photos" in line for line in messages))


if __name__ == "__main__":
    unittest.main()
