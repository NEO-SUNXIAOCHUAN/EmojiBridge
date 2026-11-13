# EmojiBridge SAM 2 adapter

Upstream: https://github.com/facebookresearch/sam2
Commit: 2b90b9f5ceec907a1c18123530e92e794ad901a4

The Python package and configs are vendored with Apache-2.0 and cctorch BSD notices.
Weights are not bundled. The optional capability downloads the official SAM2.1
Hiera Tiny checkpoint and validates its SHA-256. Our worker adds a two-frame LRU
loader and uses the official image/video predictors. No custom model or encoder.

Tested on Windows 11, Python 3.12, CPU, torch 2.15.0+cpu, torchvision 0.29.2+cpu,
hydra-core 1.3.2, iopath 0.1.10. Model/session is reused across a propagation run.
The optional installer reuses an existing verified project runtime when available;
otherwise installs pinned packages into its own capability directory. A fresh
machine installation has not been validated. No system Python or WSL is needed
for manual lasso/brush tools. Automatic postprocessing CUDA extension is omitted.

Video propagation is limited to an explicitly selected maximum of 180 frames per
operation; it does not silently shorten the original or change its timing. Long
CPU runs can be cancelled. Complex occlusions and leaving/reentering the frame
remain manual-review cases. Model scores are not exposed as verified accuracy.
