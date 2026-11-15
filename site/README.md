<p align="center"><img src="assets/readme-cover.png" alt="EmojiBridge：好梗，不必留在原地。收集、创作，再带去 QQ 和微信。" width="1200"></p>

# EmojiBridge

**把喜欢的表情收起来，改成自己的梗，再带到 QQ 和微信。**

一款 Windows 桌面表情工具，连接收集、编辑和使用。QQ ↔ 微信互通、随手素材、视频转 GIF、图文拼接与动效编辑，都在同一个工作空间里。

[选择下载](#下载与开始使用) · [功能详览](https://neo-sunxiaochuan.github.io/EmojiBridge/features.html) · [完整宣传片](https://neo-sunxiaochuan.github.io/EmojiBridge/docs/VIDEO.html) · [同款表情包](https://neo-sunxiaochuan.github.io/EmojiBridge/docs/MATERIALS.html) · [使用条件](https://neo-sunxiaochuan.github.io/EmojiBridge/docs/COMPATIBILITY.html)

[**☆ Star 支持项目**](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge) · **Created by Neo**

## 好梗，不必留在原地

选中一组表情，交给 EmojiBridge 转移。QQ 和微信可以双向互通；素材库里的图片、GIF，以及编辑完成的作品，也能加入收藏。

![同一个表情从 QQ 来源移向微信，再返回的交互示意](assets/bridge-loop.gif)

这是功能流程的视觉示意。实际运行需要本机登录客户端，并保持窗口可操作；微信通过本人的文件传输助手发送并添加表情，会占用文件传输助手的聊天上下文并产生消息记录；QQ通过本地导入收藏。支持范围见[兼容说明](https://neo-sunxiaochuan.github.io/EmojiBridge/docs/COMPATIBILITY.html)。

## 漫画配文与图文创作

漫画加一句神回复，多张图片拼出一个新梗。文字、基础图形、静态图与 GIF 可以一起组成画面；也可以套用模板、复用排版。

![漫画配文作品画廊：切换作品、对比原图和配字结果](assets/creation-board.png)

[打开交互画廊](https://neo-sunxiaochuan.github.io/EmojiBridge/index.html#create)：七组漫画配文，加上标签图与论战图。同一展示区也能切换到“评论区收集”，查看从抖音评论区拖入随手素材的过程。选择作品，查看配字前后，或展开大图读清每一句。

想知道具体能做什么？[功能详览](https://neo-sunxiaochuan.github.io/EmojiBridge/features.html)按收集、裁剪 GIF、抠主体、拼图、文字图形与模板、趣味动效、随手素材、导出互通八个方向展开，每组都有对应演示片段。

<details>
<summary><b>让表情更有戏：Q 弹、旋转、掉落物与传送</b></summary>

![Q弹动效实际演示](assets/bounce.gif)

调整动效参数，再导出自己的版本。视频可以选取片段、裁剪画面，转成聊天里能循环播放的 GIF。

</details>

## 做好了，顺手拖出去

从成品拖出区，把刚做好的图片或 GIF 拖到支持接收文件的聊天窗口或文件夹，减少保存后再翻找的步骤。[体验拖出示意](https://neo-sunxiaochuan.github.io/EmojiBridge/index.html#drag-out)。

经验瓶在处理完成后收起经验球，末影人陪表情走过搬运舞台。两套软件同款动效，也可以在[宣传页亲手播放](https://neo-sunxiaochuan.github.io/EmojiBridge/index.html#product-details)。

## 逛到哪，带到哪

随手素材浮在网页上方。喜欢的收进来，想用的拖出去；也可以贴在屏幕上，继续拖动、缩放。它是独立置顶窗口，不改变网页内容。

![随手素材及网页上方贴屏实录](assets/pocket.gif)

做好后，从成品拖出区域拖到支持接收文件的窗口，或加入 QQ / 微信收藏。

## 下载与开始使用

**S0174 · 下载 ZIP → 全部解压 → 双击 EB/EmojiBridge.exe。无需安装 Python。**

| 下载项 | 怎么选 |
| --- | --- |
| [轻量版 ZIP · 523.25 MB（推荐）](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-Windows-x64-lite.zip) | 自带默认自动抠图、基础编辑、视频/GIF、拖出与互通组件；更多模型和模板在设置中选装 |
| [完整离线版 ZIP · 1.35 GB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-Windows-x64-full.zip) | 另含动漫/精细抠图、tiny 字幕及模板扩展 |
| [宣传片同款表情包 · 707 MB](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0163/EmojiBridge-promo-assets-20261114.zip) | 独立可选，解压后多选导入 |
| [对应公开源码](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/EmojiBridge-S0174-public-source.zip) · [SHA256 校验](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge/releases/download/S0174/SHA256SUMS.txt) | 开发者或需要核验下载内容的用户 |

两版均包含默认 **自动／U²-Net** 模型，默认抠主体无需下载。轻量版可通过“设置 → 可选组件”下载并导入动漫/精细抠图、字幕或模板组件。缺少系统 WebView2 时，按启动提示安装微软官方组件。

**已整合 S0169—S0173 累计补丁和本次 QQ 路径、重新检测、窗口贴边处理修复，并保留 DLL 启动修复。** 保存作品并退出旧版，解压到新目录启动；保留个人素材和旧目录，不叠加旧补丁。自定义数据目录沿用原参数。故障外机仍需复测，不保证所有环境问题均已解决。

[安装、选装组件与完整升级说明](https://neo-sunxiaochuan.github.io/EmojiBridge/docs/DOWNLOADS.html)

<details>
<summary>第一次使用，从哪里开始？</summary>

先把几张自己的图片拖入素材库，试试编辑、保存和拖出。使用互通前，登录自己的 QQ、微信，按界面引导连接账号。读取 QQ 表情或执行互通时，不要移动鼠标、点击或切换窗口；等待任务完成后再操作。

</details>



## 使用前的小提醒

- **转入微信会使用文件传输助手**，占用其聊天上下文并产生相应消息记录。
- **读取 QQ 表情及执行互通时不要移动鼠标、点击或切换窗口**，等待任务完成后再操作。

## 支持 EmojiBridge

如果它帮你把好梗带到了想去的地方，欢迎 [点个 Star](https://github.com/NEO-SUNXIAOCHUAN/EmojiBridge)，支持 Neo 继续打磨。也欢迎带着具体使用场景来提建议。

## 作者与许可

Created by **Neo**。项目自有源码采用 **GPL-3.0-only**；第三方代码及素材保留各自许可与来源，表情包、音乐、漫画等不自动适用源码许可。

## 从源码运行与构建

Windows x64、带 Tk 的 Python 3.12 与 Microsoft WebView2。桌面入口还需要 `runtime/desktop` 中的桌面依赖；完整构建的组件准备与固定校验值见 [BUILDING.md](BUILDING.md)。公开源码与本版完整包对应，产品提交记录在 [SOURCE_BUILD.json](SOURCE_BUILD.json)。

详见 [功能说明](FEATURES.md)、[第三方声明](THIRD_PARTY_NOTICES.md)及[资源核对记录](RELEASE_RIGHTS.md)。
