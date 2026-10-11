# 下载、安装和在 Agent 中使用 xx3zdjj

**最省事的方法：打开你已经在用的本地 Agent，把 [首页安装提示词](../README.md#第一步让-agent-帮你安装推荐) 整段发给它。** 它负责下载、放入技能目录、核对文件和检查依赖。

如果想手动安装，下面从零开始操作。下载 Skill 免费且不需要 GitHub 账号；所用 AI Agent、剪映或第三方依赖遵循各自的账号和许可规则。

## 1. 先确认你用什么 Agent

本 Skill 要运行本地转写、FFmpeg 和项目管理脚本，所以 Agent 需要能读取你的原片、写入输出目录，并按你的授权运行本机命令。请使用本地执行环境，给它开放本次项目所需的文件夹；无需开放整台电脑或关闭系统保护。

| 你使用的工具 | 安装后的调用方法 | 说明 |
| --- | --- | --- |
| 本地 Codex | `$xx3zdjj` 后接需求，或说“使用 xx3zdjj” | 可用 `$skill-installer` 从 GitHub 安装 |
| 本地 Claude Code | `/xx3zdjj` 后接需求 | 安装到个人或项目技能目录 |
| 本地 Cursor Agent | 输入 `/` 搜索并选择 `xx3zdjj`，或明确要求使用 | 使用可以运行终端工具的 Agent 会话 |
| 其他支持 Agent Skills 的本地 Agent | 按该产品的技能入口选择；或明确指名 | 先核对该产品的技能目录与执行能力，不猜安装路径 |
| 仅能聊天、不能读取本机文件或运行命令的网页会话 | 不适用于直接在你的电脑上剪辑 | 上传 ZIP 只能提供文件，不会自动安装到你的电脑 |

目录与调用方式核对自 [OpenAI 官方文档](https://learn.chatgpt.com/docs/build-skills)、[Claude Code 官方文档](https://code.claude.com/docs/en/skills)、[Cursor 官方文档](https://cursor.com/docs/skills)。读取 Skill 的兼容性不代表整个媒体流程已在这些宿主上逐一实测；当前验证范围见 [能力与边界](../README.md#能力与边界)。

## 2. 下载完整 Skill

1. 点击 **[直接下载 xx3zdjj-skill.zip](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest/download/xx3zdjj-skill.zip)**。
2. 或打开 [最新 Release](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest)，在 **Assets** 区域找到 `xx3zdjj-skill.zip`。
3. macOS 双击 ZIP；Windows 右键 ZIP，选择“全部解压”。不要在压缩包浏览窗口中直接使用。
4. 找到里面直接包含 `SKILL.md`、`scripts`、`references` 和 `assets` 的 **xx3zdjj** 文件夹。

如果用了 GitHub 首页的 **Code → Download ZIP**，解压出来可能叫 `xx3zdjj-main`。找到直接包含 `SKILL.md` 的那一层，把它改名为 `xx3zdjj` 后再安装。GitHub 的自动 Source code ZIP 也按这个方法处理。不要只下载网页上的单个 `SKILL.md`。

发布包已经含有默认黑色网格、剪映模板与所有操作参考；Python、模型、FFmpeg、剪映软件本体不在 ZIP 里。系统字体也不会随包分发，首次字幕阶段会选择本机可用字体。

## 3. 把文件夹放到正确的位置

以下是默认的个人技能目录，装一次可供本机多个项目使用。公司策略或宿主安装器指定了不同位置时，以它实际确认支持的位置为准；不要在多个目录重复安装同名 Skill。

| Agent | macOS 的完整 Skill 路径 | Windows 原生环境的完整 Skill 路径 |
| --- | --- | --- |
| Codex（按当前官方目录） | `~/.agents/skills/xx3zdjj/` | `%USERPROFILE%\.agents\skills\xx3zdjj\` |
| Claude Code | `~/.claude/skills/xx3zdjj/` | `%USERPROFILE%\.claude\skills\xx3zdjj\` |
| Cursor | `~/.cursor/skills/xx3zdjj/` | `%USERPROFILE%\.cursor\skills\xx3zdjj\` |

`~` 代表当前运行 Agent 的用户主目录；Windows 文件资源管理器地址栏会展开 `%USERPROFILE%`。Codex 内置安装器或已有版本可能使用 `$CODEX_HOME/skills`（常见为 `~/.codex/skills`）；如果安装器已经确认在那里可用，保留该位置，不要为了这张表另装一份。目录依据：[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code](https://code.claude.com/docs/en/skills)、[Cursor](https://cursor.com/docs/skills)。

**macOS：**在 Finder 中按 `Command + Shift + G`，输入表中路径的父目录，例如 `~/.agents/skills/`。不存在时可让 Agent 创建；将完整的 `xx3zdjj` 文件夹放入。隐藏文件夹不是错误，不必修改系统显示设置。

**Windows：**在文件资源管理器地址栏输入父目录，例如 `%USERPROFILE%\.agents\skills`。不存在时新建对应文件夹，再复制完整的 `xx3zdjj` 文件夹。

**WSL、远程 SSH 或云端会话：**路径属于 Agent 真正执行命令的那台机器或环境，不一定是 Windows 桌面用户目录。请让 Agent 先报出执行环境与实际用户主目录。该 Skill 的自动补装主要针对 macOS 和 Windows x64，不把 WSL/Linux 或云端当成已经验收的本机环境，也不自动上传原片迁就云端。

正确结构：

```text
skills/
└── xx3zdjj/
    ├── SKILL.md
    ├── scripts/
    ├── references/
    ├── assets/
    ├── agents/
    ├── docs/
    └── README.md
```

错误示例是 `skills/xx3zdjj/xx3zdjj/SKILL.md`，或目录里只有 `SKILL.md`、没有脚本和素材。如果目标已经存在，请保留旧版并比较修改，不要选择“全部替换”。

### 有 Git 时的可选安装方法

不想手动解压，可以让 Agent 执行 Git 克隆。下面以当前 Codex 目录为例，其他产品按上表更改目标目录。

macOS 终端：

```bash
skill_target="$HOME/.agents/skills/xx3zdjj"
if [ -e "$skill_target" ] || [ -L "$skill_target" ]; then
  echo "目标已存在，请先保留旧版并检查差异：$skill_target"
else
  mkdir -p "$(dirname "$skill_target")"
  git clone https://github.com/zhaidike123456ai-ux/xx3zdjj.git "$skill_target"
fi
```

Windows PowerShell：

```powershell
$skillRoot = Join-Path $HOME '.agents/skills'
$skillTarget = Join-Path $skillRoot 'xx3zdjj'
if (Test-Path -LiteralPath $skillTarget) { throw "目标已存在，请先保留旧版并检查差异：$skillTarget" }
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
git clone https://github.com/zhaidike123456ai-ux/xx3zdjj.git "$skillTarget"
if ($LASTEXITCODE -ne 0) { throw 'Git clone 失败，请检查网络与上方错误。' }
```

不要为了运行这些示例覆盖系统环境变量。没有 Git 时直接使用 ZIP，不必先安装 Git。

## 4. 让 Agent 确认能用

安装后发送：

```text
请检查你能否发现名为 xx3zdjj 的 Skill，读取它的 SKILL.md。
告诉我真实安装路径，确认 scripts、references、assets 都齐全。
本次只做环境检测，列出哪些能用、哪些缺失，不开始处理视频。
```

如果没有识别，开新会话后重试；仍没有时重启 Agent，再检查目录、技能启用状态及公司策略。安装器本身可能支持立即发现，能找到时无需反复重启。

如果某个 Agent 没有 Skill 自动发现功能，但能访问本地文件和运行命令，可以发送下面这段临时加载提示词：

```text
请读取这里的 SKILL.md：这里填写解压后 SKILL.md 的绝对路径。
把它作为本次 xx3zdjj 口播工作流程，按所在文件夹解析 scripts、references、assets 等相对路径。
先确认能读取完整资源并进行只读环境检查，不要剪视频。
```

这是当前会话的显式加载，不代表已经注册为该产品的全局技能。若 Agent 不能读这个路径或不能运行命令，需要改用有这些能力的本地环境。

## 5. 第一次准备依赖

Agent 会一起检查 Python、FFmpeg/FFprobe、faster-whisper、本地语音模型、Node.js、Remotion 和 HyperFrames，不要求你先选是否制作动效。已有可用的直接复用。全新机器可能需要约 3.8 GB，再加缓存和视频处理空间；具体报告以本机检测为准。

确认缺失清单后，可回复：

```text
同意按刚才说明的来源、位置和空间，补齐缺失的本地依赖。
已有可用的不要重装。保存在用户级隔离目录，不覆盖其他项目，不自动付费或上传我的视频。
安装后做小测试并告诉我结果。
```

环境与模型保存在 Skill 文件夹之外，同一台电脑后续调用会先检测并复用。安装授权只作用于本机，不会因为你把 Skill 给朋友就自动转移给他。

## 6. 真正开始剪辑

可以发送自然语言，也可以在前面加对应宿主的技能调用标记。

Codex 示例（路径是占位示例，需要换成你的原片）：

```text
$xx3zdjj
原视频：/Users/your_name/Movies/take01.mp4
逐字稿：我会紧接着粘贴；如果没有稿，请先本地转写。

先分析整条视频的气口、口误和重说，列出拟删除的原片时间段、保留内容、理由和预计成片时长，暂时不要直接剪。
重复的字、词、半句或整句只保留最后一次完整表达，拿不准的先给我原音试听，不要吞字。
```

Windows 原片可以写成 `C:\Users\your_name\Videos\take01.mp4`。输入中文文件名和带空格的完整路径可以保留，交给 Agent 正确引用。附件也必须能被当前本地 Agent 读取；不要把别人的示例路径原样复制使用。

Claude Code 可把第一行换成 `/xx3zdjj`；Cursor 可在 Agent 聊天中输入 `/` 后选中 `xx3zdjj`。通用写法是“使用 xx3zdjj 处理我刚发的原视频”。调用语法来源：[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code](https://code.claude.com/docs/en/skills)、[Cursor](https://cursor.com/docs/skills)。

你会先看到环境报告和剪辑计划。确认后给完整无字幕预览；粗剪确认后做字幕；字幕确认后选择人物形状与画布背景；完整 MP4 确认后再做剪映工程。每次修改都给完整新版预览。你无需自己填写工程 JSON 或编写媒体命令。

成果位置由 Agent 给出可打开的绝对路径。默认工作室中的 `04_previews` 放预览、`05_jianying` 放工程、`06_deliverables` 放已验收交付。

## 7. 常见问题

| 问题 | 怎么处理 |
| --- | --- |
| 下载链接打不开 | 打开 [Release 页面](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest) 的 Assets；仍打不开先解决 GitHub 网络访问 |
| 提示没有 Git | 用 ZIP 手动安装，或把已下载 ZIP 的本地路径发给 Agent |
| Agent 找不到 Skill | 核对宿主、执行机器、目录层级和 SKILL.md；开新会话或重启；已有同名版本先消除歧义 |
| Agent 只解释步骤、不执行 | 确认会话有本地文件和终端工具，并允许它访问本次项目；如果没有执行能力，换合适的本地 Agent |
| Skill 找到了，但转写/导出失败 | 让 Agent 跑环境检查和小测试；不要把“安装成功”当成所有运行环境都准备好了 |
| Windows 禁止执行 ps1 | 不关闭系统保护；让 Agent 在现有允许的环境用兼容 Python 运行检查，或按本机管理策略解决 |
| 想做剪映工程 | 同机需装剪映；先确认完整 MP4，再按该版本做兼容测试与真实界面验收 |
| 想升级 | 让 Agent 比较新旧版本并先保留个人修改；环境、模型、项目和偏好不用删，不盲目强制覆盖 |

当前原生圆角方、原片级恢复、Windows 实机与剪映 UI 的验证边界详见 [README](../README.md#能力与边界)。本教程提供宿主的安装/调用方法，不把未实测的完整后期流程宣称为全平台通过。
