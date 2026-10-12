# 下载、安装和在 Agent 中使用 xx3zdjj

**最省事的方法：在 [首页安装提示词](../README.md#第一步让-agent-帮你安装推荐) 中，选择“项目级安装”或“全局安装”，只复制对应的一段发给本地 Agent。** 项目级安装前先打开目标项目文件夹；全局安装使用当前 Agent 的用户级目录，供本机多个项目使用。Agent 会按所选范围安装、核对文件并检查依赖。

如果想手动安装，下面从零开始操作。公开仓库的安装包无需 GitHub 账号即可下载。

## 1. 先确认你用什么 Agent

本 Skill 要运行本地转写、FFmpeg 和项目管理脚本，所以 Agent 需要能读取你的原片、写入输出目录，并按你的授权运行本机命令。请使用本地执行环境，给它开放本次项目所需的文件夹；无需开放整台电脑或关闭系统保护。

| 你使用的工具 | 安装后的调用方法 | 说明 |
| --- | --- | --- |
| 本地 Codex | `$xx3zdjj` 后接需求，或说“使用 xx3zdjj” | 可用 `$skill-installer` 从 GitHub 安装，须显式指定项目内目标 |
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

### 默认安装到当前项目

先在 Agent 中打开要剪辑的项目文件夹，让它报告项目根的绝对路径。项目根是你正在工作的文件夹，不是解压的 Skill 源码目录，也不一定是终端当前所在目录。没有打开项目或多根工作区中有多个候选时，先选定一个项目再安装。

下表的 `<项目根>` 需要替换成刚确认的实际路径。**不要把项目路径换成 `~` 或 `%USERPROFILE%`**，那会变成用户级安装。

| Agent | macOS 项目内完整 Skill 路径 | Windows 原生项目内完整 Skill 路径 |
| --- | --- | --- |
| Codex | `<项目根>/.agents/skills/xx3zdjj/` | `<项目根>\.agents\skills\xx3zdjj\` |
| Claude Code | `<项目根>/.claude/skills/xx3zdjj/` | `<项目根>\.claude\skills\xx3zdjj\` |
| Cursor | `<项目根>/.cursor/skills/xx3zdjj/` | `<项目根>\.cursor\skills\xx3zdjj\` |

这些项目目录由宿主在相应项目范围发现，子目录加载规则以宿主为准。不要笼统承诺“项目版一定优先”：Codex 同名副本可能同时出现，Claude Code 的个人同名技能可能优先于项目版。安装前检查当前项目和宿主会加载的其他位置，报告已有同名版本，保留它们；验收时核对**实际读取的是项目内哪一个 SKILL.md**。有冲突时先说明解决办法，不擅自删除或更名用户的旧技能。目录与同名规则依据：[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code](https://code.claude.com/docs/en/skills)、[Cursor](https://cursor.com/help/customization/skills)。

**macOS：**在 Finder 中按 `Command + Shift + G`，输入项目内的 skills 父目录。例如项目是 `/Users/your_name/Movies/my_project`，Codex 的父目录就是 `/Users/your_name/Movies/my_project/.agents/skills`。不存在时可让 Agent 创建，再放入完整的 `xx3zdjj` 文件夹。

**Windows：**在文件资源管理器地址栏输入项目内 skills 父目录，例如 `D:\my_project\.agents\skills`；不存在时新建对应文件夹，再放入完整的 `xx3zdjj` 文件夹。示例路径需要换成自己的项目路径。

**WSL、远程 SSH 或云端会话：**路径属于 Agent 真正执行命令的环境，不一定是 Windows 桌面。先让 Agent 报告执行环境、项目根和目标目录。该 Skill 的自动补装主要针对 macOS 和 Windows x64，不把 WSL/Linux 或云端当成已经验收的本机环境，也不自动上传原片。

正确结构（以 Codex 为例，另外两种 Agent 将 `.agents` 换成表中对应目录）：

```text
my_project/
└── .agents/
    └── skills/
        └── xx3zdjj/
            ├── SKILL.md
            ├── scripts/
            ├── references/
            ├── assets/
            ├── agents/
            ├── docs/
            └── README.md
```

错误示例是 `skills/xx3zdjj/xx3zdjj/SKILL.md`，或只有 `SKILL.md`、没有脚本和素材。如果目标已经存在，请保留旧版并比较修改，不要选择“全部替换”。

### Codex 安装器的目标目录

`$skill-installer` 的默认位置可能是用户级 `$CODEX_HOME/skills`，**只写“使用安装器”不能保证项目级安装**。让 Agent 检查当前安装器帮助，并为仓库根目录显式传入以下参数：

```text
--repo zhaidike123456ai-ux/xx3zdjj --path . --name xx3zdjj --dest "<项目根>/.agents/skills"
```

`--dest` 是项目内的 **skills 父目录**，安装器再创建 `xx3zdjj`，不要把目标写成 `.../skills/xx3zdjj` 后再嵌套一层。上述是给安装器的参数示意，不是完整的终端命令；真实脚本位置和 Python 命令由 Agent 检查后填写。不支持指定项目目标的安装器应改用完整 ZIP 的项目内复制方式，不改为全局安装。

### 有 Git 时的可选安装方法

也可以让 Agent 用 Git 克隆。下面以 Codex 为例：先在终端进入已选定的项目根，核对输出路径；其他 Agent 将 `.agents` 换成对应目录。没有 Git 时直接用 ZIP，无需先安装 Git。

macOS 终端（先执行 `pwd`，确认显示的就是项目根）：

```bash
skill_target="$PWD/.agents/skills/xx3zdjj"
if [ -e "$skill_target" ] || [ -L "$skill_target" ]; then
  echo "目标已存在，请先保留旧版并检查差异：$skill_target"
else
  mkdir -p "$(dirname "$skill_target")"
  git clone https://github.com/zhaidike123456ai-ux/xx3zdjj.git "$skill_target"
fi
```

Windows PowerShell（先执行 `Get-Location`，确认显示的就是项目根）：

```powershell
$skillRoot = Join-Path (Get-Location).Path '.agents/skills'
$skillTarget = Join-Path $skillRoot 'xx3zdjj'
if (Test-Path -LiteralPath $skillTarget) { throw "目标已存在，请先保留旧版并检查差异：$skillTarget" }
New-Item -ItemType Directory -Force -Path $skillRoot | Out-Null
git clone https://github.com/zhaidike123456ai-ux/xx3zdjj.git "$skillTarget"
if ($LASTEXITCODE -ne 0) { throw 'Git clone 失败，请检查网络与上方错误。' }
```

这些命令只检查目标目录是否已存在；其他位置的同名技能仍需按上文核对。Git 克隆会保留 Skill 自己的 `.git` 历史。若需要把完整 Skill 文件纳入你现有项目的 Git，建议用 ZIP 复制版，避免嵌套仓库；安装提示词不授权自动提交或推送你的项目。

### 可选全局安装

只有想让多个项目共用时，才采用下面的用户级目录。“全局”在这里指当前用户多个项目可用，不是写系统目录或申请管理员权限。

| Agent | macOS 用户级完整 Skill 路径 | Windows 原生用户级完整 Skill 路径 |
| --- | --- | --- |
| Codex（按当前官方目录） | `~/.agents/skills/xx3zdjj/` | `%USERPROFILE%\.agents\skills\xx3zdjj\` |
| Claude Code | `~/.claude/skills/xx3zdjj/` | `%USERPROFILE%\.claude\skills\xx3zdjj\` |
| Cursor | `~/.cursor/skills/xx3zdjj/` | `%USERPROFILE%\.cursor\skills\xx3zdjj\` |

`~` 是执行 Agent 的用户主目录，Windows 文件资源管理器可展开 `%USERPROFILE%`。Codex 内置安装器或已有版本可能采用 `$CODEX_HOME/skills`（通常为 `~/.codex/skills`）；以宿主核实可用的位置为准，不在多个目录重复安装。

想选择此方式，单独发送以下提示词，**不要与首页的“仅当前项目”提示词一起发送**：

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

### Skill、依赖与作品的位置分别管理

项目级安装只决定 **Skill 文件放在哪、在什么项目中发现**，不会自动更改运行环境和作品的位置：

- Python、FFmpeg、模型等默认在本机用户级隔离目录中检测、按授权补齐和复用；不会因每个项目安装 Skill 就复制整套环境，也不会写全局 pip/npm。首次安装提示词只允许检测，不授权补装。
- 工作室默认仍是 `Documents/talking_head_studio`。如希望作品也留在当前项目，可告诉 Agent：“本项目使用 `<项目根>/talking_head_studio` 作为工作室”，由它按 `studio_manager.py --studio-root` 设置。
- 若明确要求运行环境也留在项目内，让 Agent 先核对并说明 `--runtime-root` 的位置和空间，再按授权执行。这不等于已经验证所有工具缓存都只写项目内，不能把项目级 Skill 当成完全隔离的便携环境。

见 [运行环境说明](../references/runtime.md) 和 [项目目录说明](../references/studio.md)。

## 4. 让 Agent 确认能用

默认项目级安装后，发送下面的验证提示词。如果刚选择的是可选用户级安装，将“项目内这一份”换成“刚确认的用户级目录内这一份”，核对实际路径，不为验证再向项目复制一份。

```text
请在当前项目会话中检查能否发现 xx3zdjj，读取项目内这一份的 SKILL.md。
告诉我实际加载路径和版本，确认 scripts、references、assets 都齐全，并说明有无其他同名副本。
本次只做环境检测，列出哪些能用、哪些缺失，不开始处理视频。
```

如果没有识别，在同一项目开新会话后重试；仍没有时重启 Agent，再检查目录、技能启用状态及公司策略。安装器本身可能支持立即发现，能找到时无需反复重启。

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
已有可用的不要重装。保存在用户级隔离目录，不覆盖其他项目，不上传我的视频。
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

先检查环境、建立项目并核对素材，再让我明确选择全自动或半自动；本项目已经选过就沿用。
重复的字、词、半句或整句只保留最后一次完整表达，拿不准的删除边界保留完整发音，不要吞字。
```

Windows 原片可以写成 `C:\Users\your_name\Videos\take01.mp4`。输入中文文件名和带空格的完整路径可以保留，交给 Agent 正确引用。附件也必须能被当前本地 Agent 读取；不要把别人的示例路径原样复制使用。

Claude Code 可把第一行换成 `/xx3zdjj`；Cursor 可在 Agent 聊天中输入 `/` 后选中 `xx3zdjj`。通用写法是“使用 xx3zdjj 处理我刚发的原视频”。项目级安装时，请在安装了 Skill 的项目会话中调用；用户级安装可在宿主支持的其他本地项目中调用。有同名副本时先核对实际加载路径。调用语法来源：[Codex](https://learn.chatgpt.com/docs/build-skills)、[Claude Code](https://code.claude.com/docs/en/skills)、[Cursor](https://cursor.com/docs/skills)。

首次收到视频和可选逐字稿、核对对应关系后，Agent 会让你明确选择模式。没有回答不会默认全自动；本项目已有明确选择不重复问。旧项目没有模式记录时保留半自动，“继续”或“你判断”不会自动切到全自动。你无需自己填写工程 JSON 或编写媒体命令。

**全自动 `full_auto`：** 开工时一次确定蒙版形状、默认或自定义背景、背景动效方向与速度、字幕样式、剪辑风格和重说策略；自定义素材先提供齐全。你可以明确让 AI 决定部分样式，它会记录具体参数。确定选项后，Agent 记录与本次视频、稿件、背景和设置绑定的一次流程授权，再连续完成分析→剪辑→字幕→蒙版→剪映原生工程→导入，每阶段都检查实际产物，不逐阶段等你批准。若选项超出当前能力，例如尚未适配的原生圆角方，会在开工前说明，不能悄悄换形状。

全自动信息、素材与授权准备齐全后，Agent 会先明确提示：

> 信息已收集完毕，接下来进入全自动剪辑。我会按已确定的选项完成制作和 AI 质检，最终交付可编辑的剪映工程文件。

这是一条开工通知，随后直接继续，不需要你再回复一次“开始”；仍有缺项时会先说明，不提前宣布收集完成。

**半自动 `semi_auto`：** 分析方案经 AI 质检后交你确认，再给完整无字幕预览；粗剪确认后做字幕，字幕确认后做人物蒙版与背景，完整 MP4 确认后再做剪映工程。每阶段都保留 AI 质检和你对具体版本的确认，每次修改给完整新版预览。

两种模式采用相同的机器质检标准，不要求 Agent 实际听音频或提供听校证明，缺少音频感知能力不会让流程停住。Agent 会结合局部转写、声学边界、词时间和剪辑映射检查；必要工具或素材缺失、机器检测失败、警报未处理时，仍需修复或说明具体阻塞，不能直接填通过。原片或约定设置改变会使旧的全自动授权失效；你随时可以要求暂停或改为半自动，“先分析、不要剪”等明确限制始终优先。详见 [模式与授权](../references/workflow-modes.md)。

两种模式都以“一轮基础工程检查通过 + 剪映实际识别导入”为默认交付条件。复制到草稿目录不等于导入成功；没有 UI 能力或尚无可靠的应用识别证据时，会给你现有文件路径并标记“导入待确认”，不把待确认说成完成，也不无限检查。已做的同版本检查直接复用，默认不试改、不保存重开、不从剪映导出 MP4，也不主动询问深度验收。只有你另外明确要求时才做对应验证。

**两种模式最终都交付可编辑剪映工程文件。** Agent 会给完整工程目录及所需素材、工程名、可打开的绝对路径和导入结果。完整 MP4、SRT/ASS 继续用于过程预览、质检和工程构建并保留在项目内；最终不会只给一个 MP4 就结束完整剪辑任务。

成果位置由 Agent 给出可打开的绝对路径。默认工作室中的 `04_previews` 放预览、`05_jianying` 放工程、`06_deliverables` 放已验收交付。

视频处理阶段会按 Skill 的 [多智能体协作规则](../references/multi-agent.md) 自主判断子智能体人数、职责和顺序，并根据任务进展调整；你不必每次指定人数。分析方案及新制或修改的产物必须质检，工具可用时由未制作或修改该版本的子智能体独立检查，发现问题后修复并复查。实际创建与结果由当前宿主工具提供；无法创建时，主代理仍须检查并说明独立质检缺口，不需要为此安装额外 Skill。仅安装或检查环境时，不保证出现子智能体。

## 7. 常见问题

| 问题 | 怎么处理 |
| --- | --- |
| 下载链接打不开 | 打开 [Release 页面](https://github.com/zhaidike123456ai-ux/xx3zdjj/releases/latest) 的 Assets；仍打不开先解决 GitHub 网络访问 |
| 提示没有 Git | 用 ZIP 手动安装，或把已下载 ZIP 的本地路径发给 Agent |
| Agent 找不到 Skill | 核对宿主、项目根、执行机器、目录层级和 SKILL.md；在同一项目开新会话；已有同名版本先核对实际加载路径 |
| 在另一个项目找不到 | 项目级安装不新增全局技能；在需要的项目分别安装，或明确选择可选用户级安装 |
| 读到了旧的全局版本 | 报告全部同名路径，按宿主规则解决并核对项目内实际文件；不擅自删除全局版 |
| Agent 只解释步骤、不执行 | 确认会话有本地文件和终端工具，并允许它访问本次项目；如果没有执行能力，换合适的本地 Agent |
| Skill 找到了，但转写/导出失败 | 让 Agent 跑环境检查和小测试；不要把“安装成功”当成所有运行环境都准备好了 |
| Windows 禁止执行 ps1 | 不关闭系统保护；让 Agent 在现有允许的环境用兼容 Python 运行检查，或按本机管理策略解决 |
| 想做剪映工程 | 同机需装剪映；半自动先确认完整预览，全自动按已授权设置和 AI 质检推进。两种模式均在一轮基础检查通过并确认剪映实际识别导入后交付 |
| 工程已复制却没在剪映里看到 | 文件放置不等于应用识别。报告实际路径与“导入待确认”，按已定位问题修复；缺 UI 能力时如实说明，不无限重试 |
| 选了全自动为何还有阻塞 | 全自动省去阶段用户批准，不降低质检标准；缺素材、缺能力或必要检查失败仍须明确报告 |
| 没看到子智能体 | 确认已进入可并行的视频任务、实际加载了新版 Skill，以及本次会话是否提供创建工具；创建失败时查看真实原因，详见 [协作规则](../references/multi-agent.md) |
| 想升级 | 让 Agent 比较新旧版本并先保留个人修改；环境、模型、项目和偏好不用删，不盲目强制覆盖 |

当前原生圆角方、原片级恢复、Windows 实机与剪映 UI 的验证边界详见 [README](../README.md#能力与边界)。本教程提供宿主的安装/调用方法，不把未实测的完整后期流程宣称为全平台通过。
