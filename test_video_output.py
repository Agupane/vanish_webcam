import argparse
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

import vanish_cam as app


def arguments(**overrides):
    values = dict(
        camera=0, width=960, height=540, fps=30.0, fullscreen=False,
        no_mirror=True, mirror_output=False, virtual_camera=None, virtual_backend=None,
        virtual_device=None, gesture_debug=False, mode="normal", menu=False,
        audio_device=None,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


EMPTY_ROOM, PERSON = 50, 170


def run_loop(mode="normal", seconds=13.0, step=0.1, gesture=lambda t: False,
             person=lambda t: False, keys=None, send_error=None, power=lambda t: False,
             mask=None, **overrides):
    """Run the real loop with a fake clock that advances one step per frame.

    Before 4 s the camera sees an empty room; afterwards someone is in frame.
    Returns (live frames, preview frames, virtual camera, sound, printed lines).
    `sound` is the first VanishSound created (teleport/Naruto); the Super Saiyan
    ones (charge, transform, hum) are in `sound.others`.
    """
    clock = {"t": 0.0, "i": -1}
    count = int(round(seconds / step))
    ramp = np.arange(40, dtype=np.uint8)[None, :, None]  # Asymmetric, to see mirroring.
    frames = [np.repeat(np.full((24, 40, 1), EMPTY_ROOM if i * step < 4.0 else PERSON, np.uint8) + ramp,
                        3, axis=2) for i in range(count)]

    def read():
        clock["i"] += 1
        clock["t"] = clock["i"] * step
        return True, frames[clock["i"]]

    def wait_key(_):
        if clock["i"] >= count - 1:
            return ord("q")
        return (keys or {}).get(clock["i"], 0)

    capture = Mock()
    capture.read.side_effect = read
    segmenter, recognizer = Mock(), Mock()
    sounds = []

    def new_sound(*args, **kwargs):
        sounds.append(Mock())
        sounds[-1].created_with = (args, kwargs)
        return sounds[-1]

    camera = Mock(width=40, height=24)
    camera.send.side_effect = send_error
    displayed, printed = [], []
    person_mask = np.ones((24, 40), np.float32) if mask is None else mask
    with ExitStack() as mocks:
        mocks.enter_context(patch.object(app, "parse_args", return_value=arguments(mode=mode, **overrides)))
        mocks.enter_context(patch.object(app, "download_models"))
        mocks.enter_context(patch.object(app, "open_camera", return_value=capture))
        mocks.enter_context(patch.object(app, "create_tasks", return_value=(segmenter, recognizer)))
        mocks.enter_context(patch.object(app, "VanishSound", side_effect=new_sound))
        mocks.enter_context(patch.object(app, "teleport_sound_path", return_value="teleport.wav"))
        mocks.enter_context(patch.object(app, "ssj_sound_paths", return_value=("c.wav", "t.wav", "h.wav")))
        mocks.enter_context(patch.object(app, "create_hair_tracker", return_value=None))
        mocks.enter_context(patch.object(app, "hair_mask", return_value=None))
        mocks.enter_context(patch.object(app, "power_active", side_effect=lambda *a: power(clock["t"])))
        opening = mocks.enter_context(patch.object(app, "open_virtual_camera", return_value=camera))
        mocks.enter_context(patch.object(app, "person_mask", return_value=person_mask))
        mocks.enter_context(patch.object(app, "person_in_frame", side_effect=lambda *a: person(clock["t"])))
        mocks.enter_context(patch.object(app, "gesture_active", side_effect=lambda *a: gesture(clock["t"])))
        mocks.enter_context(patch.object(app.time, "perf_counter", side_effect=lambda: clock["t"]))
        mocks.enter_context(patch.object(app.cv2, "namedWindow"))
        mocks.enter_context(patch.object(app.cv2, "resizeWindow"))
        destroy = mocks.enter_context(patch.object(app.cv2, "destroyAllWindows"))
        mocks.enter_context(patch.object(app.cv2, "imshow", side_effect=lambda name, frame: displayed.append(frame.copy())))
        mocks.enter_context(patch.object(app.cv2, "waitKey", side_effect=wait_key))
        mocks.enter_context(patch.object(app.cv2, "putText", side_effect=AssertionError("Overlay forbidden")))
        mocks.enter_context(patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))))
        if send_error is None:
            assert app.run() == 0
        else:
            try:
                app.run()
            except RuntimeError as error:
                assert "send failed" in str(error)
            else:
                raise AssertionError("send error not raised")
        opening.assert_called_once()
        assert opening.call_args.args[1:] == (40, 24)
        capture.release.assert_called_once()
        segmenter.close.assert_called_once()
        recognizer.close.assert_called_once()
        camera.close.assert_called_once()
        destroy.assert_called_once()
    sound = sounds[0] if sounds else Mock()
    sound.others = sounds[1:]
    return frames, displayed, camera, sound, printed


class VirtualCameraTests(unittest.TestCase):
    def test_bgr_format_and_actual_frame_dimensions(self):
        camera = Mock(device="OBS Virtual Camera")
        module = SimpleNamespace(Camera=Mock(return_value=camera), PixelFormat=SimpleNamespace(BGR="BGR"))
        with patch.dict("sys.modules", pyvirtualcam=module):
            self.assertIs(app.open_virtual_camera(arguments(), 640, 480), camera)
        module.Camera.assert_called_once_with(
            width=640, height=480, fps=30.0, fmt="BGR", backend=None, device=None,
        )

    def test_unavailable_driver_auto_falls_back_but_explicit_mode_fails(self):
        module = SimpleNamespace(Camera=Mock(side_effect=RuntimeError("driver missing")),
                                 PixelFormat=SimpleNamespace(BGR="BGR"))
        with patch.dict("sys.modules", pyvirtualcam=module), patch("builtins.print"):
            self.assertIsNone(app.open_virtual_camera(arguments(), 640, 480))
            for options in (dict(virtual_camera=True), dict(virtual_backend="obs")):
                with self.assertRaisesRegex(RuntimeError, "driver missing"):
                    app.open_virtual_camera(arguments(**options), 640, 480)

    def test_disabled_camera_does_not_open_device(self):
        module = SimpleNamespace(Camera=Mock())
        with patch.dict("sys.modules", pyvirtualcam=module):
            self.assertIsNone(app.open_virtual_camera(arguments(virtual_camera=False), 640, 480))
        module.Camera.assert_not_called()

    def test_send_preserves_colors_and_handles_noncontiguous_frames(self):
        camera = Mock(width=40, height=24)
        frame = np.zeros((24, 40, 3), np.uint8)
        frame[:] = (10, 70, 200)  # BGR: do not swap red and blue.
        app.send_virtual_frame(camera, frame[:, ::-1])
        sent = camera.send.call_args.args[0]
        self.assertTrue(sent.flags.c_contiguous)
        np.testing.assert_array_equal(sent, frame)

    def test_send_resizes_if_input_resolution_changes(self):
        camera = Mock(width=40, height=24)
        app.send_virtual_frame(camera, np.full((48, 80, 3), 42, np.uint8))
        sent = camera.send.call_args.args[0]
        self.assertEqual(sent.shape, (24, 40, 3))
        self.assertTrue((sent == 42).all())


class VideoLoopTests(unittest.TestCase):
    @staticmethod
    def at(seconds, step=0.1):
        return int(round(seconds / step))

    def test_held_v_vanishes_and_held_again_reappears(self):
        held = lambda t: 5.0 <= t < 5.7 or 10.0 <= t < 10.7
        frames, shown, camera, _, _ = run_loop(gesture=held)
        background = frames[0]
        for sent, preview in zip(camera.send.call_args_list, shown):
            np.testing.assert_array_equal(sent.args[0], preview)
        np.testing.assert_array_equal(shown[self.at(2.0)], frames[self.at(2.0)])  # Calibrating: live.
        np.testing.assert_array_equal(shown[self.at(5.1)], frames[self.at(5.1)])  # Holding, not yet.
        mid = shown[self.at(7.0)]
        self.assertTrue(np.any(mid != frames[self.at(7.0)]) and np.any(mid != background))
        np.testing.assert_array_equal(shown[self.at(9.5)], background)  # Gone: only the room.
        mid = shown[self.at(11.3)]
        self.assertTrue(np.any(mid != frames[self.at(11.3)]) and np.any(mid != background))
        np.testing.assert_array_equal(shown[self.at(12.8)], frames[self.at(12.8)])  # Back.

    def test_a_brief_v_does_not_vanish(self):
        frames, shown, _, _, _ = run_loop(gesture=lambda t: 5.0 <= t < 5.15, seconds=8.0)
        for index in range(self.at(4.2), len(shown)):
            np.testing.assert_array_equal(shown[index], frames[index])

    def test_keys_v_and_r_still_work(self):
        frames, shown, _, _, _ = run_loop(keys={self.at(5.0): ord("v"), self.at(9.5): ord("r")})
        np.testing.assert_array_equal(shown[self.at(9.2)], frames[0])
        np.testing.assert_array_equal(shown[self.at(12.8)], frames[self.at(12.8)])

    def test_calibration_waits_while_someone_is_in_frame(self):
        frames, shown, _, _, printed = run_loop(
            person=lambda t: t < 3.0, seconds=8.0, gesture=lambda t: False)
        self.assertTrue(any("Someone is still in the frame" in line for line in printed))
        self.assertTrue(any("Background ready" in line for line in printed))

    def test_virtual_camera_is_not_mirrored_but_preview_is(self):
        _, shown, camera, _, _ = run_loop(no_mirror=False, seconds=5.0)
        for sent, preview in zip(camera.send.call_args_list, shown):
            np.testing.assert_array_equal(sent.args[0], preview[:, ::-1])

    def test_audio_device_is_forwarded_to_every_sound(self):
        _, _, _, sound, _ = run_loop(mode="dragonball", seconds=0.2, audio_device="Fixture output")
        for player in (sound, *sound.others):
            self.assertEqual(player.created_with[1]["device"], "Fixture output")

    def test_all_devices_close_on_send_error(self):
        run_loop(send_error=RuntimeError("send failed"), seconds=1.0)


if __name__ == "__main__":
    unittest.main()
