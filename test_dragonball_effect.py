import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

import dragonball_effect as db
from test_video_output import run_loop


def two_fingers_up(dx=0.0, dy=0.0, spread=0.0, open_hand=False):
    """Index and middle straight and together; ring and pinky curled (pixels)."""
    hand = np.array([
        (100, 300),                                              # Wrist.
        (80, 280), (72, 262), (70, 248), (72, 238),              # Thumb.
        (90, 240), (88, 210), (87, 190), (86 - spread, 170),     # Index.
        (100, 238), (100, 206), (100, 186), (100 + spread, 166),  # Middle.
        (110, 242), (115, 225), (112, 240), (108, 250),          # Ring (curled).
        (120, 248), (124, 235), (121, 245), (117, 252),          # Pinky (curled).
    ], dtype=np.float32)
    if open_hand:
        hand[13:17] = [(110, 242), (112, 212), (113, 192), (114, 174)]
        hand[17:21] = [(120, 248), (124, 224), (126, 208), (128, 194)]
    return hand + (dx, dy)


def face_points():
    face = np.zeros((478, 2), dtype=np.float32)
    face[db.FOREHEAD_TOP] = (93, 140)
    face[db.BROWS] = (93, 200)
    face[db.FOREHEAD_CENTER] = (93, 170)
    face[db.FACE_LEFT] = (40, 200)
    face[db.FACE_RIGHT] = (146, 200)
    return face


def normalized(points, width=640, height=480):
    return [SimpleNamespace(x=x / width, y=y / height) for x, y in points]


class GestureTests(unittest.TestCase):
    def test_two_fingers_together_on_the_forehead(self):
        hand = two_fingers_up()
        tip = db.two_finger_tip(hand)
        self.assertIsNotNone(tip)
        self.assertTrue(db.touching_forehead(tip, face_points()))
        self.assertTrue(db.instant_transmission([normalized(hand)], [normalized(face_points())], 640, 480))

    def test_hand_away_from_the_forehead(self):
        hand = two_fingers_up(dx=250)
        self.assertFalse(db.instant_transmission([normalized(hand)], [normalized(face_points())], 640, 480))

    def test_v_sign_or_open_hand_do_not_count(self):
        self.assertIsNone(db.two_finger_tip(two_fingers_up(spread=30)))
        self.assertIsNone(db.two_finger_tip(two_fingers_up(open_hand=True)))

    def test_needs_a_face_and_a_hand(self):
        hand = [normalized(two_fingers_up())]
        self.assertFalse(db.instant_transmission(hand, [], 640, 480))
        self.assertFalse(db.instant_transmission([], [normalized(face_points())], 640, 480))

    def test_detector_reports_what_it_saw(self):
        hands, faces = Mock(), Mock()
        hands.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[normalized(two_fingers_up())])
        faces.detect_for_video.return_value = SimpleNamespace(face_landmarks=[normalized(face_points())])
        detector = db.InstantTransmissionDetector(hands, faces)
        self.assertTrue(detector.detect(SimpleNamespace(width=640, height=480), 100))
        self.assertEqual(detector.last_hand_count, 1)
        self.assertTrue(detector.last_face_found)
        detector.close()
        hands.close.assert_called_once()
        faces.close.assert_called_once()


class TeleportEffectTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((120, 160, 3), 200, np.uint8)
        self.background = np.full_like(self.frame, 40)
        self.mask = np.zeros((120, 160), np.float32)
        self.mask[20:110, 60:100] = 1.0

    def test_person_glows_with_lines_then_disappears(self):
        early = db.render_teleport(self.frame, self.background, self.mask, 0.05)
        self.assertTrue(np.any(early[60, 60:100] != self.background[60, 60:100]))
        np.testing.assert_array_equal(early[5, 5], self.background[5, 5])
        after = db.render_teleport(self.frame, self.background, self.mask, db.VANISH_AT + 0.1)
        # The person is gone, but lines linger on the silhouette.
        self.assertTrue(np.any(after != self.background))
        self.assertLess(int(after[60, 60:100].min()), 200)
        done = db.render_teleport(self.frame, self.background, self.mask, db.EFFECT_SECONDS)
        np.testing.assert_array_equal(done, self.background)

    def test_timing(self):
        self.assertEqual(db.person_alpha(0.1), 1.0)
        self.assertEqual(db.person_alpha(db.VANISH_AT), 0.0)
        self.assertEqual(db.lines_intensity(0.0), 0.0)
        self.assertEqual(db.lines_intensity(db.VANISH_AT - 0.01), 1.0)
        self.assertEqual(db.lines_intensity(db.EFFECT_SECONDS), 0.0)

    def test_generated_sound_is_a_short_stereo_wav(self):
        with tempfile.TemporaryDirectory() as folder:
            path = db.write_teleport_sound(Path(folder) / "teleport.wav")
            with wave.open(str(path)) as audio:
                self.assertEqual(audio.getnchannels(), 2)
                seconds = audio.getnframes() / audio.getframerate()
                samples = np.frombuffer(audio.readframes(audio.getnframes()), "<i2")
        self.assertAlmostEqual(seconds, 0.5, places=2)
        self.assertGreater(int(np.abs(samples).max()), 20000)


class DragonBallLoopTests(unittest.TestCase):
    def test_teleports_away_and_back_with_the_same_gesture(self):
        # Dragon Ball needs the pose for a full second.
        held = lambda t: 5.0 <= t < 6.3 or 8.0 <= t < 9.3
        frames, shown, _, sound, printed = run_loop(mode="dragonball", gesture=held, seconds=11.0)
        np.testing.assert_array_equal(shown[55], frames[55])  # Still holding.
        mid = shown[63]
        self.assertTrue(np.any(mid != frames[63]) and np.any(mid != frames[0]))
        np.testing.assert_array_equal(shown[75], frames[0])  # Gone: the empty room.
        np.testing.assert_array_equal(shown[108], frames[108])  # Back.
        self.assertEqual(sound.play.call_count, 2)
        self.assertTrue(any("Keep your fingers on your forehead" in line for line in printed))

    def test_a_short_touch_does_not_teleport(self):
        frames, shown, _, sound, _ = run_loop(mode="dragonball", gesture=lambda t: 5.0 <= t < 5.6,
                                              seconds=8.0)
        for index in range(45, len(shown)):
            np.testing.assert_array_equal(shown[index], frames[index])
        sound.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
