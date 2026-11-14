# EmojiBridge 第三方代码与资源

S0163 首发候选。原创代码版权 Neo，GPL-3.0-only；第三方各自原许可保留。
具体发行资源的待核事项见 RELEASE_RIGHTS.md，不宣称全部素材已取得分发授权。

## 实际运行与构建组件

| 组件 | 使用方式 | 许可/来源记录 |
| --- | --- | --- |
| CPython 3.12 / Tcl-Tk | 随 Windows 包运行时 | runtime/LICENSE.txt、runtime/tcl、runtime/DLLs 原文 |
| Pillow / NumPy / cryptography / cffi / pycparser / pip | 独立依赖 | runtime/p 的 dist-info 原许可；精确版本在 BUILD.json |
| pywebview / pythonnet / clr_loader / bottle / proxy_tools | 桌面宿主 | runtime/desktop distribution 元数据与许可 |
| ONNX Runtime 1.23.2 | 独立 CPU 推理 | MIT，third_party/cutout，模型不随主包 |
| RapidOCR / OpenCV contrib | OCR / CSRT | Apache-2.0 及各依赖原许可，third_party/factory/vision-runtime-lock.json |
| React / ReactDOM / Motion / Radix / liquid-glass-react | bundle 依赖 | MIT，锁文件 desktop-ui/pnpm-lock.yaml，assets/desktop/THIRD_PARTY.txt |
| Lucide React | 图标 | ISC，同上述 bundle 声明 |
| TkinterDnD2 / TkDND | 原生文件拖放 | third_party/tkdnd 原许可证和 SOURCE.json |
| meme-generator / meme-generator-contrib | 独立模板 worker / 部分模块复制 | MIT，third_party/factory 与 third_party/meme_contrib；插画/字体单独核对 |
| hitherdither | Atkinson 实现改编 | MIT，third_party/factory/hitherdither-LICENSE |
| rembg | 预处理和蒙版缩放改编 | MIT，third_party/cutout/NOTICE.md 与完整原许可 |
| FFmpeg | S0167 离线测试包内独立进程 | GPLv3 Gyan 构建；原 LICENSE / README 随 runtime/ffmpeg；third_party/FFmpeg-NOTICE.md |
| gifski | 可选独立编码器 | AGPLv3，third_party/factory/gifski-LICENSE；不随软件包 |
| SAM2 | 可选跟随模型调用 | 原许可及声明见 third_party/sam2；权重按需 |
| miniPaint | 旧草稿兼容/可选组件 | MIT，third_party/miniPaint-MIT.txt；主要编辑器为原生 Tk |

软件包保留所有实际分发依赖的 dist-info、许可证和版权声明。模板扩展保留同一锁定依赖集合。
未将 DepthFlow / LivePortrait 运行时、模型或人物宠物输入资源重新加入包。

## 初始素材和界面资源

- Twemoji v16.0.1 图形为 CC BY 4.0；assets/examples/LICENSE-GRAPHICS.txt 及来源记录保留。
- 四张经典 Meme 仅在独立宣传片素材包中，不随软件或源码分发；来源与SHA保留在独立素材包。不属于 Twemoji 授权范围，也不适用项目源码 GPL 授权。
- 模板插画/字体依照上游各项来源记录；引擎 MIT 不自动覆盖作品版权。
- V10、随手素材、像素动效由用户提供的代码包适配，实际出处在 assets/desktop/THIRD_PARTY.txt、assets/startup-v10、assets/motion。
- 游戏声音、美术及 QQ/微信品牌标识不由本项目重新授权；公开分发证据状态见 RELEASE_RIGHTS.md。
- OhMyMeme、Fabric、ScreenToGif、PixiJS 等为交互或格式阅读参考，没有将整套应用代码/资源复制到产品；不是随包运行依赖。

## Windows-MCP（S0049隔离研究；S0050小范围改编）

- 仓库：https://github.com/CursorTouch/Windows-MCP
- 固定提交：`b74c507d9e709223a0904cf08019edf55f2a75bb`，该树声明0.8.8、Python>=3.14。
- 根许可证MIT，Copyright (c) 2025 JEOMON GEORGE；`uia/`模块头另注明源自yinkaisheng/Python-UIAutomation-for-Windows、Apache-2.0。原许可/模块声明保留于忽略的研究副本。
- 实际研究：原样执行UIA子模块进行限定窗口结构读取；隔离提取并执行`desktop/service.py`中的`bring_window_to_top`原函数，未运行整个服务/全桌面Snapshot/遥测/常驻监听。comtypes1.4.15、pywin32311仅安装到私有研究目录，未列为产品依赖。
- 项目新增的QQ只读探针直接使用Windows.NET UIAutomation，未复制上游实现。来源、实际计时与限制见`docs/T006-windows-mcp-S0049.md`；后续若引入/分发上游代码，需保留对应许可及模块来源。
- S0050：`src/emoji_bridge/source_focus.py`参考并改编该固定版本`Desktop.bring_window_to_top`的当前线程同时关联前台/目标线程方法，只接入QQ来源读取的任务起始激活。使用项目现有ctypes，另加身份/取消/输入并发/中途前台改变拒绝/成功关联逆序解绑；不调用全局`AllowSetForegroundWindow(-1)`，不注入按键、不猜点标题栏。根MIT原文按字节保存于`third_party/windows_mcp/LICENSE`，来源及差异见同目录`SOURCE.json`。没有引入上游UIA代码或其Apache来源模块，完整MCP服务和Python3.14不是产品运行依赖。

## wechat_meme_export

- 作者／仓库：Ant39140，https://github.com/Ant39140/wechat_meme_export
- 固定提交：`908adfa3b7a0b4560825c9db2bf234ef5368c8ec`
- 许可：MIT；上游完整许可原样保存在 `third_party/wechat_meme_export/LICENSE`。
- 原样引入：`memory.py`、`decrypt.py`，来自上游 `src/wechat_meme_export/`。
- 实际复用：Win32 内存读取器和页解密；本项目另加限定进程、超时、HMAC、稳定快照与 WAL 校验。没有运行上游 CLI、GUI、密钥打印／导出命令。

## export-wechat-emoji

- 作者／仓库：liusheng22，https://github.com/liusheng22/export-wechat-emoji
- 固定提交：`f1196314b66eddbe4da2a8b958c8082b5945aa1f`
- `cli/Cargo.toml` 声明 `license = "MIT"`；该固定树没有独立 LICENSE 文件。源码阅读副本在忽略的研究目录，尚未把上游整包并入源码。
- `wechat_index.py` 中微信 4.1 Config.Cipher 名称、对象布局、XOR 规则，以及表情库 HMAC 参数，依据其 `cli/src/windows.rs`、`keyscan.rs` 核对。WAL 校验采用 SQLite 格式；不沿用其密钥持久缓存、非收藏表兜底、缩略图兜底。
- 本次重新核对固定 Cargo.toml 仍声明 MIT；固定树没有独立 LICENSE。本项目不分发其源码或二进制，格式参考与复制代码分开记录。

wechat_meme_export 的固定仓库、完整提交、采用文件及 SHA-256 另随源码记录在 `third_party/wechat_meme_export/SOURCE.json`，三个文件均原样保留。export-wechat-emoji 的阅读摘要另存本机研究报告。不把第三方宣称的功能当成本项目实测结论。

## QQNT 原件目录研究参考（S0028，仅阅读，未引入代码）

- https://github.com/dogxii/BackupQQEmoji ，提交 `eb1c2979cdfe225eecfae0d4cadb73d6482c7918`，MIT：核对 `personal_emoji/Ori`、`Thumb` 和真实文件格式说明。
- https://github.com/VanillaNahida/QQFavoriteExtract ，提交 `f9f224504dc6f79cf85fa3291a965f38f55e48b0`，GPL-3.0：核对保存路径定位和缓存范围限制。
- https://github.com/OhMyMeme/OhMyMeme ，提交 `3a3cad5c6a17544718ca5eb309a2ab77e7dadd3b`：仓库元信息及所读 `src/qqnt_extract.py` 明确 GPL-3.0，模块说明源自 QQFavoriteExtract；核对 `UserDataInfo.ini` 的 `UserDataSavePath` 和固定个人表情目录。

本轮未复制、执行或分发以上三个项目的源码／二进制，未使用其外部昵称查询；项目内另写只读候选与完整副本验证程序。准确阅读范围和本机限制见 `docs/T006-qq-cache.md`，不将缓存中所有文件直接视作当前收藏。
