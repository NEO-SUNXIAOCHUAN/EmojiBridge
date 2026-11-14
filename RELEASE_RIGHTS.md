# 首发资源核对状态

本文件针对 S0163 本地首发候选。GPLv3 适用于 Neo 有权授权的原创源码，
不替代第三方许可。本次尚未上传 GitHub。

| 项目 | 当前分发方式 | 核对结果 |
| --- | --- | --- |
| 微信提取 wechat_meme_export | 原样复制 memory.py / decrypt.py | MIT 原文、固定提交与文件 SHA 在 third_party/wechat_meme_export |
| export-wechat-emoji | 阅读格式/参数参考，未复制其 Rust 包 | 固定 Cargo.toml 声明 MIT；固定树无独立 LICENSE，不宣称分发其源码 |
| Windows-MCP | 小范围改编前台线程关联方法 | MIT 原文及 SOURCE.json 保留；未引入上游 UIA 服务 |
| Python / Tk / Python 依赖 | 随软件运行时分发 | 保留各 distribution 元数据和原许可；具体版本见 BUILD.json |
| React / Motion / Radix / Lucide / Glass | 前端 bundle | assets/desktop/THIRD_PARTY.txt；前端锁文件保留 |
| Twemoji 既有初始素材 | PNG / GIF / 可编辑示例 | CC BY 4.0，来源及改编记录在 assets/examples |
| 四张经典 Meme | 仅独立宣传素材包，不在软件或源码包 | 独立素材包的来源/许可单独核对 |
| meme-generator / contrib | 完整包或单独模板扩展 | 引擎 MIT；不等于模板插画/字体全部获得再分发授权，逐素材授权仍待核 |
| 像素音效、末影人及品牌相关美术 | 现有动效资源 | 用户提供与来源记录保留；第三方声音/游戏美术公开再分发授权尚待核 |
| FFmpeg | S0167 独立离线测试候选包含固定 Gyan 构建 | GPLv3 构建及来源见 third_party/FFmpeg-NOTICE.md；公开分发前完整对应源码及外部库义务仍待核，不将上游链接当作完成 |
| 抠图模型 | 不随软件包分发，按需取得或校验导入 | 权重与代码许可分开，详见 third_party/cutout/NOTICE.md |
| OCR / CSRT | 随视觉运行时分发 | 锁定依赖、三个 OCR 模型及原许可，见 third_party/factory/vision-runtime-lock.json |
| 已移除照片视差/人物宠物 | 不提供产品入口，不捆绑运行时/权重 | 保留历史许可文本不等于重新启用；指定14模板排除表保留 |

**公开发布前仍需解决**：软件中模板插画/字体及上述声音/美术的分发依据；独立素材包另行核对。
当前完整功能候选保留这些资源以供本地验收，不能标成“全部资源已完成公开许可审核”。
可选择补齐授权，或另行批准将未明确授权资源从公开下载中移除；不静默删掉现有功能或用户作品。
