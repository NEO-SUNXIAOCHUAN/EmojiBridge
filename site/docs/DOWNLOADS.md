# 下载与启动

**S0168 R2 · Windows x64**。完整包已带齐三种抠图模型、模板、识字与跟随、视频处理组件和默认字幕模型。

- [完整 ZIP · 1.35 GB（推荐）](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0168R2/EmojiBridge-S0168-download-ready-trial-full.zip)
- [同版 7z · 1.19 GB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0168R2/EmojiBridge-S0168R2-full-lossless.7z)：内容相同，下载量减少约 11.7%。请使用支持 7z 的解压工具。
- [对应公开源码 · 114 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0168R2/EmojiBridge-S0168R2-public-source.zip)：开发者使用。
- [SHA256 校验文件](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0168R2/SHA256SUMS-release-S0168R2.txt)
- [宣传片同款素材 · 707 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0163/EmojiBridge-promo-assets-20261114.zip)：独立可选，解压后多选导入。

## 三步开始

1. 保存作品并正常退出旧版。下载 ZIP 或 7z，二选一即可。
2. **全部解压到一个新文件夹**，不要在压缩包预览里运行。
3. 双击 **EB/EmojiBridge.exe**，保留同目录运行文件。无需运行命令行，也无需默认使用管理员身份。

升级不需要删除个人素材库。不要只移动 EXE，不要将不同版本混合覆盖。

## 模型和运行组件

| 功能 | 完整包提供什么 |
| --- | --- |
| 抠主体 | U2-Net、IS-Net Anime、BiRefNet Lite 三种模型和执行环境 |
| 模板、识字与跟随 | 模板引擎、OCR 模型和跟随组件 |
| 视频转 GIF / MP4 | FFmpeg 与 ffprobe |
| 视频台词与字幕 | 默认 tiny 字幕模型与执行环境 |

以上默认本地功能无需首次下载模型。更大的 base / small 字幕模型可按需下载；失败时仍可使用随包 tiny。模型首次加载、大图或多帧处理可能需要等待。

S0168 R2 已修复下载标记引起的部分 DLL 加载失败。**缺少 Microsoft WebView2 的电脑**，按启动提示安装 [微软官方 Evergreen Standalone Installer x64](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)，再点击重新检查。

## 互通前，记住这两件事

- 转入微信会使用本人的文件传输助手，发送素材并添加表情，占用聊天上下文并产生消息记录。
- 读取 QQ 表情或执行互通时，请不要移动鼠标、点击或切换窗口；等待任务完成。QQ / 微信需要联网并登录，首次连接可能需要等待。

## S0167 测试版专用补丁

[下载补丁 · 330 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0168R2/EmojiBridge-S0168-download-ready-patch.zip)，仅适用于未修改的 S0167 b20f907 完整测试包。**不适用于 S0163、旧 S0168 或新用户。** 不确定版本请使用上方完整 ZIP。

文件大小使用十进制 GB / MB。可用 SHA256 校验文件核验下载内容。
