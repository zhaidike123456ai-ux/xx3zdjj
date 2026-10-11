# xx3zdjj

引导式本地口播精剪 Skill：分析气口、口误与重复，分阶段制作无字幕粗剪、同步字幕、人物蒙版和可编辑剪映工程。

支持英文项目目录、个人偏好、可复用资产和环境复用。视频默认在本地处理，不自动上传、购买服务或覆盖其他项目。

## 安装

需要能读取 Skill 并执行本机命令的 AI 助手。以下以 Codex 为例；仓库根目录就是 Skill 根目录。克隆只安装 Skill 文件，不包含运行环境、语音模型或用户素材。

已有同名目录时先保留修改并对比版本；下面的命令会停止，不覆盖旧版。

### macOS

在终端执行（需要 Git）：

```bash
skill_target="${CODEX_HOME:-$HOME/.codex}/skills/xx3zdjj"
if [ -e "$skill_target" ] || [ -L "$skill_target" ]; then
  echo "目标已存在，请先保留旧版并检查差异：$skill_target"
else
  mkdir -p "$(dirname "$skill_target")"
  git clone https://github.com/zhaidike123456ai-ux/xx3zdjj.git "$skill_target"
fi
```

### Windows

在 PowerShell 执行（需要 Git）：

```powershell
$skillRoot = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
$skillTarget = Join-Path $skillRoot 'xx3zdjj'
if (Test-Path -LiteralPath $skillTarget) { throw "目标已存在，请先保留旧版并检查差异：$skillTarget" }
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
git clone https://github.com/zhaidike123456ai-ux/xx3zdjj.git "$skillTarget"
if ($LASTEXITCODE -ne 0) { throw 'Git clone 失败，请查看上方错误。' }
```

也可以下载 [Release](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases) 中的 Skill 压缩包，把其中的 `xx3zdjj` 文件夹放到上述 skills 目录。不要合并覆盖已有修改。

如果当前会话尚未发现 Skill，开启新会话后输入：

> 用 xx3zdjj 处理这条口播，先分析气口、口误和重说，暂时不要剪。

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
