# Windows 源码与离线组件

源码导出不包含 Git 历史、用户数据或二进制运行时。`SOURCE_BUILD.json` 记录产品提交与逐文件 SHA256；软件 `BUILD.json` 记录同一产品提交和实际分发文件。原创代码许可见 LICENSE，第三方代码和权重许可见 THIRD_PARTY_NOTICES.md / RELEASE_RIGHTS.md。

## 从源码启动

使用 Windows x64、带 Tk 的 Python 3.12，在独立虚拟环境安装 requirements-release.txt。桌面需要 WebView2 Runtime。前端源在 desktop-ui，使用锁定的 pnpm-lock.yaml 安装后执行 pnpm build。run-desktop.cmd 启动脚本入口。

## 基础打包

公开源码解压后先在本地初始化 Git 并提交文件。用已安装 requirements-release.txt 的 Python 运行 scripts/build_pilot.py，传入 --output exports/windows-preview、--runtime Python 根目录及 --desktop-runtime 桌面依赖目录。可追加 --cutout-runtime、--vision-runtime、--template-runtime。准确参数见该脚本 --help。

基础构建与完整离线包不同：完整包还需要下列原始组件，不能只把基础构建改名为 full。

| 组件 | 完整包内位置 |
| --- | --- |
| 三种抠图权重 | runtime/cutout-models/u2net.onnx、isnet-anime.onnx、birefnet-general-lite.onnx |
| 抠图运行时 | runtime/cutout |
| OCR 与跟随 | runtime/vision；准确资源清单见 third_party/factory/vision-runtime-lock.json |
| 模板与生成运行时 | runtime/meme；锁定清单见 third_party/factory/runtime-lock.json |
| 视频转码 | runtime/ffmpeg/ffmpeg.exe、ffprobe.exe |
| 默认字幕 | runtime/speech 与 runtime/speech-models/tiny，由 scripts/factory_speech_worker.py 定位 |

权重来源、固定校验值和定位规则分别见 src/emoji_bridge/background_remove.py、capabilities.py、scripts/factory_speech_worker.py、video.py。准备组件时保留其许可证文件，不从个人库复制账号或缓存目录。可从已核验 SHA256 的对应完整发行包提取这些运行时组件；这不替代源码，也不应复制其中的旧产品脚本。

## S0168 R2 发行流水线

scripts/package_download_ready.py 是本轮增量重组工具：以未修改的 S0167 完整包为运行时基线，校验基线 SHA256，再加入本轮显式产品文件和两份已固定校验的模型 ZIP，生成新 BUILD.json、完整 ZIP 和仅适用于 S0167 的补丁。输入文件名和 SHA 在脚本中列明。它需要这些本地发行输入，不能在只有源码 ZIP 的环境中凭空生成二进制运行时。

scripts/export_public_source.py 按白名单从已提交文件生成公开源码。发行前必须核对软件和源码提交一致、重叠产品文件逐字节一致、完整 ZIP CRC/全部清单 SHA，以及三种抠图、模板、OCR、跟随、FFmpeg 和 tiny 的空缓存离线实际运行。下载标记启动测试只用独立副本，不对用户目录解除锁定。

测试入口：python -m unittest discover -s tests -p test_download_startup_S0168.py -v；初始化测试见 README。下载标记用例仅适用于支持 NTFS ADS 的 Windows 文件系统。
