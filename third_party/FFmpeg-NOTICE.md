# S0100 FFmpeg 来源与许可

- 工程没有引入 FFmpeg 源码或 Python 视频库；仅通过独立本地进程调用 `ffmpeg` / `ffprobe`。
- 先复用 `EMOJI_BRIDGE_FFMPEG_BIN` 指定目录或 PATH 中的完整工具对。没有可用工具时，按需取得唯一固定 Windows 构建：Gyan FFmpeg **9.0.2 essentials**。
- 来源页：[Gyan Windows builds](https://www.gyan.dev/ffmpeg/builds/)；FFmpeg 官方下载页列出的 Windows 构建提供者。[官方构建发布](https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2)。
- 固定文件：[ffmpeg-9.0.2-essentials_build.zip](https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip)，114768076 字节；SHA-256 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。
- 构建对应 FFmpeg 来源：[946fcce07b](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b)。原始 LICENSE、README.txt 和 `build.json` 与工具保存在 `%LOCALAPPDATA%/EmojiBridgePilot/tools/ffmpeg-9.0.2/`，不混入素材原件。
- 本次实际构建启用 `--enable-gpl --enable-version3 --enable-libx264`，按 **GPL-3.0-or-later** 构建许可处理，不能称为 LGPL-only。仅提取 ffmpeg.exe、ffprobe.exe 及原许可证/说明，不运行 ffplay，不安装系统组件。
- 本轮只在用户本机按需下载并使用，未把二进制提交仓库或外发包。未来若随 EmojiBridge 分发这套构建，需同步完整许可、版权声明、构建信息及相应源代码提供方式，并核对该构建所含外部库义务；不能把本记录或单个上游源码链接当作已完成分发合规。

技术接口参考 FFmpeg 自身 `-h full`、`ffprobe -show_format -show_streams -of json`、`palettegen`/`paletteuse`；实际实现以本机上述固定构建及真实短片检查为准。没有直接移植第三方应用代码。
