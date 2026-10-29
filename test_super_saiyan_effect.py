import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

import super_saiyan_effect as ssj
import vanish_cam as app
from test_video_output import run_loop
from vanish_sound import VanishSound


def fist(cx, cy, scale=1.0, open_hand=False):
    """A hand seen from the front at chest height; fingers curled unless open_hand (pixels)."""
    hand = np.zeros((21, 2), dtype=np.float32)
    hand[0] = (cx, cy + 40 * scale)
    hand[1:5] = [(cx - 20 * scale, cy + 25 * scale - 6 * i * scale) for i in range(4)]
    for base, dx, dy in ((5, -15, 0), (9, -5, -3), (13, 5, -3), (17, 15, 0)):
        mcp = np.array((cx + dx * scale, cy + dy * scale))
        if open_hand:
            steps = ((0, -20), (0, -35), (0, -48))
        else:
            steps = ((0, -12), (0, -6), (0, 8))  # Curled back towards the palm.
        hand[base] = mcp
        for offset, (sx, sy) in enumerate(steps, start=1):
            hand[base + offset] = mcp + np.array((sx, sy)) * scale
    return hand


def face(scale=1.0, dx=0.0, dy=0.0):
    points = np.zeros((478, 2), dtype=np.float32)
    points[ssj.NOSE] = (320, 150)
    points[ssj.CHIN] = (320, 230)
    points[ssj.FOREHEAD_TOP] = (320, 90)
    points[ssj.FACE_LEFT] = (270, 170)
    points[ssj.FACE_RIGHT] = (370, 170)
    return points * scale + (dx, dy)


def normalized(points, width=640, height=480):
    return [SimpleNamespace(x=x / width, y=y / height) for x, y in points]


class ChargePoseTests(unittest.TestCase):
    def test_two_fists_at_chest_height_charge(self):
        self.assertTrue(ssj.charge_pose([fist(200, 300), fist(440, 300)], face(), 640, 480))
        self.assertTrue(ssj.charging_from_landmarks(
            [normalized(fist(200, 300)), normalized(fist(440, 300))], [normalized(face())], 640, 480))

    def test_scale_and_position_invariance(self):
        for scale in (0.5, 1.0, 2.0):
            for shift in ((0, 0), (40, -30)):
                with self.subTest(scale=scale, shift=shift):
                    hands = [fist(200, 300) * scale + shift, fist(440, 300) * scale + shift]
                    self.assertTrue(ssj.charge_pose(hands, face(scale, *shift), int(640 * scale) + 80,
                                                    int(480 * scale) + 80))

    def test_other_poses_do_not_charge(self):
        cases = {
            "open hands": [fist(200, 300, open_hand=True), fist(440, 300, open_hand=True)],
            "one hand": [fist(200, 300)],
            "same side": [fist(200, 300), fist(240, 300)],
            "crossed to one side": [fist(420, 300), fist(460, 300)],
            "above the chin": [fist(200, 150), fist(440, 150)],
            "tiny hands": [fist(200, 300, scale=0.2), fist(440, 300, scale=0.2)],
            "one high one low": [fist(200, 300), fist(440, 420)],
        }
        for name, hands in cases.items():
            with self.subTest(name):
                self.assertFalse(ssj.charge_pose(hands, face(), 640, 480))

    def test_tension_counts_curled_fingers(self):
        self.assertEqual(ssj.hand_tension(fist(200, 300)), 4)
        self.assertEqual(ssj.hand_tension(fist(200, 300, open_hand=True)), 0)

    def test_teleport_wins_over_charge(self):
        recognizer = SimpleNamespace(
            last_teleport=True, last_size=(640, 480),
            last_hands=[normalized(fist(200, 300)), normalized(fist(440, 300))],
            last_faces=[normalized(face())],
        )
        self.assertFalse(app.power_active(recognizer))
        recognizer.last_teleport = False
        self.assertTrue(app.power_active(recognizer))


class HairTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.frame = np.full((120, 160, 3), 90, np.uint8)
        texture = rng.integers(10, 80, (30, 60)).astype(np.uint8)
        self.frame[10:40, 50:110] = np.repeat(texture[:, :, None], 3, axis=2)  # Dark textured hair.
        self.hair = np.zeros((120, 160), np.float32)
        self.hair[10:40, 50:110] = 1.0

    def test_recolor_is_golden_and_keeps_texture(self):
        output = ssj.recolor_hair(self.frame, self.hair, 1.0)
        hair = output[12:38, 52:108].reshape(-1, 3).astype(np.float32)
        blue, green, red = hair[:, 0].mean(), hair[:, 1].mean(), hair[:, 2].mean()
        self.assertGreater(red, blue + 40)
        self.assertGreater(green, blue + 20)
        hue = cv2.cvtColor(output[12:38, 52:108], cv2.COLOR_BGR2HSV)[:, :, 0]
        self.assertTrue(15 <= float(np.median(hue)) <= 35)
        before = cv2.cvtColor(self.frame[12:38, 52:108], cv2.COLOR_BGR2GRAY).ravel().astype(float)
        after = cv2.cvtColor(output[12:38, 52:108], cv2.COLOR_BGR2GRAY).ravel().astype(float)
        self.assertGreater(np.corrcoef(before, after)[0, 1], 0.8)

    def test_pixels_far_from_the_hair_are_untouched(self):
        output = ssj.recolor_hair(self.frame, self.hair, 1.0)
        np.testing.assert_array_equal(output[90:, :], self.frame[90:, :])
        self.assertIs(ssj.recolor_hair(self.frame, None, 1.0), self.frame)
        self.assertIs(ssj.recolor_hair(self.frame, self.hair, 0.0), self.frame)

    def test_head_box_stays_inside_the_frame(self):
        left, top, right, bottom = ssj.head_box(face(dy=-80), 640, 480)
        self.assertEqual(top, 0)
        self.assertTrue(0 <= left < right <= 640 and bottom <= 480)
        self.assertIsNone(ssj.head_box(face(scale=0.1), 640, 480))

    def test_tracker_uses_the_hair_class_and_holds_briefly_without_a_face(self):
        confidence = Mock()
        confidence.numpy_view.return_value = np.ones((256, 256, 1), np.float32)
        segmenter = Mock()
        segmenter.segment.return_value = SimpleNamespace(confidence_masks=[Mock(), confidence])
        tracker = ssj.HairTracker(segmenter)
        frame = np.zeros((480, 640, 3), np.uint8)
        mask = tracker.update(frame, face(), 1.0)
        self.assertGreater(mask[100, 320], 0.9)
        self.assertEqual(mask[400, 20], 0.0)
        tracker.update(frame, face(), 1.05)
        segmenter.segment.assert_called_once()  # Throttled to HAIR_INTERVAL.
        self.assertIsNotNone(tracker.update(frame, None, 1.2))
        self.assertIsNone(tracker.update(frame, None, 1.5))


class AuraTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((240, 320, 3), 60, np.uint8)
        self.mask = np.zeros((240, 320), np.float32)
        self.mask[80:240, 130:190] = 1.0
        self.aura = ssj.AuraRenderer()

    def test_no_intensity_no_change(self):
        np.testing.assert_array_equal(self.aura.render(self.frame, self.mask, 0.0, 1.0), self.frame)

    def test_glows_yellow_next_to_the_silhouette_and_rises(self):
        output = self.aura.render(self.frame, self.mask, 1.0, 1.0).astype(int)
        beside = output[150, 120]
        self.assertGreater(beside[2], 60 + 30)  # Red and green up: yellow.
        self.assertGreater(beside[1], 60 + 30)
        above = output[60, 160]
        self.assertGreater(int(above[1]), 60)  # The flames go above the head.
        np.testing.assert_array_equal(output[5, 5], self.frame[5, 5])
        np.testing.assert_array_equal(output[230, 5], self.frame[230, 5])

    def test_deterministic_for_the_same_time(self):
        first = self.aura.render(self.frame, self.mask, 1.0, 2.5)
        second = ssj.AuraRenderer().render(self.frame, self.mask, 1.0, 2.5)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first.dtype, np.uint8)
        self.assertEqual(first.shape, self.frame.shape)

    def test_fast_enough_for_live_video(self):
        frame = np.full((540, 960, 3), 60, np.uint8)
        mask = np.zeros((540, 960), np.float32)
        mask[150:540, 380:580] = 1.0
        aura = ssj.AuraRenderer()
        hair = np.zeros_like(mask)
        hair[150:200, 420:540] = 1.0
        levels = ssj.PowerLevels(aura=1.0, hair=1.0)
        ssj.render_super_saiyan(frame, mask, hair, levels, 0.0, aura)
        started = time.perf_counter()
        for index in range(10):
            ssj.render_super_saiyan(frame, mask, hair, levels, index / 30, aura)
        self.assertLess((time.perf_counter() - started) / 10, 0.04)


class PowerStateTests(unittest.TestCase):
    def test_full_timeline(self):
        power = ssj.PowerState()
        power.update(1.0, 1.0)
        self.assertEqual(power.phase, "charging")
        middle = power.levels(1.0 + ssj.CHARGE_SECONDS / 2)
        self.assertGreater(middle.aura, 0.2)
        self.assertGreater(middle.shake, 2.0)
        power.transform(2.5)
        self.assertTrue(power.transformed)
        self.assertGreater(power.levels(2.58).flash, 0.85)
        self.assertGreater(power.levels(2.6).radius, 1.5)
        power.update(2.5 + ssj.FLASH_SECONDS + 0.01, None)
        self.assertEqual(power.phase, "super")
        self.assertEqual(power.levels(4.0), ssj.PowerLevels(aura=1.0, hair=1.0))
        power.power_down(5.0)
        self.assertLess(power.levels(5.3).aura, 1.0)
        power.update(5.0 + ssj.POWER_DOWN_SECONDS + 0.01, None)
        self.assertEqual(power.phase, "off")
        self.assertEqual(power.levels(6.0), ssj.PowerLevels())

    def test_letting_go_while_charging_cancels(self):
        power = ssj.PowerState()
        power.update(1.0, 1.0)
        power.update(1.4, None)
        self.assertEqual(power.phase, "off")


class SoundTests(unittest.TestCase):
    def read(self, writer):
        with tempfile.TemporaryDirectory() as folder:
            path = writer(Path(folder) / "sound.wav")
            with wave.open(str(path)) as audio:
                channels = audio.getnchannels()
                seconds = audio.getnframes() / audio.getframerate()
                samples = np.frombuffer(audio.readframes(audio.getnframes()), "<i2").reshape(-1, 2)
        return channels, seconds, samples[:, 0].astype(int)

    def test_charge_and_transform(self):
        for writer, length in ((ssj.write_charge_sound, ssj.CHARGE_SECONDS + 0.1),
                               (ssj.write_transform_sound, 1.2)):
            with self.subTest(writer.__name__):
                channels, seconds, samples = self.read(writer)
                self.assertEqual(channels, 2)
                self.assertAlmostEqual(seconds, length, places=2)
                self.assertGreater(np.abs(samples).max(), 20000)

    def test_charge_grows(self):
        _, _, samples = self.read(ssj.write_charge_sound)
        quarter = len(samples) // 4
        self.assertGreater(np.abs(samples[-quarter:]).mean(), np.abs(samples[:quarter]).mean() * 1.5)

    def test_hum_loops_without_a_click(self):
        _, seconds, samples = self.read(ssj.write_aura_hum)
        self.assertAlmostEqual(seconds, 2.0, places=2)
        typical_step = np.abs(np.diff(samples)).mean()
        self.assertLess(abs(samples[0] - samples[-1]), typical_step * 6 + 50)

    def test_vanish_sound_loops_and_stops(self):
        sound = Mock()
        mixer = Mock()
        mixer.get_init.return_value = None
        mixer.Sound.return_value = sound
        with tempfile.NamedTemporaryFile(suffix=".wav") as file, \
                patch.dict("sys.modules", pygame=SimpleNamespace(mixer=mixer)):
            player = VanishSound(Path(file.name))
            player.play(loops=-1, fade_ms=400)
            sound.play.assert_called_with(loops=-1, fade_ms=400)
            player.stop(500)
            sound.fadeout.assert_called_once_with(500)
            player.stop()
            sound.stop.assert_called()
            player.set_volume(2.0)
            sound.set_volume.assert_called_once_with(1.0)
            player.close()
            mixer.quit.assert_called_once()

    def test_vanish_sound_uses_the_requested_audio_device(self):
        mixer = Mock()
        mixer.get_init.return_value = None
        with tempfile.NamedTemporaryFile(suffix=".wav") as file, \
                patch.dict("sys.modules", pygame=SimpleNamespace(mixer=mixer)):
            player = VanishSound(Path(file.name), device="BlackHole 2ch")
            mixer.init.assert_called_once_with(
                frequency=44100, size=-16, channels=2, buffer=256, devicename="BlackHole 2ch")
            player.close()

    def test_vanish_sound_does_not_reinitialize_a_shared_mixer(self):
        mixer = Mock()
        mixer.get_init.return_value = (44100, -16, 2)
        with tempfile.NamedTemporaryFile(suffix=".wav") as file, \
                patch.dict("sys.modules", pygame=SimpleNamespace(mixer=mixer)):
            player = VanishSound(Path(file.name), device="BlackHole 2ch")
            mixer.init.assert_not_called()
            player.close()
            mixer.quit.assert_not_called()


def person_in_middle():
    mask = np.zeros((24, 40), np.float32)
    mask[6:24, 15:25] = 1.0
    return mask


class SuperSaiyanLoopTests(unittest.TestCase):
    def test_charge_transform_and_power_down_with_the_same_pose(self):
        held = lambda t: 5.0 <= t < 6.8 or 8.0 <= t < 9.7
        frames, shown, _, sound, printed = run_loop(
            mode="dragonball", power=held, mask=person_in_middle(), seconds=11.0)
        charge, transform, hum = sound.others
        np.testing.assert_array_equal(shown[45], frames[45])  # Normal.
        self.assertTrue(np.any(shown[57] != frames[57]))  # Charging: shake and small aura.
        self.assertTrue(np.any(shown[80] != frames[80]))  # Super Saiyan.
        np.testing.assert_array_equal(shown[105], frames[105])  # Back to normal.
        charge.play.assert_called_once()
        transform.play.assert_called_once()
        hum.play.assert_called_once_with(loops=-1, fade_ms=400)
        hum.stop.assert_any_call(500)
        self.assertTrue(any("Super Saiyan!" in line for line in printed))
        self.assertTrue(any("Back to normal" in line for line in printed))

    def test_a_short_charge_does_not_transform(self):
        frames, shown, _, sound, _ = run_loop(
            mode="dragonball", power=lambda t: 5.0 <= t < 5.6, mask=person_in_middle(), seconds=8.0)
        charge, transform, _ = sound.others
        charge.play.assert_called_once()
        charge.stop.assert_called()
        transform.play.assert_not_called()
        for index in range(62, len(shown)):
            np.testing.assert_array_equal(shown[index], frames[index])

    def test_key_s_toggles(self):
        frames, shown, _, sound, _ = run_loop(
            mode="dragonball", keys={50: ord("s"), 70: ord("s")}, mask=person_in_middle(), seconds=9.0)
        _, transform, hum = sound.others
        self.assertTrue(np.any(shown[60] != frames[60]))
        np.testing.assert_array_equal(shown[80], frames[80])
        transform.play.assert_called_once()
        hum.stop.assert_any_call(500)

    def test_teleport_while_transformed_cuts_and_resumes_the_hum(self):
        teleport = lambda t: 6.0 <= t < 7.3 or 8.5 <= t < 9.8
        frames, shown, _, sound, _ = run_loop(
            mode="dragonball", gesture=teleport, keys={50: ord("s")}, mask=person_in_middle(), seconds=11.5)
        _, _, hum = sound.others
        np.testing.assert_array_equal(shown[80], frames[0])  # Gone: the empty room.
        hum.stop.assert_any_call(300)
        self.assertEqual(hum.play.call_count, 2)  # On transform and again on return.
        self.assertTrue(np.any(shown[112] != frames[112]))  # Back, still Super Saiyan.

    def test_other_modes_have_no_super_saiyan(self):
        _, _, _, sound, _ = run_loop(mode="naruto", power=lambda t: True, seconds=6.0)
        self.assertEqual(sound.others, [])


if __name__ == "__main__":
    unittest.main()
