import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import mediapipe as mp

import vanish_cam as app
from vanish_cam import (
    GestureHold, MultiViewGestureRecognizer, camera_source, compose_dashboard,
    find_linux_cameras, linux_camera_label, mode_name, recognize_gesture,
    render_status_panel, status_snapshot, victory_landmark_score,
)


def hand_points(extended=(True, True, False, False)):
    points = np.zeros((21, 3))
    for base, x, opened, spread in zip(
        (5, 9, 13, 17), (-0.45, 0.0, 0.4, 0.75), extended, (-0.35, 0.25, 0.0, 0.0)
    ):
        if opened:
            points[base : base + 4] = [
                (x, 1.0, 0.0), (x + spread * 0.45, 1.7, 0.0),
                (x + spread * 0.75, 2.15, 0.0), (x + spread, 2.5, 0.0),
            ]
        else:
            points[base : base + 4] = [
                (x, 1.0, 0.0), (x, 1.5, 0.2),
                (x, 1.3, 0.5), (x, 0.95, 0.3),
            ]
    return points


def landmarks(points):
    return [SimpleNamespace(x=x, y=y, z=z) for x, y, z in points]


class VictoryGestureTests(unittest.TestCase):
    def test_victory_with_back_palm_rotation_mirror_and_scale(self):
        points = hand_points()
        for angle in (0.0, 0.7, 1.57, 2.6, np.pi):
            c, s = np.cos(angle), np.sin(angle)
            rotation = np.array(((c, -s, 0), (s, c, 0), (0, 0, 1)))
            tilt = np.array(((1, 0, 0), (0, c, -s), (0, s, c)))
            for mirror in (1, -1):
                for scale in (0.02, 1.0, 100.0):
                    with self.subTest(angle=angle, mirror=mirror, scale=scale):
                        transformed = points @ rotation @ tilt
                        transformed[:, 0] *= mirror
                        transformed = transformed * scale + (0.5, 0.3, 0.1)
                        self.assertGreater(victory_landmark_score(transformed), 0.62)

    def test_other_gestures_do_not_trigger(self):
        for fingers in (
            (False, False, False, False),  # Fist.
            (True, True, True, True),  # Open palm.
            (True, False, False, False),  # Index only.
            (True, False, False, True),  # Horns.
            (True, True, True, False),  # Three fingers.
        ):
            with self.subTest(fingers=fingers):
                self.assertEqual(victory_landmark_score(hand_points(fingers)), 0.0)

    def test_invalid_or_degenerate_landmarks(self):
        for points in (np.zeros((21, 3)), np.zeros((20, 3)), np.full((21, 3), np.nan)):
            self.assertEqual(victory_landmark_score(points), 0.0)

    def test_landmarks_trigger_without_classifier_category(self):
        result = SimpleNamespace(
            hand_world_landmarks=[landmarks(hand_points())], hand_landmarks=[], gestures=[]
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        name, score = recognize_gesture(recognizer, None, 1000)
        self.assertEqual(name, "Victory")
        self.assertGreater(score, 0.62)

    def test_normalized_landmark_fallback_handles_video_aspect_ratio(self):
        image = SimpleNamespace(width=960, height=540)
        points = hand_points() * 40 + (480, 200, 0)
        normalized = points / (image.width, image.height, image.width)
        result = SimpleNamespace(
            hand_world_landmarks=[], hand_landmarks=[landmarks(normalized)], gestures=[]
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        self.assertEqual(recognize_gesture(recognizer, image, 1000)[0], "Victory")

    def test_existing_classifier_still_works(self):
        result = SimpleNamespace(
            hand_world_landmarks=[], hand_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.9)]],
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        self.assertEqual(recognize_gesture(recognizer, None, 1000), ("Victory", 0.9))

    def test_occluded_folded_fingers_can_appear_short_and_straight(self):
        points = hand_points()
        for base in (13, 17):
            points[base : base + 4] = [
                (0.4, 1.0, 0.0), (0.4, 1.1, 0.0),
                (0.4, 1.2, 0.0), (0.4, 1.3, 0.0),
            ]
        self.assertGreater(victory_landmark_score(points), 0.62)

    def test_hidden_fingers_with_coincident_landmarks(self):
        points = hand_points()
        points[13:16] = points[13]
        points[16] = points[13]
        points[17:20] = points[17]
        points[20] = points[17]
        self.assertGreater(victory_landmark_score(points), 0.62)

    def test_visible_geometry_is_used_even_with_inaccurate_world_landmarks(self):
        image = SimpleNamespace(width=960, height=540)
        points = hand_points() * 40 + (480, 200, 0)
        world = hand_points()
        world[8] = world[6]
        self.assertEqual(victory_landmark_score(world), 0.0)
        result = SimpleNamespace(
            hand_world_landmarks=[landmarks(world)],
            hand_landmarks=[landmarks(points / (960, 540, 960))], gestures=[],
        )
        recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
        self.assertEqual(recognize_gesture(recognizer, image, 1000)[0], "Victory")

    def test_diagnostics_distinguish_missing_hand_and_rejected_gesture(self):
        for hands, expected in (([], "No_Hand"), ([landmarks(hand_points((False,) * 4))], "Hand_Detected")):
            result = SimpleNamespace(hand_world_landmarks=hands, hand_landmarks=[], gestures=[])
            recognizer = SimpleNamespace(recognize_for_video=lambda image, timestamp: result)
            self.assertEqual(recognize_gesture(recognizer, None, 1000)[0], expected)


class GestureHoldTests(unittest.TestCase):
    def test_triggers_only_after_holding(self):
        hold = GestureHold(0.3)
        self.assertFalse(hold.update(True, 1.0))
        self.assertFalse(hold.update(True, 1.2))
        self.assertTrue(hold.update(True, 1.3))

    def test_a_single_missed_frame_does_not_restart_the_count(self):
        hold = GestureHold(0.3)
        hold.update(True, 1.0)
        hold.update(False, 1.14)
        self.assertTrue(hold.update(True, 1.3))

    def test_letting_go_restarts_the_count(self):
        hold = GestureHold(0.3)
        hold.update(True, 1.0)
        hold.update(False, 1.5)
        self.assertFalse(hold.update(True, 1.6))
        self.assertTrue(hold.update(True, 1.95))

    def test_must_let_go_before_triggering_again(self):
        hold = GestureHold(0.3)
        hold.update(True, 1.0)
        self.assertTrue(hold.update(True, 1.3))
        for now in (1.5, 2.0, 3.0):
            self.assertFalse(hold.update(True, now))
        hold.update(False, 3.5)
        hold.update(True, 3.6)
        self.assertTrue(hold.update(True, 3.95))


class ModeTests(unittest.TestCase):
    def test_goku_is_an_alias_for_dragonball(self):
        self.assertEqual(mode_name("goku"), "dragonball")
        self.assertEqual(mode_name("Naruto"), "naruto")
        with self.assertRaises(Exception):
            mode_name("vegeta")


class MultiViewTests(unittest.TestCase):
    def setUp(self):
        self.empty = SimpleNamespace(hand_world_landmarks=[], hand_landmarks=[], gestures=[])
        self.victory = SimpleNamespace(
            hand_world_landmarks=[], hand_landmarks=[],
            gestures=[[SimpleNamespace(category_name="Victory", score=0.9)]],
        )
        self.image = mp.Image(
            image_format=mp.ImageFormat.SRGB, data=np.zeros((32, 48, 3), dtype=np.uint8)
        )

    def test_rotated_detection_and_preferred_view_are_used(self):
        calls = []

        def recognize(image):
            calls.append((image.width, image.height))
            return self.victory if image.width == 32 else self.empty

        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.empty),
            SimpleNamespace(recognize=recognize),
        )
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "Victory")
        self.assertEqual(calls, [(48, 32), (32, 48)])
        self.assertEqual(detector.preferred_rotation, 1)
        calls.clear()
        self.assertEqual(recognize_gesture(detector, self.image, 1140)[0], "Victory")
        self.assertEqual(calls, [(32, 48)])

    def test_failed_search_is_throttled_without_reusing_old_positive(self):
        calls = []
        alternate = SimpleNamespace(recognize=lambda image: calls.append(image) or self.empty)
        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.empty), alternate
        )
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "No_Hand")
        self.assertEqual(len(calls), 3)  # Retries are spread over successive frames.
        recognize_gesture(detector, self.image, 1100)
        self.assertEqual(len(calls), 3)
        alternate.recognize = lambda image: self.victory
        self.assertEqual(recognize_gesture(detector, self.image, 1420)[0], "Victory")
        alternate.recognize = lambda image: self.empty
        self.assertEqual(recognize_gesture(detector, self.image, 1560)[0], "No_Hand")

    def test_primary_victory_avoids_extra_inference(self):
        calls = []
        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.victory),
            SimpleNamespace(recognize=lambda image: calls.append(image) or self.empty),
        )
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "Victory")
        self.assertEqual(calls, [])

    def test_lower_hand_crop_recovers_a_small_sideways_v(self):
        calls = []

        def recognize(image):
            calls.append((image.width, image.height))
            return self.victory if (image.width, image.height) == (37, 24) else self.empty

        detector = MultiViewGestureRecognizer(
            SimpleNamespace(recognize_for_video=lambda image, timestamp: self.empty),
            SimpleNamespace(recognize=recognize),
        )
        # The lower crop is reached in the second retry batch.
        self.assertEqual(recognize_gesture(detector, self.image, 1000)[0], "No_Hand")
        self.assertEqual(recognize_gesture(detector, self.image, 1140)[0], "Victory")
        self.assertEqual(detector.preferred_crop, "lower_left")
        self.assertEqual(detector.preferred_rotation, 0)
        calls.clear()
        self.assertEqual(recognize_gesture(detector, self.image, 1280)[0], "Victory")
        self.assertEqual(calls, [(37, 24)])



class LinuxCameraTests(unittest.TestCase):
    def test_skips_metadata_nodes_and_v4l2loopback_outputs(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            sysfs = root / "class"
            sysfs.mkdir()
            for name, parent, index in (
                ("video0", "pci/usb1", "0"), ("video1", "pci/usb1", "1"),
                ("video2", "pci/usb2", "0"), ("video10", "virtual/video4linux", "0"),
            ):
                device = root / "devices" / parent / name
                device.mkdir(parents=True)
                (device / "index").write_text(index + "\n")
                try:
                    (sysfs / name).symlink_to(device)
                except OSError:  # Windows without Developer Mode cannot create symlinks.
                    self.skipTest("symlinks are not available")
            self.assertEqual(find_linux_cameras(sysfs), ["/dev/video0", "/dev/video2"])

    def test_camera_accepts_index_or_device_path(self):
        self.assertEqual(camera_source("1"), 1)
        self.assertEqual(camera_source("/dev/video2"), "/dev/video2")

    def test_camera_label_comes_from_sysfs(self):
        with tempfile.TemporaryDirectory() as root:
            device = Path(root) / "video2"
            device.mkdir()
            (device / "name").write_text("USB Camera\n")
            self.assertEqual(linux_camera_label("/dev/video2", Path(root)), "USB Camera")
            self.assertEqual(linux_camera_label("/dev/video9", Path(root)), "")


class WindowsCameraTests(unittest.TestCase):
    def test_names_keep_opencv_indices_and_hide_virtual_cameras(self):
        names = ["OBS Virtual Camera", "Integrated Camera", "Meta Quest 3", "Logitech C920"]
        self.assertEqual(app.find_windows_cameras(names),
                         [(1, "Integrated Camera"), (3, "Logitech C920")])

    def test_probes_indices_when_names_are_unavailable(self):
        captures = {0: Mock(), 2: Mock()}
        with patch.object(app, "windows_camera_names", return_value=None):
            cameras = app.find_windows_cameras(probe=captures.get)
        self.assertEqual(cameras, [(0, "Camera 0"), (2, "Camera 2")])
        for capture in captures.values():
            capture.release.assert_called_once()

    def test_open_camera_picks_the_only_real_camera(self):
        info = {}
        capture = Mock()
        with patch.object(app.platform, "system", return_value="Windows"), \
                patch.object(app, "windows_camera_names", return_value=["OBS Virtual Camera", "Integrated Camera"]), \
                patch.object(app, "_open_capture", return_value=capture) as opened, \
                patch("builtins.print"):
            self.assertIs(app.open_camera(None, 640, 480, info), capture)
        self.assertEqual(opened.call_args.args[0], 1)
        self.assertEqual(info["label"], "1 (Integrated Camera)")

    def test_open_camera_refuses_to_read_only_virtual_cameras(self):
        with patch.object(app.platform, "system", return_value="Windows"), \
                patch.object(app, "windows_camera_names", return_value=["OBS Virtual Camera", "Meta Quest 2"]), \
                patch.object(app, "_open_capture") as opened, patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "Only virtual cameras"):
                app.open_camera(None, 640, 480)
        opened.assert_not_called()

    def test_explicit_camera_gets_its_name(self):
        with patch.object(app, "windows_camera_names", return_value=["OBS Virtual Camera", "Integrated Camera"]):
            self.assertEqual(app.camera_label(1, "Windows"), "Integrated Camera")
            self.assertEqual(app.camera_label(7, "Windows"), "")

    def test_camera_panel_lists_names(self):
        panel = app.render_camera_panel(360, 300, [(1, "Integrated Camera"), (3, "Kamera ü")], 1)
        self.assertEqual(panel.shape, (300, 360, 3))


class LivePanelTests(unittest.TestCase):
    def test_buttons_sit_at_the_bottom_and_are_hit_where_drawn(self):
        controls = app.panel_controls(True, True, False)
        self.assertEqual([name for name, _, _ in controls], ["recalibrate", "flames", "eyes", "brows", "hair"])
        rects = app.panel_buttons(380, 540, len(controls))
        self.assertEqual(rects[-1][3], 540 - 12)
        self.assertEqual(rects[0][1], rects[1][1])  # Recalibrate and the flame aura on the top row.
        self.assertEqual({rect[1] for rect in rects[2:]}, {rects[2][1]})  # Eyes, brows, hair on the bottom row.
        self.assertLess(rects[0][3], rects[2][1])
        self.assertEqual(app.panel_buttons(380, 540, 1), [(12, 540 - 12 - app.PANEL_BUTTON_HEIGHT, 368, 528)])
        for (name, _, _), (x0, y0, x1, y1) in zip(controls, rects):
            self.assertTrue(12 <= x0 < x1 <= 380 - 12)
            self.assertEqual(app.panel_hit(380, 540, controls, (x0 + x1) // 2, (y0 + y1) // 2), name)
        self.assertIsNone(app.panel_hit(380, 540, controls, 190, 40))
        self.assertEqual([name for name, _, _ in app.panel_controls(False, True, True)], ["recalibrate"])

    def test_panel_draws_the_switch_states(self):
        on = app.render_status_panel(380, 540, "dragonball", "super", "0", "x", [], "", app.panel_controls(True, True, True))
        off = app.render_status_panel(380, 540, "dragonball", "super", "0", "x", [], "", app.panel_controls(True, False, True))
        self.assertEqual(on.shape, (540, 380, 3))
        x0, y0, x1, y1 = app.panel_buttons(380, 540, 5)[2]
        self.assertTrue(np.any(on[y0:y1, x0:x1] != off[y0:y1, x0:x1]))
        hairless = app.render_status_panel(380, 540, "dragonball", "super", "0", "x", [], "",
                                           app.panel_controls(True, True, True, False))
        x0, y0, x1, y1 = app.panel_buttons(380, 540, 5)[4]
        self.assertTrue(np.any(on[y0:y1, x0:x1] != hairless[y0:y1, x0:x1]))


class DashboardTests(unittest.TestCase):
    def test_compose_keeps_the_video_untouched_on_the_left(self):
        display = np.full((24, 40, 3), 7, np.uint8)
        panel = np.full((24, 60, 3), 3, np.uint8)
        view = compose_dashboard(display, panel)
        self.assertEqual(view.shape, (24, 100, 3))
        np.testing.assert_array_equal(view[:, :40], display)
        np.testing.assert_array_equal(view[:, 40:], panel)
        np.testing.assert_array_equal(display, np.full((24, 40, 3), 7, np.uint8))

    def test_panel_is_resized_to_the_video_height(self):
        view = compose_dashboard(np.zeros((30, 40, 3), np.uint8), np.zeros((10, 60, 3), np.uint8))
        self.assertEqual(view.shape, (30, 100, 3))

    def test_status_panel_has_the_requested_size(self):
        panel = render_status_panel(380, 300, "dragonball", "ready", "/dev/video4",
                                    "Two fingers on the forehead", ["Background ready."])
        self.assertEqual(panel.shape, (300, 380, 3))

    def test_status_snapshot_follows_the_phase(self):
        state = SimpleNamespace(phase="calibrating")
        power = SimpleNamespace(transformed=False, phase="off")
        action, key = status_snapshot(state, "dragonball", False, power, "pose", 3)
        self.assertEqual(key, "calibrating")
        self.assertIn("3", action)

        state.phase = "ready"
        action, key = status_snapshot(state, "dragonball", True, power, "pose", None)
        self.assertEqual(key, "ready")
        self.assertIn("fists", action)

        power.transformed = True
        action, key = status_snapshot(state, "dragonball", True, power, "pose", None)
        self.assertEqual(key, "super")
        self.assertIn("Super Saiyan", action)

        state.phase = "vanished"
        action, key = status_snapshot(state, "dragonball", False, power, "pose", None)
        self.assertEqual(key, "vanished")
        self.assertIn("R", action)


if __name__ == "__main__":
    unittest.main()
