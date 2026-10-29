import argparse
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

import home_ui
import vanish_cam as app


def center(buttons, name):
    x0, y0, x1, y1 = next(button for button in buttons if button.name == name).rect
    return (x0 + x1) // 2, (y0 + y1) // 2


class LayoutTests(unittest.TestCase):
    def test_buttons_are_hit_where_they_are_drawn(self):
        buttons = home_ui.layout(show_camera=True, show_hair=True)
        for name in ("mode:dragonball", "mode:normal", "mode:naruto", "camera", "photos", "prompt",
                     "folder", "check", "start"):
            self.assertEqual(home_ui.hit(buttons, *center(buttons, name)), name)
        self.assertIsNone(home_ui.hit(buttons, 2, 2))

    def test_no_buttons_overlap_or_leave_the_window(self):
        buttons = home_ui.layout(show_camera=True, show_hair=True)
        for index, button in enumerate(buttons):
            x0, y0, x1, y1 = button.rect
            self.assertTrue(0 <= x0 < x1 <= home_ui.WIDTH and 0 <= y0 < y1 <= home_ui.HEIGHT)
            for other in buttons[index + 1:]:
                a0, b0, a1, b1 = other.rect
                self.assertTrue(x1 < a0 or a1 < x0 or y1 < b0 or b1 < y0, (button.name, other.name))

    def test_hidden_sections_have_no_buttons_or_keys(self):
        buttons = home_ui.layout(show_camera=False, show_hair=False)
        names = {button.name for button in buttons}
        self.assertFalse(names & {"camera", "photos", "prompt", "folder", "check"})
        self.assertIsNone(home_ui.key_action(buttons, ord("t")))
        self.assertIsNone(home_ui.key_action(buttons, ord("w")))

    def test_keys(self):
        buttons = home_ui.layout(show_camera=True, show_hair=True)
        self.assertEqual(home_ui.key_action(buttons, ord("2")), "mode:normal")
        self.assertEqual(home_ui.key_action(buttons, ord("T")), "photos")
        self.assertEqual(home_ui.key_action(buttons, 13), "start")
        self.assertEqual(home_ui.key_action(buttons, 27), "quit")
        self.assertIsNone(home_ui.key_action(buttons, 255))

    def test_render_has_the_window_size(self):
        settings = home_ui.HomeSettings(camera=1, camera_label="Kamera ü")
        buttons = home_ui.layout(True, True)
        image = home_ui.render_home(settings, buttons, 2, "Not set up", ["one", "two"])
        self.assertEqual(image.shape, (home_ui.HEIGHT, home_ui.WIDTH, 3))


class HomeLoopTests(unittest.TestCase):
    def run_home(self, events, settings=None, **actions):
        """events: key codes, or (x, y) clicks delivered before the next waitKey returns 255."""
        mouse = {}
        pending = iter(events)

        def wait(_):
            event = next(pending)
            if isinstance(event, tuple):
                mouse["callback"](home_ui.cv2.EVENT_LBUTTONUP, *event, 0, None)
                return 255
            return event

        with ExitStack() as mocks:
            mocks.enter_context(patch.object(home_ui.cv2, "namedWindow"))
            mocks.enter_context(patch.object(home_ui.cv2, "setMouseCallback",
                                             side_effect=lambda name, callback: mouse.update(callback=callback)))
            mocks.enter_context(patch.object(home_ui.cv2, "imshow"))
            destroy = mocks.enter_context(patch.object(home_ui.cv2, "destroyWindow"))
            mocks.enter_context(patch.object(home_ui.cv2, "getWindowProperty", return_value=1))
            mocks.enter_context(patch.object(home_ui.cv2, "waitKey", side_effect=wait))
            result = home_ui.run_home(settings or home_ui.HomeSettings(), home_ui.HomeActions(**actions))
        destroy.assert_called_once_with(home_ui.WINDOW)
        return result

    def test_keys_choose_the_effect_and_start(self):
        result = self.run_home([ord("3"), 13])
        self.assertEqual(result.mode, "naruto")

    def test_quit_returns_nothing(self):
        self.assertIsNone(self.run_home([ord("q")]))

    def test_mouse_changes_camera_and_runs_hair_actions(self):
        buttons = home_ui.layout(True, True)
        cameras = [(1, "Integrated Camera"), (3, "Logitech C920")]
        photos = Mock(return_value=["Saved 3 photos."])
        failing = Mock(side_effect=RuntimeError("webcam busy"))
        status = Mock(return_value="Not set up")
        result = self.run_home(
            [center(buttons, "camera"), center(buttons, "photos"), center(buttons, "check"),
             center(buttons, "mode:normal"), center(buttons, "start")],
            home_ui.HomeSettings(camera=1, camera_label="Integrated Camera"),
            cameras=cameras, choose_camera=lambda settings: cameras[1], take_photos=photos,
            check_pictures=failing, hair_status=status)
        self.assertEqual((result.camera, result.camera_label, result.mode), (3, "Logitech C920", "normal"))
        photos.assert_called_once()
        failing.assert_called_once()  # The error is shown in the window, the window stays open.
        self.assertGreaterEqual(status.call_count, 2)  # Refreshed after taking photos.

    def test_hair_buttons_only_for_dragon_ball(self):
        photos = Mock(return_value=[])
        result = self.run_home([ord("2"), ord("t"), 13], take_photos=photos)
        self.assertEqual(result.mode, "normal")
        photos.assert_not_called()


class SettingsTests(unittest.TestCase):
    def test_round_trip_and_bad_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertEqual(home_ui.load_settings(path), {})
            home_ui.save_settings(path, home_ui.HomeSettings("naruto", 2, "Logitech C920"))
            self.assertEqual(home_ui.load_settings(path), {"mode": "naruto", "camera": "Logitech C920"})
            path.write_text("[1, 2")
            self.assertEqual(home_ui.load_settings(path), {})
            path.write_text(json.dumps([1, 2]))
            self.assertEqual(home_ui.load_settings(path), {})

    def test_camera_is_remembered_by_name(self):
        args = argparse.Namespace(camera=None, mode="dragonball")
        cameras = [(0, "Integrated Camera"), (2, "Logitech C920")]
        settings = app.initial_home_settings(args, {"mode": "naruto", "camera": "Logitech C920"}, cameras)
        self.assertEqual((settings.mode, settings.camera), ("naruto", 2))
        settings = app.initial_home_settings(args, {"mode": "bogus", "camera": "Gone"}, cameras)
        self.assertEqual((settings.mode, settings.camera), ("dragonball", 0))
        self.assertIsNone(app.initial_home_settings(args, {}, []).camera)

    def test_explicit_camera_wins(self):
        args = argparse.Namespace(camera=5, mode="normal")
        with patch.object(app, "camera_label", return_value="USB"):
            settings = app.initial_home_settings(args, {"camera": "Logitech C920"}, [(2, "Logitech C920")])
        self.assertEqual((settings.mode, settings.camera, settings.camera_label), ("normal", 5, "USB"))


class OsHelperTests(unittest.TestCase):
    def test_copy_uses_the_first_available_linux_tool(self):
        with patch.object(home_ui.shutil, "which", side_effect=lambda name: name == "xclip" and "/usr/bin/xclip"), \
                patch.object(home_ui.subprocess, "run") as run:
            self.assertTrue(home_ui.copy_text("hello", "Linux"))
        self.assertEqual(run.call_args.args[0], ["xclip", "-selection", "clipboard"])
        self.assertEqual(run.call_args.kwargs["input"], b"hello")

    def test_copy_without_tools_or_with_failures(self):
        with patch.object(home_ui.shutil, "which", return_value=None):
            self.assertFalse(home_ui.copy_text("hello", "Linux"))
        with patch.object(home_ui.subprocess, "run", side_effect=OSError("no clip")):
            self.assertFalse(home_ui.copy_text("hello", "Windows"))

    def test_copy_on_windows_and_macos(self):
        for system, command in (("Windows", ["clip"]), ("Darwin", ["pbcopy"])):
            with patch.object(home_ui.shutil, "which", return_value="/bin/tool"), \
                    patch.object(home_ui.subprocess, "run") as run:
                self.assertTrue(home_ui.copy_text("hi ü", system))
            self.assertEqual(run.call_args.args[0], command)
            self.assertEqual(run.call_args.kwargs["input"], b"hi ?")

    def test_open_folder_creates_it(self):
        with tempfile.TemporaryDirectory() as root, patch.object(home_ui.subprocess, "Popen") as popen:
            folder = Path(root) / "ssj_hair"
            self.assertTrue(home_ui.open_folder(folder, "Linux"))
            self.assertTrue(folder.is_dir())
        self.assertEqual(popen.call_args.args[0][0], "xdg-open")


class HairActionTests(unittest.TestCase):
    def test_status_and_check_without_pictures(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "HAIR_DIR", Path(folder)):
            self.assertIn("Not set up", app.hair_status())
            (Path(folder) / "photo_front.jpg").write_bytes(b"x")
            self.assertIn("Photos taken", app.hair_status())
            self.assertIn("No golden pictures", app.check_hair_pictures()[0])
            (Path(folder) / "ssj_front.png").write_bytes(b"x")
            self.assertIn("1 golden picture", app.hair_status())

    def test_check_reports_ready_views(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, "HAIR_DIR", Path(folder)), \
                patch.object(app.ssj_face, "load_hair_views",
                             side_effect=lambda path, detect, log: log("Hair imported from ssj_front.png.") or [1]):
            (Path(folder) / "ssj_front.png").write_bytes(b"x")
            (Path(folder) / "ssj_left.png").write_bytes(b"x")
            messages = app.check_hair_pictures()
        self.assertEqual(messages[0], "Hair imported from ssj_front.png.")
        self.assertIn("1 of 2 golden pictures ready", messages[-1])


if __name__ == "__main__":
    unittest.main()
