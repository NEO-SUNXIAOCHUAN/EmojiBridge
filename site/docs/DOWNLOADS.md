# 下载与启动

**S0175 · Windows x64 · 三版任选一个，全部解压后双击 EB/EmojiBridge.exe。无需安装 Python。**

| 下载 | 怎么选 |
| --- | --- |
| [轻量版 ZIP · 523.26 MB（推荐）](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0175/EmojiBridge-S0175-Windows-x64-lite.zip) | 自带默认自动抠图、基础编辑、视频/GIF、OCR 与互通组件；更多模型和模板按需选装 |
| [带模板版 ZIP · 859.43 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0175/EmojiBridge-S0175-Windows-x64-lite-templates.zip) | 包含轻量版全部功能与表情工厂模板，无需另装模板包 |
| [完整离线版 ZIP · 1.35 GB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0175/EmojiBridge-S0175-Windows-x64-full.zip) | 包含带模板版全部内容，再含动漫/精细抠图和 tiny 字幕 |
| [公开源码 · 114.63 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0175/EmojiBridge-S0175-public-source.zip) · [SHA256 校验](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0175/SHA256SUMS.txt) | 开发者或需要核验下载内容的用户 |
| [宣传片同款素材 · 707 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0163/EmojiBridge-promo-assets-20261114.zip) | 独立可选，解压后多选导入，不随软件自动初始化 |

三版使用同一套程序，自带默认 **自动／U²-Net** 抠图模型，默认抠主体无需联网下载。区别是附带的模板和可选模型。大小采用十进制 MB / GB，不代表运行内存。

## 三步开始

1. 选择上面的一个软件 ZIP 下载。
2. **全部解压到新文件夹**，不要在压缩包预览中运行。
3. 打开 **EB** 文件夹，双击 **EmojiBridge.exe**。保留同目录运行文件，不要只移动一个 EXE。

不需要命令行、安装 Python 或默认使用管理员身份。系统缺少 Microsoft WebView2 时，按启动提示安装 [微软官方 Evergreen Standalone Installer x64](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)，再重新检查。

## 已有用户升级

S0175 已包含此前累计修复。保存作品并退出旧程序，解压到新目录启动；保留旧目录与个人素材、账号和草稿。**不要再叠加旧补丁，也不要混合覆盖不同版本。** 使用自定义 `--data-dir` 的用户继续使用原数据目录参数。

## 可选组件

打开 **设置 → 可选组件 → 下载组件 → 导入已下载组件包**。组件 ZIP 不用手动解压；软件会校验后安装。导入后重新打开工具，若组件已被加载则重启软件。

**S0175 继续使用 S0174 的四个组件包，已有同版组件无需重新安装。** 带模板版自带模板组件，完整离线版自带下列四项。

| 组件 | 下载大小 |
| --- | ---: |
| [动漫抠图 · IS-Net Anime](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-anime.zip) | 163.76 MB |
| [精细抠图 · BiRefNet Lite](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-fine.zip) | 164.91 MB |
| [tiny 字幕及专用运行环境](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-speech.zip) | 159.08 MB |
| [模板扩展及专用依赖](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-templates.zip) | 336.13 MB |

视频转 GIF / MP4 所需 FFmpeg、默认自动抠图、OCR 与互通视觉组件三版均包含。base/small 字幕、SAM2 等其他模型不包含在上述四项及完整离线版中。

## 本版更新

本版修复浅色微信搜索、白边/透明图片匹配及已知未发送草稿恢复，并减少重复文字识别。创作页支持多选删除草稿；同一素材可重复贴到桌面，固定后可取消、右键可旋转；编辑器平移可再次点击、按 Esc 或切换工具退出。保留此前 QQ 路径发现、重新检测状态及下载标记 DLL 启动修复。

开发侧源码及包内各 188 项回归通过，三版普通 EXE 本机验收通过。不同电脑、客户端版本和缩放布局仍需复测，不保证所有环境零故障。

## 互通前

- 转入微信会使用本人的文件传输助手发送素材并添加表情，占用聊天上下文并产生消息记录。
- 读取 QQ 收藏及补原件时请勿移动鼠标。互通自动操作期间，请勿点击、滚动、拖动、遮挡或切换目标窗口；需要操作时先取消。QQ / 微信需要联网并登录。

QQ 路径未识别时，可在账号设置选择实际数据文件夹，再重新检测。反馈问题提供软件/客户端版本和复现步骤即可，无需上传账号数据库或聊天内容。

## 下载中断

软件通过 GitHub Releases 下载，速度受网络线路影响。中断时先在浏览器下载列表点击继续或重试；下载完成后可用 SHA256 校验文件确认完整性。
