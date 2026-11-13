# Local static cutout dependencies

EmojiBridge S0100 uses one local CPU foreground model: **U²-Net (`u2net`)**. Images are processed locally. Only the optional runtime wheels and public model weights are downloaded; input images are never uploaded.

## Adapted model session

- Source: [rembg](https://github.com/danielgatis/rembg), commit `c5b48b0417a0254df7d461efa14573597f369a83`.
- Reused portions: `rembg/sessions/base.py` image normalization, `rembg/sessions/u2net.py` output normalization and mask resizing, and its official weight URL/checksum.
- Copyright (c) 2020 Daniel Gatis. MIT license, reproduced in `rembg-LICENSE.txt`.
- Modifications: use a short-lived isolated ONNX Runtime CPU worker instead of importing the full rembg package; preserve original RGBA dimensions, multiply the inferred mask by existing alpha, expose progress/cancel, persist/cache transparent results. No scipy, scikit-image, pymatting or rembg CLI/server dependencies are imported.
- S0101 extends this worker to PNG sequences, following the same pinned rembg README session-reuse example and `rembg/commands/b_command.py`: one model session per sequence, existing FFmpeg/Pillow decoding, per-frame RGBA output and cancellation. No additional inference dependency is introduced. Original video/GIF bytes and lossless alpha frames remain in editable drafts separately from palette-based delivery GIFs.

## Model

- Upstream: [U-2-Net](https://github.com/xuebinqin/U-2-Net), Xuebin Qin et al., official project repository under Apache-2.0 (`U-2-Net-LICENSE.txt`).
- Converted ONNX distribution: [rembg u2net.onnx release asset](https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx).
- Official rembg checksum: MD5 `60024c5c889badc19c04ad937298a77b`; download is checked before use. Model is not checked into this repository or bundled into a public package in this round.
- Initial lightweight U²-NetP trial was rejected as the default because it visibly omitted the raised arms in the tested portrait. The final default uses U²-Net, approximately 176 MB, through the same session/preprocessing architecture.

## Inference runtime

- [Microsoft ONNX Runtime](https://github.com/microsoft/onnxruntime/tree/v1.23.2), 1.23.2, MIT (`onnxruntime-LICENSE.txt`). CPUExecutionProvider, two intra-op threads and one inter-op thread.
- NumPy 2.3.5; the desktop's existing Pillow is reused. Optional wheel dependencies keep their own upstream license files inside the separate runtime installation.
- Install location: `%LOCALAPPDATA%/EmojiBridge/optional/cutout-ort-1.23.2`; model and immutable PNG cache: `%LOCALAPPDATA%/EmojiBridge/cutout`.
- Runtime/model preparation occurs on first use and can be cancelled/retried. Existing app Python packages are not upgraded. A future portable installer must separately package the optional runtime and all its dependency notices, or document the first-use download; this round produces no distribution package.

S0106 portable distribution update: the existing CPython builder can copy the verified ONNX Runtime 1.23.2 CPU wheel and its installed dependencies into `runtime/cutout`, including wheel license/metadata files. NumPy/Pillow come from the bundled main runtime. The isolated worker adds only this explicit path (embedded CPython does not honor PYTHONPATH). Model weights are not bundled; the same checked first-use download/local model path above is retained. FFmpeg remains a pinned first-use download or explicit local tool path, not a binary copied into this ZIP.

## Verification inputs

Two public rembg example images (`examples/animal-1.jpg` and `examples/girl-1.jpg`) from the same pinned commit were used for local checks, under the upstream repository's license. Inputs and output comparison images remain in ignored private test evidence and are not redistributed with the application. Existing-alpha testing derived a transparent strip from the animal input to check that segmentation never restores erased pixels. Model quality is not guaranteed for fine hair, similar foreground/background colors, small objects, multiple subjects or arbitrary anime art.

## S0112 models and editable masks

Default remains U²-Net. Optional candidates use the rembg session preprocessing protocols in `dis_anime.py`, `birefnet_general.py`, and `birefnet_general_lite.py` (MIT). Model selection reuses one isolated ONNX Runtime 1.23.2 CPU session per sequence, now up to eight intra-op threads and one inter-op thread. Original alpha and a separate editable mask are stored; repeated inference starts from the original.

- ISNetAnime: SkyTNT/anime-segmentation, Apache-2.0 (anime-segmentation-LICENSE.txt). Official rembg v0.0.0/isnet-anime.onnx, MD5 6f184e756bb3bd901c8849220a83e38e; input 1024, mean (.485, .456, .406) / std 1. On the tested nine-frame anime GIF it dropped most of two frames; it remains explicitly experimental.
- BiRefNet-general-lite: ZhengPeng7/BiRefNet, MIT (BiRefNet-LICENSE.txt). Official rembg v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx, MD5 4fab47adc4ff364be1713e97b7e66334; input 1024, ImageNet normalization, sigmoid output. It retained the tested character body better, at significantly higher CPU cost. UI labels this choice 动漫 / 精细（较慢）; not a universal quality guarantee.
- Weights remain optional checked downloads, not bundled. No GPU framework or second processing engine is installed.
- Editable masks and source drafts also feed dropped-item effects; the output GIF retains only GIF's supported binary alpha, while the editable originals/masks retain full alpha.


## S0130 scribble adaptation
The same three automatic ONNX models and weight digests above remain in use. None has a native scribble prompt input. EmojiBridge selects connected model-alpha regions from normalized positive/negative brush prompts; only conflicting seeds in a connected region invoke the existing OpenCV 4.11 GrabCut mask initializer. A brush-shaped exclusion hole is rejected when it does not separate subjects. Soft model alpha is retained; missed subjects cannot be reconstructed. Existing DIS forward/backward correspondence follows dynamic selections, with explicit failure on unstable correspondence. This is not identity-aware tracking through occlusion.

References inspected: official OpenCV `samples/python/grabcut.py` (4.x) and mask-initialization tutorial, https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html. No GUI or rectangle-first requirement was copied; no new model or application was embedded. IOPaint interactive segmentation documentation was reviewed as an interaction reference only; no IOPaint code/dependency was imported. Existing OpenCV licensing notices remain applicable.
