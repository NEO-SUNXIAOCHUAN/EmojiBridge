# S0113 optional capabilities / sources and licenses

S0153 removes the photo-parallax and portrait/pet adapters and their UI. DepthFlow / LivePortrait entries below document historical use only; those packages/models are not included. The 14 template IDs in excluded-templates.json are removed from the current catalog, previews and bundled runtime, leaving 2746 locked template resources. Old personal works are not removed. Upstream license records are retained.

The S0153 full local test build additionally bundles RapidOCR/CSRT's 27 installed distributions and the three default ONNX OCR models listed with SHA256 in vision-runtime-lock.json. Wheel RECORD hashes are checked; the contrib/headless wheel supplies the shared cv2 module. Distribution metadata/licenses are retained. Recognition uses an installed system font, not a downloaded visualization font. No user recognition cache, requests or results are packaged.

S0136 bundles meme-generator 0.1.14, its exact dependency closure and pinned image/font resources under runtime/meme for private offline template testing. runtime-lock.json records 48 installed distributions and 2885 resource hashes; every wheel RECORD hash is validated when packaging. Original distribution metadata, license files and upstream resource attributions are retained. No user cache, configuration or generated work is copied. Other optional environments and models are still prepared separately on demand. This is not a public release or a declaration of blanket media redistribution rights.

|Component|Pinned version/source|Use and license|
|---|---|---|
|MemeCrafters/meme-generator|Python0.1.14, resource commit f5ee44f6a3e134b9ac54032f97eab788d6454e3c|MIT code, isolated worker; https://github.com/MemeCrafters/meme-generator |
|MemeCrafters/meme-generator-contrib|8547f2e5718bfbb3328d700fe2c21d2ec5962500|MIT modules with LICENSE in ../meme_contrib; https://github.com/MemeCrafters/meme-generator-contrib |
|hitherdither|Atkinson adaptation cited in dither_atkinson.py|MIT; https://github.com/hbldh/hitherdither |
|OpenCV contrib|4.11.0.86|CSRT; Apache2.0 and third-party notices; https://github.com/opencv/opencv_contrib |
|RapidOCR / ONNX Runtime|3.4.2 / 1.23.2|local OCR; Apache2.0 / MIT; https://github.com/RapidAI/RapidOCR |
|faster-whisper / CTranslate2 / PyAV|1.2.1 / 4.8.4 / 14.2.0|CPU int8 transcript; MIT / MIT / BSD with FFmpeg notices; https://github.com/SYSTRAN/faster-whisper |
|gifski|1.34.0|optional separate encoder, AGPL3 or upstream commercial licensing; https://github.com/ImageOptim/gifski |
|DepthFlow / ShaderFlow|1.0.1 / .12|headless2.5D; AGPL3 full license texts retained, adapter source included; https://github.com/BrokenSource/DepthFlow and https://github.com/BrokenSource/ShaderFlow |
|Depth Anything V2 Small|selected by pinned DepthFlow|Small model Apache2.0, not larger restricted models; https://github.com/DepthAnything/Depth-Anything-V2 |
|LivePortrait|official Windows20240829|MIT inference; separate official package; https://github.com/KlingAIResearch/LivePortrait |

LivePortrait uses InsightFace for detection/cropping. InsightFace pretrained weights are restricted to non-commercial research use, separate from MIT inference code. Human and animal models were validated independently. Official Windows archive:5,266,629,446 bytes / extracted9.46GB; SHA256 b4e6e006d19a4c4db0729951f82ab75216802f1aeac0f8a8006da024345e9a3a. It is NOT bundled. Model availability does not grant commercial redistribution rights.

Meme template illustrations/fonts are individually sourced internet resources. Code MIT does not establish all illustration/font redistribution rights. Generated assets/factory covers are preview examples of pinned templates, not a declaration that underlying characters/art are public domain. Keep upstream resource attribution. This is a private local test build, not a public asset redistribution service; individual media rights remain unresolved.

EmojiBridge Chinese text uses installed system fonts (Windows fonts not redistributed). Meme templates retain supplied fonts and notices; this app grants no new font licenses.

S0122 reuses the installed Python0.1.14 `seal` and `stare_at_you` template makers (MIT) in the same isolated worker. `factory_animation_input.py` connects those existing per-frame visual functions to EmojiBridge's bounded frame sources and lossless APNG writer; it does not copy or replace the template artwork. This preserves input frame timing, loop count and transparency instead of the upstream helper's averaged GIF timings. Other templates keep explicit static-frame selection until individually adapted. No new dependency or model is installed.

Review landscape: Fronalpstock big, Hannes Röst, CC BY-SA3.0: https://commons.wikimedia.org/wiki/File:Fronalpstock_big.jpg . Human/pet inputs/drivers come from official LivePortrait examples; inference tests do not imply separate permissive redistribution licenses for every example photo.

Petpet old/new JSON support is a limited declarative interchange; no Java service/remote script/full frontend is installed. Unsupported instructions fail explicitly. PixiJS Filters, ScreenToGif, didder, sticker-convert and pynput remain references, not wholesale incorporated engines. Windows shortcut uses RegisterHotKey directly.

Full license texts are beside this notice and optional package distributions. Existing Pillow/NumPy/FFmpeg/TkDND/Motion/Radix/Glass notices remain in root THIRD_PARTY_NOTICES.md. No public release was performed.
