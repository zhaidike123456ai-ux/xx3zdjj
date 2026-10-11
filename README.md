# xx3zdjj

引导式本地口播精剪 Skill：分析气口、口误与重复，分阶段制作无字幕粗剪、同步字幕、人物蒙版和可编辑剪映工程。

支持英文项目目录、个人偏好、可复用资产和环境复用。视频默认在本地处理，不自动上传、购买服务或覆盖其他项目。

## 新手从这里开始

**[直接下载 Skill 压缩包](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest/download/xx3zdjj-skill.zip)** · **[完整安装与 Agent 使用教程](docs/GETTING_STARTED.md)** · **[查看发布版本](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest)**

这是给 **能读取本机文件、执行本机命令的 AI Agent** 使用的 Skill，例如本地 Codex、Claude Code、Cursor Agent。普通网页聊天里上传 ZIP，不等于安装到本机。先准备好你自己的 Agent；剪映工程验收还需要在同一台电脑上安装剪映。

### 第一步：让 Agent 帮你安装（推荐）

先在 Agent 中打开准备剪视频的项目文件夹，再把下面整段复制到聊天框。**默认安装到当前项目，不做全局安装**：

```text
请把 xx3zdjj Skill 安装到我当前打开的项目中：
https://github.com/zhaidike123456ai-ux/xx3zdjj

先识别当前 Agent、操作系统和当前项目根目录，说明项目根的绝对路径。若未打开项目或有多个候选目录，先让我指定，不把下载目录当项目。
采用该 Agent 实际支持的项目级技能目录：Codex 通常为 <项目根>/.agents/skills/xx3zdjj，Claude Code 为 <项目根>/.claude/skills/xx3zdjj，Cursor 为 <项目根>/.cursor/skills/xx3zdjj。其他 Agent 请先核对官方支持的位置；不支持项目级时先说明，不改成全局安装。
仓库根目录就是 Skill 根目录。下载完整内容，包括 SKILL.md、scripts、references、assets 等，放入名为 xx3zdjj 的文件夹，不多套一层目录。
不要写入用户级或系统级技能目录。若使用安装器，必须显式指定项目内的目标目录，不能使用它的全局默认位置。
检查项目内及会被当前 Agent 加载的其他位置是否已有同名 Skill；有则先说明路径、版本和差异，保留我的修改，不覆盖或删除已有版本。
安装后检查资源完整，并在当前项目会话中验证能发现和读取项目内这一份 xx3zdjj，告诉我实际加载路径、版本和调用方法；若有同名冲突或需要开启新会话，请说明。
本次只安装 Skill 并只读检测依赖，不补装工具或模型。已有可用环境直接复用；缺失项列出来源、安装位置和预计空间，等我确认再补装。不要上传我的视频、自动付费或开始剪辑。
```

项目级 Skill 用于该项目及宿主支持的子目录范围；换到其他项目时不会因此新增全局 Skill。想供本机多个项目共用，可主动选择教程中的 [可选全局安装](docs/GETTING_STARTED.md#可选全局安装)。

Codex 可让 `$skill-installer` 执行，但必须指定项目目录。安装器支持时使用 `--repo zhaidike123456ai-ux/xx3zdjj --path . --name xx3zdjj --dest "<项目根>/.agents/skills"`，其中 `--dest` 是 **skills 父目录**，末尾不再加 `xx3zdjj`；让 Agent 根据当前安装器的帮助信息执行。Codex 的项目目录依据：[官方说明](https://learn.chatgpt.com/docs/build-skills)。

### 第二步：确认安装成功

让 Agent 回答：“你是否能在当前项目中找到 xx3zdjj？请读取项目内这一份的 SKILL.md，给出真实加载路径和版本，并说明有无其他同名副本。”

安装后的文件夹应是下图结构，**不能只下载 SKILL.md，也不要多套一层 xx3zdjj 文件夹**：

```text
当前项目的技能目录/
└── xx3zdjj/
    ├── SKILL.md
    ├── scripts/
    ├── references/
    ├── assets/
    └── agents/
```

若未发现，先在同一项目开新会话；仍没有时检查目录或重新启动 Agent。项目级安装限定 Skill 的位置，依赖与成片目录单独管理：工具和模型默认按授权放在本机用户级隔离目录，作品默认放在 Documents/talking_head_studio。“Skill 已安装”不代表模型和 FFmpeg 已安装。详见 [安装范围说明](docs/GETTING_STARTED.md#skill依赖与作品的位置分别管理)。

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

## 开发与测试

v2.0.0 发布前在 macOS ARM64 完成 73 项单元/合成媒体回归，另有短重说检测与字幕连接自检。模型合成推理证明入口可执行，不代表真人口误识别准确率。没有把私人测试视频或本机审计记录放入仓库。

仅用 Python 3.11 标准库运行轻量测试，不下载模型或视频：

```bash
cd scripts
python -B -S -m unittest test_runtime test_studio_manager test_stage_gate test_jianying_adapter test_media_quality.TextQualityTests
python -B -S test_retake_detection.py
```

上述轻量套件在 macOS 上实跑 62 项通过，另 9 个重说检测用例通过。完整媒体测试还需要带 `ass` 滤镜的 FFmpeg、FFprobe、Pillow 和本机字体：

```bash
python -B -m unittest discover -s scripts -p 'test_*.py'
```

完整套件从仓库根运行。没有媒体依赖时可能跳过部分用例，不能将跳过记作媒体验收通过。

提交问题时请描述系统、软件版本、复现步骤及脱敏错误；不要上传原片、凭证或本机授权记录。贡献改动请同时说明验证范围。

## 许可证与致谢

本项目代码和文档采用 [MIT License](LICENSE)。剪映模板来自 [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft)，保留原 [Apache-2.0 许可证](assets/jianying/LICENSE) 和来源记录。

运行环境、模型、字体、Remotion、HyperFrames 等外部依赖不包含在发布包内，分别遵循其自身许可；例如 [Remotion License](https://www.remotion.dev/license)，不因本项目采用 MIT 而改变。完整说明见 [第三方说明](THIRD_PARTY_NOTICES.md)。
