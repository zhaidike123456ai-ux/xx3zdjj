# xx3zdjj

引导式本地口播精剪 Skill：分析气口、口误与重复，分阶段制作无字幕粗剪、同步字幕、人物蒙版和可编辑剪映工程。

支持英文项目目录、个人偏好、可复用资产和环境复用。视频默认在本地处理，保留已有项目和修改。

## 新手从这里开始

**[直接下载 Skill 压缩包](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest/download/xx3zdjj-skill.zip)** · **[完整安装与 Agent 使用教程](docs/GETTING_STARTED.md)** · **[查看发布版本](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest)**

适用于能读取本机文件、运行命令的本地 Agent，例如 Codex、Claude Code、Cursor Agent。

### 第一步：让 Agent 帮你安装（推荐）

**下面两个提示词选一个复制，不要同时发送。**

**项目级安装：用于当前项目。** 先在 Agent 中打开你的项目文件夹。

```text
请帮我安装 xx3zdjj 口播精剪 Skill：
https://github.com/zhaidike123456ai-ux/xx3zdjj

本次选择项目级安装，只用于当前项目，不做全局安装。
1. 确认当前 Agent、操作系统和项目根目录，按仓库安装教程选择正确的项目级位置；项目不明确时先让我指定。
2. 下载完整 Skill，包括脚本、素材和参考文档。已有同名版本先说明路径、版本和差异，保留我的修改，不直接覆盖。
3. 安装后验证能找到并读取所选位置的 xx3zdjj，检查资源完整，告诉我实际加载路径、版本和调用方法；需要开启新会话时请说明。
4. 检测运行依赖，已有可用环境直接复用。缺失项先说明来源、安装位置和预计空间，等我确认再补装。

本次先安装 Skill 和检查环境，不剪视频、不上传素材。
```

**全局安装：供本机多个项目使用。** 这里的“全局”指当前用户，不需要安装到系统目录。

```text
请帮我安装 xx3zdjj 口播精剪 Skill：
https://github.com/zhaidike123456ai-ux/xx3zdjj

本次选择全局安装，供本机多个项目使用。
1. 确认当前 Agent 和操作系统，按仓库安装教程放入该 Agent 支持的用户级技能目录，不写系统目录，也不额外安装到当前项目。
2. 下载完整 Skill，包括脚本、素材和参考文档。已有同名版本先说明路径、版本和差异，保留我的修改，不直接覆盖。
3. 安装后验证能找到并读取所选位置的 xx3zdjj，检查资源完整，告诉我实际加载路径、版本和调用方法；需要开启新会话时请说明。
4. 检测运行依赖，已有可用环境直接复用。缺失项先说明来源、安装位置和预计空间，等我确认再补装。

本次先安装 Skill 和检查环境，不剪视频、不上传素材。
```

目录和安装参数交给 Agent 按 [安装教程](docs/GETTING_STARTED.md) 处理。

### 第二步：确认安装成功

Agent 应告诉你实际加载路径、版本和调用方法，并确认符合所选安装范围：项目级在当前项目内，全局安装在该 Agent 的用户级技能目录。若未找到，先开新会话（项目级需在同一项目）；仍有问题，让 Agent 按 [教程排查](docs/GETTING_STARTED.md#7-常见问题)。

### 第三步：发原视频，开始使用

把视频拖入支持本机附件的 Agent，或把下面的示例路径换成你自己的绝对路径，再发送：

```text
使用 xx3zdjj 处理我的口播。
原视频：这里填写原视频的绝对路径，或者使用我刚附上的原视频。
逐字稿：有就粘贴在这里；没有请用本地模型转写。

先检查环境并建立项目。分析整条视频的气口、口误和重说，给我拟删除的时间段、保留内容和预计时长，暂时不要直接剪。
重复的字、词、半句或整句，只保留最后一次完整表达；拿不准的先给我原音试听。等我确认方案后再剪，不要吞字。
```

想显式选择技能时：Codex 输入 `$xx3zdjj`；Claude Code 输入 `/xx3zdjj`；Cursor 在 Agent 聊天里输入 `/` 选择 `xx3zdjj`。各产品目录、手动解压步骤和故障排查见 [完整新手教程](docs/GETTING_STARTED.md)。普通用户不需要填写内部 JSON，也不需要自己组织 FFmpeg 命令。

---

## 第一次使用

提供本地原片，可附逐字稿。助手会依次引导：

1. 检查 Python、FFmpeg/FFprobe、faster-whisper、本地模型、Node.js、Remotion 和 HyperFrames，复用可用环境。
2. 创建独立项目，解释各文件夹的用途，核对视频与稿件的对应关系。
3. 给出拟删除时间段、保留表达与预计时长；疑点提供原音试听。
4. 按授权精剪并检查，交完整无字幕预览；确认后制作字幕，再确认人物蒙版与背景。
5. 完整 MP4 确认后才制作剪映工程，分别核对结构、打开、编辑、保存重开和原生导出。

缺失依赖会先说明来源、位置和空间，按用户已有授权补装。环境、模型与授权记录保存在本机用户目录，后续复用；不会随 Skill 复制到别人电脑。新装全部依赖约需 3.8 GB，另需缓存及视频处理空间，实际以检测结果为准。见 [环境准备](references/runtime.md)。

只做一次检测时，在 Skill 根目录运行：

```bash
# macOS；只读，不下载
bash scripts/bootstrap.sh check
```

```powershell
# Windows；不更改系统脚本执行策略
.\scripts\bootstrap.ps1 check
```

已完成环境准备后，媒体命令通过 `runtime_manager.py exec` 使用检测通过的工具；必需参数由助手填写，普通用户无需编写时间线 JSON。

## 多智能体协作

进入视频处理后，Skill 会先核对当前会话的子智能体能力。有独立任务且工具可用时，主动创建子智能体进行气口/重说分析、当前阶段的检查及产物独立质检，无需每次追加提示。主代理统一时间线与文件写入，保留逐阶段确认。

安装检查和简单问答不强行分派。宿主不提供工具或创建失败时，会说明原因并顺序处理，标明未完成独立子智能体验收。Skill 不能替宿主开启未提供的能力，文字角色扮演不算真实委派。详见 [协作规则](references/multi-agent.md)。

已经安装旧版的用户需先更新 Skill，并核对实际加载的版本；GitHub 更新不会自动修改本机副本。同名修改先保留，必要时在同一项目开启新会话。

## 项目、偏好与资产

默认工作室目录为用户 Documents 下的 `talking_head_studio`，可另行指定。生成文件夹使用英文名，中文标题保存在项目记录中；不改用户原文件名。

```text
talking_head_studio/
├── preferences/                 # 已确认偏好与反馈候选
├── assets/                      # 背景、字幕样式、布局与动效
└── projects/
    └── YYYYMMDD_project_name/
        ├── 00_project_info/     # 项目说明、设置和确认记录
        ├── 01_inputs/           # 原片引用、逐字稿与素材副本
        ├── 02_analysis/         # 分析和剪辑计划
        ├── 03_edit_data/        # 剪辑映射、词时间与字幕
        ├── 04_previews/         # 各版本完整预览
        ├── 05_jianying/         # 剪映工程
        ├── 06_deliverables/     # 已验收成果
        └── 90_logs_cache/       # 日志和缓存
```

本次选择优先；多次反馈先记为候选，明确要求“以后都这样”才成为长期默认。素材库去重，项目保留固定副本；文件或上游内容变化后，旧确认会失效。详见 [项目与资产](references/studio.md)。

## 能力与边界

| 项目 | 当前状态 |
| --- | --- |
| 单字、词、半句、整句重说 | 生成候选，结合原音和授权处理；不把正常强调自动删掉 |
| 本地转写、SRT/ASS、字幕匹配 | 已实现；机器对齐不等于人耳听校通过 |
| 圆形/圆角方形完整预览 | 已实现，字幕与背景独立处理 |
| 网格移动 | 支持左右移动，速度由本次选择确定，默认静止 |
| 剪映原生候选 | 当前实现圆形蒙版；圆角方原生参数仍需实机适配 |
| 原片级恢复已删内容 | 未实现；`approved-clean` 基于批准后的精剪媒体再分段 |
| PR/FCP 通用转换 | 未实现；需按具体应用能力另行适配 |
| macOS | ARM64 本地验证；其他架构/软件版本仍需实际核验 |
| Windows | x64 环境与工程分支已有实现，实机安装/剪映 UI 尚未验收；ARM64 自动补装暂阻断 |

剪映版本可能影响兼容性。静态检查通过不等于目标电脑已完整打开、可编辑、重开和导出通过。详见 [剪映适配](references/jianying.md) 与 [验收说明](references/testing.md)。

## v2.1.1：修复测量边界与分窗异常

静音时间统一转换到合法媒体范围，保留原始测量和裁剪差值；解码音频与媒体时长异常偏差会单独提示。零时长词不再导致整窗正常词丢失，完整原始输出与异常词均保留；时间覆盖、多尺度完成和质量状态分开记录。不会通过降低门禁让流程继续。详见 [检测与警报处理](references/speech-review.md)。

本次用真实原片复现了“上”的零时长，保留了另外 9 个正常词；原片 hash 未改变。新增真实合成媒体的分析→粗剪→残留复核→字幕入口测试，覆盖证据齐备生成 SRT，以及缺证据、缺确认和旧版本仍阻断。具体平台、数量与结果见 [发布说明](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/tag/v2.1.1)。Windows 文本夹具明确 UTF-8，尚未宣称 Windows 实机验收。

v2.1.0 的默认重说检测、有效开场分窗、警报传递与阶段确认继续保留。更新后重新生成受影响的检测报告和相应证据引用，不能手工把旧警报改成通过；无需因为修复测量坐标而重剪已确认的媒体。Skill 更新不会自动修改已有视频，下载包不包含私人素材。

## 开发与测试

v2.0.0 发布前在 macOS ARM64 完成 73 项单元/合成媒体回归，另有短重说检测与字幕连接自检。模型合成推理证明入口可执行，不代表真人口误识别准确率。没有把私人测试视频或本机审计记录放入仓库。

仅用 Python 3.11 标准库运行轻量测试，不下载模型或视频：

```bash
cd scripts
python -B -S -m unittest test_runtime test_studio_manager test_stage_gate test_review_state test_opening_review test_silence_media_bounds test_retake_pipeline test_review_pipeline test_retake_detection test_jianying_adapter test_media_quality.TextQualityTests
python -B -S test_retake_detection.py
```

早期 v2.0.0 的轻量套件为 62 项，另有 9 个重说检测用例。新版增加开场分窗、默认策略、警报闭环、版本绑定和帧对齐保护回归；实际测试数量与结果见对应 Release。完整媒体测试还需要带 `ass` 滤镜的 FFmpeg、FFprobe、Pillow 和本机字体：

```bash
python -B -m unittest discover -s scripts -p 'test_*.py'
```

完整套件从仓库根运行。没有媒体依赖时可能跳过部分用例，不能将跳过记作媒体验收通过。

提交问题时请描述系统、软件版本、复现步骤及脱敏错误；不要上传原片、凭证或本机授权记录。贡献改动请同时说明验证范围。

## 许可证与致谢

本项目代码和文档采用 [MIT License](LICENSE)。剪映模板来自 [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)，保留原 [Apache-2.0 许可证](assets/jianying/LICENSE) 和来源记录。

运行环境、模型、字体、Remotion、HyperFrames 等外部依赖不包含在发布包内，分别遵循其自身许可；例如 [Remotion License](https://www.remotion.dev/license)，不因本项目采用 MIT 而改变。完整说明见 [第三方说明](THIRD_PARTY_NOTICES.md)。
