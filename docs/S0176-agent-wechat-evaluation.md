# agent-wechat 候选评估（2026-11-16）

本轮只审阅固定提交 b110ce531306a381618fe902bc3b7b853c000a92，没有安装运行、登录账号或把它接进 EmojiBridge。

它值得作为后续独立适配候选，但并不是给 UIA 补一个插件：它自行维护账号会话并直接通信。其协议库针对 Linux 4.1.13.26 的 Profile；不能拿现有 Windows 微信的数据目录直接替换。读取、登录和退出的职责都会发生变化。[协议说明](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/packages/native-client-rust/crates/wechat-protocol/README.md)

自动添加自定义表情有实际代码：上传分块校验进度和内容身份，添加与聊天发送分开，任务保存提交标记和回执，再对照收藏列表确认结果。因此它可能减少窗口、主题、缩放对添加的影响；这只是架构判断，不是 EB 的性能实测。[上传](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/packages/native-client-rust/crates/wechat-protocol/src/sticker_upload.rs)、[收藏列表及变更](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/packages/native-client-rust/crates/wechat-protocol/src/custom_stickers.rs)、[持久任务](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/packages/native-client-rust/crates/wechat-core/src/sticker_jobs.rs)

若另行采用，应单独提供用户启用和登录入口，适配“准备原件→添加任务→查询回执”，保留账号隔离、取消与未知结果不重发。不得复用 Windows 登录状态作未验证的假设，也不能把本地添加成功当成手机端同步完成。先验证 Windows 发行程序、独立账号登录退出、静图/GIF 添加与手机同步，再决定是否成为可选目标适配器。现有 UIA/MSAA→必要步骤视觉路线保持。

README 明确现有官方 Profile 复用面向受支持的 Linux 数据布局；Daemon 使用期间需关闭官方客户端，交接回官方应用仍有未验证范围。不能据此承诺不掉线、不触发账号限制，亦没有证据给出封号概率。[README](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/README.zh-CN.md)

根许可证为 MIT；本轮未复制代码或二进制。真正分发时仍需随依赖核对并保留各自许可。TXT 引用的 PLATFORM-ACCEPTANCE.md 在该固定提交返回 404；平台发行说明实际在 RELEASING.md，不能把无效链接视为验收证据。[LICENSE](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/LICENSE)、[发行流程](https://github.com/thisnick/agent-wechat/blob/b110ce531306a381618fe902bc3b7b853c000a92/RELEASING.md)

OhMyMeme 参考范围：目录读取和更新器流程仅作设计参考；静态相似图的灰度/DCT pHash 函数按 GPL-3.0 改编，来源及改动已登记 THIRD_PARTY_NOTICES.md。没有引入整套 OMM、自动清理原文件或复制后收起窗口的行为。
