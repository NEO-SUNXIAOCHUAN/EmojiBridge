# 下载与启动

**S0183 · Windows x64 · 三版任选一个，全部解压后双击 EB/EmojiBridge.exe。无需安装 Python。**

| 下载 | 怎么选 |
| --- | --- |
| [轻量版 ZIP · 523.40 MB（推荐）](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0183/EmojiBridge-S0183-Windows-x64-lite.zip) | 自带默认自动抠图、基础编辑、视频/GIF、OCR 与互通组件；更多模型和模板按需选装 |
| [带模板版 ZIP · 859.56 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0183/EmojiBridge-S0183-Windows-x64-lite-templates.zip) | 包含轻量版全部功能与表情工厂模板，无需另装模板包 |
| [完整离线版 ZIP · 1.35 GB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0183/EmojiBridge-S0183-Windows-x64-full.zip) | 包含带模板版全部内容，再含动漫/精细抠图和 tiny 字幕 |
| [公开源码 · 114.80 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0183/EmojiBridge-S0183-public-source.zip) · [SHA256 校验](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0183/SHA256SUMS.txt) | 开发者或需要核验下载内容的用户 |
| [宣传片同款素材 · 707 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0163/EmojiBridge-promo-assets-20261114.zip) | 独立可选，解压后多选导入，不随软件自动初始化 |

三版使用同一套程序，自带默认 **自动／U²-Net** 抠图模型，默认抠主体无需联网下载。区别是附带的模板和可选模型。大小采用十进制 MB / GB，不代表运行内存。

## 三步开始

1. 选择上面的一个软件 ZIP 下载。
2. **全部解压到新文件夹**，不要在压缩包预览中运行。
3. 打开 **EB** 文件夹，双击 **EmojiBridge.exe**。保留同目录运行文件，不要只移动一个 EXE。

不需要命令行、安装 Python 或默认使用管理员身份。系统缺少 Microsoft WebView2 时，按启动提示安装 [微软官方 Evergreen Standalone Installer x64](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)，再重新检查。

## 已有用户升级

**S0175 用户需手动安装 S0183 一次，之后才能使用内置更新。** 保存作品并退出旧程序，完整解压到较短的新目录（例如 `D:/EmojiBridge`），运行 `EB/EmojiBridge.exe`；保留旧目录与个人素材、账号和草稿。不要混合覆盖或叠加旧补丁。使用自定义 `--data-dir` 的用户继续使用原数据目录参数。

新版启动只检查官方稳定版信息；点击更新后才下载同类型完整 ZIP，并核对大小、SHA256 和文件清单，正常保存退出后替换程序、重启确认，失败时尝试回退。它不是差分更新；上传源码本身不会触发更新，需要发布配套软件包和更新清单。兼容的已安装组件会保留。

## 可选组件

打开 **设置 → 可选组件** 在线下载并安装，或选择 **导入已下载组件包**。组件 ZIP 不用手动解压；软件会校验后安装。导入后重新打开工具，若组件已被加载则重启软件。

**S0183 继续使用 S0174 的四个组件包，已有同版组件无需重新安装。** 带模板版自带模板组件，完整离线版自带下列四项。

| 组件 | 下载大小 |
| --- | ---: |
| [动漫抠图 · IS-Net Anime](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-anime.zip) | 163.76 MB |
| [精细抠图 · BiRefNet Lite](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-fine.zip) | 164.91 MB |
| [tiny 字幕及专用运行环境](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-speech.zip) | 159.08 MB |
| [模板扩展及专用依赖](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-component-templates.zip) | 336.13 MB |

视频转 GIF / MP4 所需 FFmpeg、默认自动抠图、OCR 与互通视觉组件三版均包含。base/small 字幕、SAM2 等其他模型不包含在上述四项及完整离线版中。

## 本版更新

S0183 汇总 S0176–S0183 的改进：素材库批量选择、文件夹导入与父子合集、相似图人工整理、备份恢复；随手素材复制与桌面贴图；实时桌面绘制中的形状、箭头、文字与画笔，可选回对象移动、旋转、缩放。完成绘制后生成临时贴图，不自动入库。QQ 来源按“更新”读取本人缓存，读取和复制不再自动加入素材库。

开发侧已完成三版 EXE、默认模型与离线功能、本地升级和组件保留验证；部分升级测试使用隔离父进程模拟保存信号。不同电脑、客户端版本和缩放布局仍需复测，不保证所有环境零故障。

## 互通前

- 转入微信会使用本人的文件传输助手发送素材并添加表情，占用聊天上下文并产生消息记录。
- QQ 缓存读取可在 QQ 关闭时进行；自动操作客户端进行互通时，需要登录相应客户端，并请勿点击、遮挡或切换目标窗口，需要操作时先取消。

QQ 路径未识别时，可在账号设置选择实际数据文件夹，再重新检测。反馈问题提供软件/客户端版本和复现步骤即可，无需上传账号数据库或聊天内容。

## 下载中断

软件通过 GitHub Releases 下载，速度受网络线路影响。中断时先在浏览器下载列表点击继续或重试；下载完成后可用 SHA256 校验文件确认完整性。
