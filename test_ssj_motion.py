import math
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

import ssj_face
import ssj_motion
import super_saiyan_effect as ssj
from test_ssj_face import face_picture, synthetic_face

DETECTION = 0.08  # Seconds between detections, like the Dragon Ball detector.
FRAME = 1 / 30


def anchors(face):
    return face[list(ssj_face.HAIR_ANCHORS)]


class FitTests(unittest.TestCase):
    def test_matches_opencv_on_exact_points(self):
        source = anchors(synthetic_face())
        target = anchors(synthetic_face(cx=300, cy=280, angle=12.0, scale=0.8))
        ours = ssj_motion.fit_similarity(source, target)
        opencv, _ = cv2.estimateAffinePartial2D(source, target)
        np.testing.assert_allclose(ours, opencv, atol=1e-3)

    def test_talking_does_not_resize_the_hair(self):
        # The chin moves when the mouth opens; with its low weight the fitted scale barely changes.
        source = anchors(synthetic_face())
        talking = synthetic_face()
        talking[ssj_face.CHIN, 1] += 0.1 * 160
        fit = ssj_motion.fit_similarity(source, anchors(talking), ssj_face.ANCHOR_WEIGHTS)
        self.assertLess(abs(math.hypot(fit[0, 0], fit[1, 0]) - 1.0), 0.01)

    def test_degenerate_input(self):
        points = np.zeros((9, 2), np.float32)
        self.assertIsNone(ssj_motion.fit_similarity(points, points))


class HeadTrackerTests(unittest.TestCase):
    def follow(self, path, seconds=2.0, noise=0.0, seed=1):
        """Detections of synthetic_face(cx=path(t)) every DETECTION s; tracked face centre every frame."""
        rng = np.random.default_rng(seed)
        tracker = ssj_face.head_tracker()
        next_detection, outputs = 0.0, []
        for index in range(int(seconds / FRAME)):
            t = index * FRAME
            detection = None
            if t >= next_detection:
                detection = synthetic_face(cx=path(t))
                detection = detection + rng.normal(0.0, noise, detection.shape).astype(np.float32)
                next_detection += DETECTION
            face = tracker.update(t, detection, t if detection is not None else None)
            outputs.append((t, None if face is None else float(face[ssj_face.NOSE, 0])))
        return outputs

    def test_moves_every_frame_without_holding_and_jumping(self):
        outputs = self.follow(lambda t: 200.0 + 200.0 * t)
        xs = np.array([x for t, x in outputs if t > 0.5])
        steps = np.diff(xs)
        self.assertTrue(np.all(steps > 0))  # Never holds still while the head moves.
        self.assertLess(steps.max(), 1.6 * np.median(steps))  # No hold-then-jump.
        truth = np.array([200.0 + 200.0 * t for t, _ in outputs if t > 0.5])
        self.assertLess(np.abs(xs - truth).max(), 0.05 * 160)

    def test_smooths_landmark_jitter_on_a_still_head(self):
        # Measured where the hair is placed: the weighted fit of the anchors, at their centre.
        rng = np.random.default_rng(1)
        reference = anchors(synthetic_face())
        weights = np.asarray(ssj_face.ANCHOR_WEIGHTS, np.float32)
        center = (weights[:, None] * reference).sum(axis=0) / weights.sum()
        tracker, raw, smooth = ssj_face.head_tracker(), [], []
        for index in range(int(3.0 / FRAME)):
            t = index * FRAME
            detection = None
            if index % 2 == 0:
                detection = synthetic_face() + rng.normal(0.0, 2.0, (478, 2)).astype(np.float32)
                fit = ssj_motion.fit_similarity(reference, anchors(detection), weights)
                raw.append(ssj_motion.apply(fit, center[None])[0, 0])
            face = tracker.update(t, detection, t if detection is not None else None)
            fit = ssj_motion.fit_similarity(reference, anchors(face), weights)
            if t > 0.5:
                smooth.append(ssj_motion.apply(fit, center[None])[0, 0])
        self.assertLess(np.std(smooth), 0.7 * np.std(raw))

    def test_sudden_stop_overshoots_little_and_settles(self):
        outputs = self.follow(lambda t: 200.0 + 300.0 * min(t, 1.0), seconds=1.8)
        after = [(t, x) for t, x in outputs if t >= 1.0]
        overshoot = max(x for _, x in after) - 500.0
        self.assertLess(overshoot, 0.1 * 160)
        settled = [x for t, x in after if t > 1.4]
        self.assertLess(max(abs(x - 500.0) for x in settled), 0.02 * 160)

    def test_big_jump_reacquires_and_long_gap_loses_the_face(self):
        tracker = ssj_face.head_tracker()
        tracker.update(0.0, synthetic_face(cx=200), 0.0)
        face = tracker.update(0.08, synthetic_face(cx=420), 0.08)  # More than half a face width at once.
        self.assertAlmostEqual(float(face[ssj_face.NOSE, 0]), 420.0, delta=0.5)
        self.assertIsNotNone(tracker.update(0.08 + ssj_motion.TRACK_LOST_SECONDS - 0.01))
        self.assertIsNone(tracker.update(0.08 + ssj_motion.TRACK_LOST_SECONDS + 0.01))

    def test_follows_rotation_and_scale(self):
        tracker = ssj_face.head_tracker()
        for index in range(15):
            t = index * DETECTION
            tracker.update(t, synthetic_face(angle=10.0, scale=0.8), t)
        face = tracker.update(15 * DETECTION)
        np.testing.assert_allclose(anchors(face), anchors(synthetic_face(angle=10.0, scale=0.8)), atol=0.5)


class HairDynamicsTests(unittest.TestCase):
    def run_motion(self, velocity, seconds, fps=30, stop_at=None, kick=False):
        dynamics = ssj_motion.HairDynamics()
        if kick:
            dynamics.kick()
        lags, x = [], 300.0
        for index in range(int(seconds * fps) + 1):
            t = index / fps
            if index:
                x += (velocity if stop_at is None or t <= stop_at else 0.0) / fps
            dynamics.step(t, np.array((x, 200.0)), 0.0, 160.0)
            lags.append((t, dynamics.offset.copy(), dynamics.roll))
        return lags

    def test_still_head_still_hair(self):
        for _, offset, roll in self.run_motion(0.0, 1.0):
            self.assertEqual((offset[0], offset[1], roll), (0.0, 0.0, 0.0))

    def test_lags_behind_overshoots_once_and_settles(self):
        lags = self.run_motion(160.0, 3.0, stop_at=1.0)  # One face width per second, then stop.
        moving = [offset[0] for t, offset, _ in lags if 0.6 < t <= 1.0]
        self.assertLess(max(moving), -0.02)  # The tips trail the motion.
        after = [offset[0] for t, offset, _ in lags if t > 1.0]
        self.assertGreater(max(after), 0.005)  # Swings past the rest position once...
        self.assertLess(max(abs(value) for value in after[-15:]), 0.001)  # ...and settles.

    def test_same_motion_at_any_frame_rate(self):
        slow = {round(t, 3): offset[0] for t, offset, _ in self.run_motion(160.0, 1.5, fps=30, stop_at=0.8)}
        fast = {round(t, 3): offset[0] for t, offset, _ in self.run_motion(160.0, 1.5, fps=60, stop_at=0.8)}
        shared = [t for t in slow if t in fast and t > 0.2]
        peak = max(abs(slow[t]) for t in shared)
        self.assertLess(max(abs(slow[t] - fast[t]) for t in shared), 0.1 * peak + 1e-4)

    def test_clamped_and_kick_goes_up(self):
        lags = self.run_motion(5000.0, 0.5)
        self.assertLessEqual(max(abs(offset[0]) for _, offset, _ in lags), 2 * ssj_motion.MAX_TIP_LAG + 1e-9)
        kicked = self.run_motion(0.0, 0.3, kick=True)
        self.assertLess(min(offset[1] for _, offset, _ in kicked), -0.01)


class HairWarpTests(unittest.TestCase):
    def setUp(self):
        source = synthetic_face()
        self.view = ssj_face.extract_hair(face_picture(source), source)
        self.face = synthetic_face(cx=330, cy=280, angle=6.0, scale=0.9)
        self.shape = (520, 640, 3)

    def place(self, offset=(0.0, 0.0), roll=0.0, flutter=0.0, t=0.0):
        overlay = ssj_face.HairOverlay([self.view])
        motion = ssj_motion.HairMotion(np.array(offset), roll, flutter)
        return overlay, overlay.place_live(self.face, self.shape, t, motion)

    def full(self, placed):
        canvas = np.zeros(self.shape[:2] + (4,), np.uint8)
        x0, y0, x1, y1 = placed.box
        canvas[y0:y1, x0:x1] = placed.rgba
        return canvas

    def test_no_motion_matches_the_rigid_fit(self):
        overlay, live = self.place()
        rigid = overlay.place(self.face, self.shape)
        diff = np.abs(self.full(live).astype(int) - self.full(ssj_face.PlacedHair(*rigid)).astype(int))
        self.assertLessEqual(int(np.percentile(diff, 99.9)), 2)

    def test_tips_move_roots_stay(self):
        _, still = self.place()
        _, moved = self.place(offset=(0.06, 0.0))
        still, moved = self.full(still)[:, :, 3], self.full(moved)[:, :, 3]
        tips = np.argwhere(still > 200)
        top = tips[tips[:, 0] < tips[:, 0].min() + 10]  # The highest spike.
        y, x = top[len(top) // 2]
        self.assertGreater(int(still[y, x]) - int(moved[y, x]), 100)  # The tip has moved away.
        root_y = int(self.face[ssj_face.FOREHEAD_TOP, 1]) - 4
        root_x = int(self.face[ssj_face.FOREHEAD_TOP, 0])
        self.assertLessEqual(abs(int(still[root_y, root_x]) - int(moved[root_y, root_x])), 3)

    def test_flutter_is_deterministic_and_bounded(self):
        _, a = self.place(flutter=ssj_motion.FLUTTER_AMPLITUDE, t=0.37)
        _, b = self.place(flutter=ssj_motion.FLUTTER_AMPLITUDE, t=0.37)
        _, c = self.place(flutter=ssj_motion.FLUTTER_AMPLITUDE, t=0.61)
        np.testing.assert_array_equal(a.rgba, b.rgba)
        self.assertTrue(np.any(self.full(a) != self.full(c)))  # It moves over time...
        _, still = self.place()
        moved = np.abs(self.full(a)[:, :, 3].astype(int) - self.full(still)[:, :, 3].astype(int)) > 100
        width = float(np.linalg.norm(self.face[ssj_face.FACE_RIGHT] - self.face[ssj_face.FACE_LEFT]))
        band = max(2, int(2 * ssj_motion.FLUTTER_AMPLITUDE * width))
        grown = cv2.dilate((self.full(still)[:, :, 3] > 100).astype(np.uint8), np.ones((2 * band + 1,) * 2, np.uint8))
        self.assertFalse(np.any(moved & (grown == 0)))  # ...but only by about its amplitude.


class ViewFadeTests(unittest.TestCase):
    def setUp(self):
        source = synthetic_face()
        front = ssj_face.extract_hair(face_picture(source), source, "front")
        self.left = ssj_face.HairView("left", front.rgba, front.anchors, -0.2)
        self.front = front
        self.overlay = ssj_face.HairOverlay([front, self.left])

    def test_noisy_yaw_across_the_boundary_switches_once(self):
        rng = np.random.default_rng(3)
        switches, current = 0, None
        for index in range(90):
            t = index * FRAME
            yaw = -0.05 - 0.15 * index / 90 + rng.normal(0, 0.03)
            shown = self.overlay.select(yaw, t)[-1][0]
            if current is not None and shown is not current:
                switches += 1
            current = shown
        self.assertEqual(switches, 1)
        self.assertIs(current, self.left)

    def test_fade_blends_then_shows_only_the_new_picture(self):
        self.overlay.select(0.0, 0.0)
        self.overlay.select(-0.2, 0.125)
        layers = self.overlay.select(-0.2, 0.125 + ssj_face.VIEW_SWITCH_HOLD)
        self.assertEqual([view.name for view, _ in layers], ["front", "left"])
        middle = self.overlay.select(-0.2, 0.125 + ssj_face.VIEW_SWITCH_HOLD + ssj_face.VIEW_FADE_SECONDS / 2)
        self.assertAlmostEqual(middle[1][1], 0.5, places=2)
        done = self.overlay.select(-0.2, 0.125 + ssj_face.VIEW_SWITCH_HOLD + ssj_face.VIEW_FADE_SECONDS + 0.01)
        self.assertEqual([(view.name, weight) for view, weight in done], [("left", 1.0)])

    def test_blend_mixes_alpha(self):
        a = ssj_face.PlacedHair(np.full((4, 4, 4), 255, np.uint8), (0, 0, 4, 4))
        b = ssj_face.PlacedHair(np.zeros((4, 4, 4), np.uint8), (2, 0, 6, 4))
        mixed = ssj_face._blend([(a, 0.5), (b, 0.5)])
        self.assertEqual(mixed.box, (0, 0, 6, 4))
        self.assertEqual(int(mixed.rgba[0, 0, 3]), 127)  # Only the fading-out picture covers it: half alpha.


class SharedPlacementTests(unittest.TestCase):
    def test_aura_and_drawing_share_one_placement(self):
        source = synthetic_face()
        overlay = ssj_face.HairOverlay([ssj_face.extract_hair(face_picture(source), source)])
        face = synthetic_face()
        frame = np.full((520, 640, 3), 90, np.uint8)
        body = np.zeros(frame.shape[:2], np.float32)
        cv2.ellipse(body, (320, 300), (90, 130), 0, 0, 360, 1.0, -1)
        placed = overlay.place_live(face, frame.shape, 0.0, ssj_motion.HairMotion(np.zeros(2), 0.0, 0.01))
        with patch.object(overlay, "place", side_effect=AssertionError("fitted again")):
            output = ssj.render_super_saiyan(frame, body, ssj.PowerLevels(aura=1.0, hair=1.0), 0.5,
                                             ssj.AuraRenderer(), face=face, hair=overlay, placed=placed)
        drawn = ssj_face.HairOverlay.render_placed(frame, placed, 1.0)
        inside = ssj_face.HairOverlay.mask_from(placed, frame.shape) > 0.97
        self.assertLess(np.abs(output.astype(int) - drawn.astype(int))[inside].max(), 10)

    def test_fast_enough_for_live_video(self):
        source = synthetic_face(width=260)
        overlay = ssj_face.HairOverlay([ssj_face.extract_hair(face_picture(source), source)])
        tracker, dynamics = ssj_face.head_tracker(), ssj_motion.HairDynamics()
        samples = []
        for repeat in range(3):
            started = time.perf_counter()
            for index in range(15):
                t = repeat + index * FRAME
                face = tracker.update(t, synthetic_face(cx=300 + index, width=260) if index % 3 == 0 else None,
                                      t if index % 3 == 0 else None)
                dynamics.step(t, *ssj_face.head_pose(face))
                overlay.place_live(face, (540, 960, 3), t, dynamics.motion(1.0))
            samples.append((time.perf_counter() - started) / 15)
        self.assertLess(min(samples), 0.008)  # Tracking + dynamics + warp per frame.


if __name__ == "__main__":
    unittest.main()
