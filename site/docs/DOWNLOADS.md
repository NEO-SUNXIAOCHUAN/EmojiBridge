# 下载与启动

**S0174 · Windows x64 · 完整解压后，双击 EB/EmojiBridge.exe。无需安装 Python。**

| 下载 | 怎么选 |
| --- | --- |
| [轻量版 ZIP · 523.25 MB（推荐）](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-Windows-x64-lite.zip) | 含默认自动抠图、基础编辑、视频/GIF、拖出与互通组件；其他模型和模板按需选装 |
| [完整离线版 ZIP · 1.35 GB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-Windows-x64-full.zip) | 另含动漫/精细抠图、tiny 字幕及模板扩展，适合希望一次下齐的用户 |
| [公开源码 · 114.61 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-public-source.zip) · [SHA256 校验](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/SHA256SUMS.txt) | 开发者或需要核验下载内容的用户 |
| [宣传片同款素材 · 707 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0163/EmojiBridge-promo-assets-20261114.zip) | 独立可选，解压后多选导入；不随软件自动初始化 |

两版自带同一个默认 **自动／U²-Net** 模型，默认抠主体无需联网。轻量版较 S0168 R2 下载体积减少约 61.1%。大小采用十进制 MB / GB，不代表运行内存。

## 三步开始

1. 下载轻量版或完整版 ZIP，任选一个。
2. **全部解压到新文件夹**，不要在压缩包预览里运行。
3. 进入 **EB** 文件夹，双击 **EmojiBridge.exe**。保留同目录运行文件，不要只移动一个 EXE。

不需要命令行或安装 Python，也不需要默认使用管理员身份。系统缺少 Microsoft WebView2 时，按启动提示安装 [微软官方 Evergreen Standalone Installer x64](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)，再重新检查。

## 已有用户升级

保存作品并正常退出旧程序，再将 S0174 解压到新目录启动。**S0169—S0173 的累计修复已整合，不要再叠加旧补丁，也不要混合覆盖不同版本。** 保留旧软件目录和个人素材、账号、草稿、模型。

默认用户库位置保持不变；原先使用自定义 `--data-dir` 的用户继续使用原数据目录参数。两种版本是同一套代码，区别是附带组件。

## 轻量版的可选组件

打开 **设置 → 可选组件 → 下载组件 → 导入已下载组件包**。组件 ZIP 不用手动解压；软件会校验后安装。导入后重新打开工具，若组件已被加载则重启软件。完整版会显示这些组件已安装。

| 组件 | 下载大小 |
| --- | ---: |
| [动漫抠图 · IS-Net Anime](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-anime.zip) | 163.76 MB |
| [精细抠图 · BiRefNet Lite](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-fine.zip) | 164.91 MB |
| [tiny 字幕及专用运行环境](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-speech.zip) | 159.08 MB |
| [模板扩展及专用依赖](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-templates.zip) | 336.13 MB |

基础视频转 GIF / MP4 使用的 FFmpeg、默认自动抠图和互通所需 OCR/视觉组件，两版均已自带。base/small 字幕、SAM2 等其他模型不包含在上述四项及完整离线版中。

## 本版修复

改进 QQ 路径发现和手动选择、重新检测的旧状态处理，以及微信窗口贴边时的视觉处理；累计包含旧草稿恢复/隔离、启动恢复、混合图片判断与视觉识别复用等 S0169—S0173 修复。保留 S0168 R2 的下载标记 DLL 启动修复。

开发侧已做本机 EXE、断网默认模型、组件导入和拖出验证。反馈故障电脑仍需复测，控件首次慢、部分环境控件不可见和不同缩放布局仍有待验证，不保证所有电脑零故障。

## 互通前，记住这两件事

- 转入微信会使用本人的文件传输助手发送素材并添加表情，占用聊天上下文并产生消息记录。
- 读取 QQ 收藏或执行互通时，请不要移动鼠标、点击、切换或遮挡目标窗口，等待任务完成。目标 QQ / 微信需要联网并登录。

QQ 路径未识别时，可在账号设置选择实际数据文件夹，再重新检测；多账号请确认本人所用目录。问题反馈提供软件/客户端版本及复现步骤即可，不需上传账号数据库或聊天内容。
