import tempfile
import time
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

import dragonball_effect
import super_saiyan_effect as ssj
import vanish_cam as app
from test_video_output import run_loop
from vanish_sound import VanishSound


def fist(cx, cy, scale=1.0, open_hand=False):
    """A fist seen from the front; fingers curled unless open_hand (pixels)."""
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

    def test_fists_in_front_of_the_face_charge(self):
        for y in (90, 150, 200, 260):
            with self.subTest(y=y):
                self.assertTrue(ssj.charge_pose([fist(200, y), fist(440, y)], face(), 640, 480))

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
            "below the face": [fist(200, 420), fist(440, 420)],
            "above the head": [fist(200, 20), fist(440, 20)],
            "too far to the sides": [fist(80, 200), fist(560, 200)],
            "tiny hands": [fist(200, 300, scale=0.2), fist(440, 300, scale=0.2)],
            "one high one low": [fist(200, 300), fist(440, 420)],
        }
        for name, hands in cases.items():
            with self.subTest(name):
                self.assertFalse(ssj.charge_pose(hands, face(), 640, 480))

    def test_tension_counts_curled_fingers(self):
        self.assertEqual(ssj.hand_tension(fist(200, 300)), 4)
        self.assertEqual(ssj.hand_tension(fist(200, 300, open_hand=True)), 0)

    def test_charge_uses_a_recent_face_when_the_fists_hide_it(self):
        recognizer = SimpleNamespace(
            last_teleport=False,
            last_hands=[normalized(fist(200, 200)), normalized(fist(440, 200))],
            last_faces=[],
            last_size=(640, 480),
            recent_faces=lambda timestamp_ms: [normalized(face())],
        )
        self.assertTrue(app.power_active(recognizer, 100))

    def test_detector_remembers_the_face_for_a_moment(self):
        hands = Mock()
        hands.detect_for_video.return_value = SimpleNamespace(hand_landmarks=[])
        faces = Mock()
        faces.detect_for_video.return_value = SimpleNamespace(face_landmarks=[normalized(face())])
        detector = dragonball_effect.InstantTransmissionDetector(hands, faces)
        image = SimpleNamespace(width=640, height=480)
        detector.detect(image, 0)
        faces.detect_for_video.return_value = SimpleNamespace(face_landmarks=[])
        detector.detect(image, 100)
        self.assertEqual(detector.last_faces, [])
        self.assertTrue(detector.recent_faces(100))
        self.assertFalse(detector.recent_faces(1000))

    def test_teleport_wins_over_charge(self):
        recognizer = SimpleNamespace(
            last_teleport=True, last_size=(640, 480),
            last_hands=[normalized(fist(200, 300)), normalized(fist(440, 300))],
            last_faces=[normalized(face())],
        )
        self.assertFalse(app.power_active(recognizer))
        recognizer.last_teleport = False
        self.assertTrue(app.power_active(recognizer))


class AuraTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.full((240, 320, 3), 60, np.uint8)
        self.mask = np.zeros((240, 320), np.float32)
        self.mask[80:240, 130:190] = 1.0
        self.aura = ssj.AuraRenderer()

    def test_no_intensity_no_change(self):
        np.testing.assert_array_equal(self.aura.render(self.frame, self.mask, 0.0, 1.0), self.frame)

    def test_does_not_paint_the_person(self):
        output = self.aura.render(self.frame, self.mask, 1.0, 1.0)
        np.testing.assert_array_equal(output[200, 160], self.frame[200, 160])
        np.testing.assert_array_equal(output[220, 150], self.frame[220, 150])

    def test_rim_light_only_along_the_inside_edge(self):
        output = self.aura.render(self.frame, self.mask, 1.0, 1.0).astype(int)
        edge = output[90, 133]  # Just inside the left edge, near the top.
        self.assertGreater(edge[2], 60 + 15)  # Warmer: more red than blue.
        self.assertGreater(edge[2], edge[0])
        np.testing.assert_array_equal(output[150, 160], self.frame[150, 160])  # Deeper inside: untouched.

    def test_glows_yellow_next_to_the_silhouette_and_rises(self):
        output = self.aura.render(self.frame, self.mask, 1.0, 1.0).astype(int)
        beside = output[150, 124]
        self.assertGreater(beside[2], 60 + 30)  # Red and green up: yellow.
        self.assertGreater(beside[1], 60 + 30)
        self.assertGreater(beside[2], beside[0] + 30)
        above = output[60, 160]
        self.assertGreater(int(above[1]), 60)  # The flames go above the head.

    def test_surroundings_darken_with_the_power(self):
        far = (5, 5)
        full = self.aura.render(self.frame, self.mask, 1.0, 1.0).astype(int)
        half = ssj.AuraRenderer().render(self.frame, self.mask, 0.5, 1.0).astype(int)
        self.assertLess(full[far].max(), 60 * (1 - ssj.DARKEN) + 2)
        self.assertGreater(half[far].min(), full[far].max())
        self.assertLess(half[far].max(), 60)
        np.testing.assert_array_equal(full[far][0], full[far][2])  # Darker, not tinted.

    def test_light_wall_still_shows_a_yellow_aura(self):
        frame = np.full((240, 320, 3), 215, np.uint8)
        output = ssj.AuraRenderer().render(frame, self.mask, 1.0, 1.0).astype(int)
        beside = output[150, 124]
        self.assertGreater(beside[2] - beside[0], 60)  # Clearly yellow, not washed out to white.

    def test_not_cut_by_its_crop(self):
        frame = np.full((540, 960, 3), 60, np.uint8)
        mask = np.zeros((540, 960), np.float32)
        mask[450:540, 430:530] = 1.0  # Low enough that the crop does not reach the top of the frame.
        aura = ssj.AuraRenderer()
        output = aura.render(frame, mask, 1.0, 0.0, radius_scale=2.5).astype(int)
        geometry = aura.geometry(frame, mask)
        rows, cols = geometry.area
        darkened = int(round(60 * (1 - ssj.DARKEN)))
        # Just outside the crop only the darkening is left; just inside the border the aura has faded to almost nothing.
        for column in (cols.start - 1, cols.stop):
            np.testing.assert_array_equal(output[rows.start:rows.stop, column], darkened)
        for column in (cols.start, cols.stop - 1):
            self.assertLessEqual(np.abs(output[rows.start:rows.stop, column] - darkened).max(), 2)
        self.assertLessEqual(np.abs(output[rows.start, cols.start:cols.stop] - darkened).max(), 2)

    def test_geometry_is_cached_per_mask(self):
        aura = ssj.AuraRenderer()
        for index in range(5):
            aura.render(self.frame, self.mask, 1.0, index / 30)
        self.assertEqual(aura.geometry_updates, 1)
        aura.render(self.frame, self.mask.copy(), 1.0, 0.2)
        self.assertEqual(aura.geometry_updates, 2)
        first = aura.render(self.frame, self.mask, 1.0, 0.1)
        second = aura.render(self.frame, self.mask, 1.0, 0.4)
        self.assertTrue(np.any(first != second))  # The flames move between frames with the same mask.

    def test_deterministic_for_the_same_time(self):
        first = self.aura.render(self.frame, self.mask, 1.0, 2.5)
        second = ssj.AuraRenderer().render(self.frame, self.mask, 1.0, 2.5)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(first.dtype, np.uint8)
        self.assertEqual(first.shape, self.frame.shape)

    def test_fast_enough_for_live_video(self):
        frame = np.full((540, 960, 3), 200, np.uint8)
        frame[150:540, 380:580] = (200, 150, 60)
        mask = np.zeros((540, 960), np.float32)
        mask[150:540, 380:580] = 1.0
        head = ((480, 230), (70, 90), 0.0)
        aura = ssj.AuraRenderer()
        levels = ssj.PowerLevels(aura=1.0)
        ssj.render_super_saiyan(frame, mask, levels, 0.0, aura, head)
        samples = []
        current = mask
        for _ in range(3):
            started = time.perf_counter()
            for index in range(15):
                # A new mask every third frame, like the 10 Hz mask under a 30 FPS output.
                if index % 3 == 0:
                    current = mask.copy()
                ssj.render_super_saiyan(frame, current, levels, index / 30, aura, head)
            samples.append((time.perf_counter() - started) / 15)
        # ~5.5 ms on claude-bcn (main took 5.9 ms there); CI runners are slower.
        self.assertLess(min(samples), 0.02)


def chair_scene():
    """A high-back chair behind a person with dark hair; the segmenter takes the chair too."""
    height, width = 270, 480
    chair = np.zeros((height, width), np.uint8)
    cv2.ellipse(chair, (240, 160), (90, 120), 0, 0, 360, 1, -1)
    person = np.zeros((height, width), np.uint8)
    cv2.ellipse(person, (240, 120), (38, 48), 0, 0, 360, 1, -1)  # Head with dark hair.
    cv2.rectangle(person, (130, 190), (350, 270), 1, -1)  # Shoulders and torso.
    cv2.rectangle(person, (225, 160), (255, 195), 1, -1)  # Neck.
    frame = np.full((height, width, 3), 210, np.uint8)
    frame[chair > 0] = 35
    frame[person > 0] = (200, 160, 70)  # Blue shirt.
    cv2.ellipse(frame, (240, 128), (30, 38), 0, 0, 360, (120, 150, 200), -1)  # Face.
    cv2.ellipse(frame, (240, 95), (36, 22), 0, 180, 360, (30, 30, 32), -1)  # Hair, as dark as the chair.
    segmenter = np.maximum(person, chair).astype(np.float32)
    head = ((240, 112), (36, 50), 0.0)
    return frame, segmenter, head


class SilhouetteTests(unittest.TestCase):
    def test_chair_around_the_head_is_removed_but_the_dark_hair_stays(self):
        _, segmenter, head = chair_scene()
        refined = ssj.refine_person_mask(segmenter, head)
        self.assertLess(refined[100, 180], 0.1)  # Chair beside the head.
        self.assertLess(refined[50, 240], 0.1)  # Chair above the head.
        self.assertGreater(refined[80, 240], 0.9)  # Dark hair in front of the dark chair.
        self.assertGreater(refined[130, 240], 0.9)  # Face.

    def test_body_below_the_eyes_is_never_cut(self):
        # A close webcam sees the shoulders above the chin, and a black hoodie in front of a black chair has no
        # edge: the body is kept as the segmenter sees it, so the aura never paints on it.
        _, segmenter, head = chair_scene()
        refined = ssj.refine_person_mask(segmenter, head)
        self.assertGreater(refined[190:, 130:351].min(), 0.9)  # Torso and shoulders.
        self.assertGreater(refined[160:190, 225:256].min(), 0.9)  # Neck.
        close = segmenter.copy()
        cv2.ellipse(close, (240, 270), (110, 130), 0, 180, 360, 1.0, -1)  # Shoulders up to row 140.
        refined = ssj.refine_person_mask(close, head)
        self.assertGreater(refined[150:, 160:321].min(), 0.9)

    def test_chair_just_below_the_eyes_is_cut_along_a_slope_not_a_shelf(self):
        _, segmenter, head = chair_scene()
        refined = ssj.refine_person_mask(segmenter, head)
        self.assertLess(refined[122, 335], 0.05)  # Chair beside the face, just under the eye line.
        self.assertGreater(refined[200, 325], 0.9)  # Further down the same column is body width.

    def test_unchanged_without_a_face(self):
        _, segmenter, _ = chair_scene()
        self.assertIs(ssj.refine_person_mask(segmenter, None), segmenter)

    def test_tilted_head_tilts_the_line(self):
        _, segmenter, _ = chair_scene()
        tilted = ssj.refine_person_mask(segmenter, ((240, 112), (36, 50), 30.0))
        # Top of the head leaning right: the eye line rises on the left, so at the same row the chair
        # is still body-level on the left and already above the eyes on the right.
        self.assertGreater(tilted[118, 180], 0.9)
        self.assertLess(tilted[118, 300], 0.1)

    def test_head_ellipse_covers_the_hair_above_the_face(self):
        width, height = 640, 480
        center, axes, angle = ssj.head_ellipse([normalized(face(), width, height)], width, height)
        self.assertEqual(center[0], 320)
        self.assertLess(center[1], (90 + 230) / 2)  # Shifted up towards the hair.
        self.assertLess(center[1] - axes[1], 90 - 30)  # Reaches above the forehead landmark.
        self.assertAlmostEqual(angle, 0.0, places=3)
        self.assertIsNone(ssj.head_ellipse([], width, height))

    def test_aura_uses_the_refined_silhouette(self):
        frame, segmenter, head = chair_scene()
        with_head = ssj.AuraRenderer().render(frame, segmenter, 1.0, 0.5, head=head)
        without = ssj.AuraRenderer().render(frame, segmenter, 1.0, 0.5)
        # Over the chair, beside the head: lit by the aura only once the chair is out of the silhouette.
        self.assertGreater(int(with_head[100, 192, 2]) - int(without[100, 192, 2]), 30)

    def test_raised_fists_are_never_covered_by_the_aura(self):
        # The charge pose that powers down puts the fists above the eye line, beside the head.
        frame, segmenter, head = chair_scene()
        frame[60:140, 300:360] = (120, 150, 200)
        segmenter[60:140, 300:360] = 1.0
        hands = [normalized(fist(330, 85), 480, 270)]
        levels = ssj.PowerLevels(aura=1.0)
        covered = ssj.render_super_saiyan(frame, segmenter, levels, 0.5, ssj.AuraRenderer(), head)
        shown = ssj.render_super_saiyan(frame, segmenter, levels, 0.5, ssj.AuraRenderer(), head, hands=hands)
        self.assertTrue(np.any(covered[95, 330] != frame[95, 330]))
        np.testing.assert_array_equal(shown[95, 330], frame[95, 330])

    def test_hair_is_gone_around_but_not_lit_like_the_body(self):
        # The see-through tips of the golden hair showed pale patches: the room behind the hair must be darkened
        # like the rest, with no rim light, while the aura still goes around it.
        frame = np.full((240, 320, 3), 120, np.uint8)
        body = np.zeros((240, 320), np.float32)
        body[140:240, 120:200] = 1.0
        hair = np.zeros((240, 320), np.float32)
        hair[60:140, 110:210] = 1.0
        output = ssj.AuraRenderer().render(frame, body, 1.0, 0.5, cover=lambda: hair)
        darkened = cv2.convertScaleAbs(frame, alpha=1.0 - ssj.DARKEN)
        np.testing.assert_array_equal(output[100, 160], darkened[100, 160])  # Behind the hair: dark, no rim.
        np.testing.assert_array_equal(output[100, 112], darkened[100, 112])  # Even at the hair's edge.
        np.testing.assert_array_equal(output[200, 160], frame[200, 160])  # The body is not darkened.
        self.assertGreater(int(output[50, 160, 2]), int(darkened[50, 160, 2]) + 30)  # Flames above the hair.

    def test_hands_mask_follows_the_landmarks_and_the_segmenter(self):
        segmenter = np.zeros((270, 480), np.float32)
        segmenter[:, :340] = 1.0
        mask = ssj.hands_mask([normalized(fist(330, 85), 480, 270)], segmenter)
        self.assertGreater(mask[90, 330], 0.9)
        self.assertEqual(mask[90, 345], 0.0)  # Outside the person.
        self.assertEqual(mask[200, 100], 0.0)
        self.assertIsNone(ssj.hands_mask([], segmenter))


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
