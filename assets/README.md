# Substitution log sprite

`substitution_log.png` was generated with the built-in ImageGen tool. The user
image was used as a visual reference for object shape and mood, not as an edit
target. The sprite is an original transparent-background illustration.

Final prompt:

> Create a single ORIGINAL 2D hand-painted anime-style game sprite for live video compositing, using the user's attached image ONLY as a visual reference for the object and mood. Subject: one short thick wooden substitution log floating diagonally (bottom-left to top-right), soft desaturated pale sage-green bark with visible wood grain, dark ink cracks and small dark notches, round cut end with concentric wood rings visible at lower-left. Dramatic clean silhouette, strong cel shading and highlights, polished Japanese animation look. Center the entire log, leave a modest transparent margin around all edges. NO smoke, NO particles, NO background, NO scenery, NO shadow outside the object, NO people, NO text, NO symbols or logos. True transparent alpha background; isolated cutout. Asset should be immediately usable as a sprite over live webcam video.

For smoke, the app uses its own procedurally animated shapes in
`naruto_effect.py`. A [CC0 smoke sprite sheet](https://opengameart.org/content/smoke-sprite-sheet)
was reviewed but is not included because the procedural smoke scales and follows
the detected person dynamically.

## Teleport sound

`teleport.mp3` comes from [bernardocm10/vanish_webcam](https://github.com/bernardocm10/vanish_webcam)
and is used by Dragon Ball mode. That repository has no license and the audio may be third-party material, so it is
not covered by this fork's MIT license (see `NOTICE.md`). A user-provided file with the same name overrides it.

## Super Saiyan sound

`ssj_transform.mp3` was supplied by the owner and is the transformation sound. It is third-party material and is not
covered by this fork's MIT license (see `NOTICE.md`). A user-provided file with the same name overrides it. The charge
and aura hum are generated in `super_saiyan_effect.py`; the Super Saiyan aura itself is procedural and needs no image.

There used to be a `saiyanaura.gif`; it was removed because the aura must surround the silhouette, and a rectangular
GIF painted the person. `AuraRenderer` now draws the aura outside the person mask.

## App icon

`vanish_icon.png` is upstream's `vanish_icon.ico` converted to PNG for the Ubuntu Applications menu. It is not covered
by the MIT license (see `NOTICE.md`); `vanish_icon.ico` is used by the Windows build.
