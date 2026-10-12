# 全自动与半自动

模式决定由谁批准阶段推进，不降低质检要求，也不改变原片只读、版本绑定和项目隔离。Skill 由宿主 Agent 调用现有媒体入口连续执行；不是一个脱离 Agent 自行运行的后台剪辑服务。

## 首次选择

收到视频、逐字稿并核对对应关系后询问：

- 全自动：先确定制作选项，AI 完成分析、剪辑、字幕、蒙版、质检与剪映工程，最后集中交付。
- 半自动：分析方案及各阶段完整预览先由用户确认，再继续。

选择必须来自用户实际消息。未回答保持未选择；已有本次选择不重复询问，旧项目无模式字段沿用半自动。用户只说“继续”“你判断”或仅选字体不能被记录为完整流程授权。用户明确限制“先分析、不剪”时执行该限制，即使项目之前选过全自动。

## 全自动开工选项

集中收齐蒙版形状、背景及自定义文件、背景运动方向与速度、字幕样式、剪辑取向/重说策略和最终交付范围。用户已确认的选项复用；可以明确授权 AI 决定样式，此时由 AI 先落成具体参数，不反复追问字号和位置。字体和背景实际可用，自定义文件带版本记录。方向/速度不从别人的项目继承。

首次检查当前软件与目标是否支持所选效果。当前原生圆角方尚未实现，不能先承诺全自动完成该工程再静默改圆形；先说明并由用户选定受支持方案或授权适配。缺文件/依赖/能力在开工前解决；全自动本身不扩大安装、登录或外部操作的既有授权。

用户确认选项并明确选择全自动后，记录一次真实授权及消息证据，绑定本项目原片、逐字稿/背景等输入、具体设置和运行编号。此授权允许 AI 在约定范围内自主确定剪点、修复及推进，不意味着用户已看过后续任何产物。

## 连续制作与 AI 质检

分析方案→精剪→残留与剪点检查→字幕校对与同步→蒙版/背景→完整预览→工程基础检查→成功导入剪映→交付。根据当前任务自主分派子智能体；工具可用时质检由未制作/修改该版本的审查者完成。共享转写、稳定证据与缓存，重任务排队。

半自动以阶段质检和用户对具体版本的确认推进。全自动以有效的一次授权和当前版本 AI 质检推进，不逐阶段问是否继续；阶段报告使用 `ai_review`，不得伪填 `user_approval`。实际检查仍有方法、覆盖范围、产物 hash、证据和未决项，不能用任务退出码或零候选代替。

重说证据充分时按已选策略处理；局部疑点有限复查，拿不准的删除边界优先保留完整发音。正常叠词/强调不机械删除。保留后仍需如实评估，不把所有警报一律改为 false_positive。没有实际音频感知能力时，ASR 文本不能冒充耳听；缺少必要证据或工具时报告具体阻塞和现有成果，不制造通过记录，不以补签人工批准掩盖技术失败。

每次改动后检查受影响范围，旧版本报告不能签验新版。进度说明不要求用户回复，不持续发送隐含确认问题。全部制作和检查完成后，再给完整 MP4、独立 SRT/ASS、剪映工程及简短检查说明，等待用户最终反馈。

## 工程检查与结束条件

两种模式标准完全相同：一轮基础完整性检查通过，并确认本次完整工程成功导入剪映后，即交付收尾。构建/安装的同版本证据直接复用，导入由一个操作者完成；记录工程名/路径及剪映实际识别证据。文件复制到草稿目录、静态检查通过，不等于导入成功。

默认不试改、保存重开或从剪映导出视频，不主动询问是否需要这些额外验收，也不因未做它们扣住工程。没有 UI 能力或无法确认导入时，交已有文件并说明“导入待确认”及具体阻塞；保留成果，不无限重试。历史 J1–J4 接口只用于用户另外明确要求的高级验证，不属于两种模式的正常交付门槛。

## 暂停、改选与恢复

用户要求暂停时先停止本任务后续动作，安全收尾正在写入的文件并记录暂停；改半自动后恢复阶段确认。不能仅靠新消息中的“继续”重新激活已撤销授权。原片、约定设置或选项改变使旧授权失效，记录变更并取得相应新授权后再自动执行；恢复前复核模式、运行编号、原片和设置，而非只凭缓存或上一轮口头结论。

能力缺失、已定位的失败或未解决的质量问题不能被模式绕过；报告具体阻塞即可，不无休止重试。文件与真实用户消息留在本机项目，不进入公开仓库。

## 脚本与报告协议

以下命令由 Agent 按真实消息填写，不要求用户操作。先 `studio_manager.py init` 建项目；收到选择后使用 `workflow select --project PROJECT --mode semi_auto|full_auto --evidence-file MESSAGE.txt`。新项目未选择时禁止制作，半自动选择后生效；全自动还需 `workflow authorize --project PROJECT --choices-file CHOICES.json --evidence-file MESSAGE.txt`。

CHOICES 的必需键为 `retake_policy`（none/last_complete）、`font_name`、`mask_shape`（circle/rounded_square）、`background`（default 或实际文件路径）、`background_motion`（static 或 `{ "direction": "right", "speed": 25 }`）和 `delivery`（例如 mp4_and_jianying）。这只是字段示意，25 不是默认速度。授权前解析字体实际路径，写到 `font_file` 或 `pipeline.captions.font_file`；背景/字体文件会绑定哈希。当前原生圆角方缺口仍须在开工前解决。逐字稿等额外已提供输入可一并登记到项目 source 清单，绑定原始文件版本；授权后不替换输入。

配置中的 `workflow` 保存 mode/state/run_id/revision 和授权文件引用；授权绑定有效设置与 `confirmed_choices` 的摘要、原片哈希和真实 UTF-8 用户消息快照。`workflow pause --project PROJECT --evidence-file MESSAGE.txt` 撤销自动授权；`workflow resume ... --choices-file CHOICES.json --evidence-file MESSAGE.txt` 为明确恢复创建新授权。设置改变后状态转 pending，重新 authorize；不重用旧授权编号。

全自动阶段报告保留 `checks`、`artifacts`、`blocking_counts` 及原有残留警报处理，但移除 `user_approval`，改为：

```json
{
  "workflow": {
    "mode": "full_auto",
    "settings": {"path": "实际项目settings.json绝对路径"},
    "authorization": {"path": "实际授权JSON路径", "sha256": "实际文件哈希"}
  },
  "ai_review": {
    "status": "passed",
    "reviewer_id": "实际审查者任务标识",
    "method": "agent_av_review",
    "capability": "audio_video_review",
    "evidence": [{"path": "实际检查记录路径", "sha256": "实际证据哈希"}],
    "artifacts": {"source": {"sha256": "当前实际输入哈希"}},
    "covered_checks": ["该阶段全部真实已完成检查ID"]
  }
}
```

示例不是通过模板：音频阶段必须实际具备 `agent_audio_listening/audio_listening` 或 `agent_av_review/audio_video_review` 能力并使用它；原有警报处理与版本检查仍执行。`jianying-basic` 的静态质检可用 `structural_review`；不能把它写成真实听校或导入结果。

全自动粗剪入口额外要求 `--decision-report` 指向 analysis 报告。其 `execution` 精确记录实际 `fps`（未指定为 null）、`confirmed_delete` 数组、`approve_candidate` 数组和 `decision_file_sha256`（无 CSV 为 null）；`artifacts/ai_review.artifacts` 绑定 source、有 CSV 时的 decisions、以及所选 CSV 行引用的 `acoustic_0000` 等声学证据（四位下标为 CSV 数据行的零基索引）。可用 `run_pipeline.decision_review_inputs(args)` 获取需绑定路径。声学证据或命令变更后需重新检查，不用旧方案直接执行。

字幕与蒙版报告保留 `source_provenance.edit_map: {path, sha256}`，将当前精剪 source 与授权原片关联；它们复用同一份实际 edit-map，不重建来源。各生产入口始终传当前 `--project-config`，不能指向活动配置的历史副本绕过暂停。全自动固定选项不可用 CLI 悄悄覆盖，未固定的逐条取景由 AI 检查确定。

产物登记后用 `review-artifact --project PROJECT --artifact-id ID --report REPORT --inputs-file INPUTS.json` 记录 `ai_reviewed`；INPUTS 将阶段输入键映射到真实路径。它支持全自动上游依赖，不写人工 approval。工程内冻结授权、用户消息、AI 证据与剪辑映射，供离线静态核验；冻结副本不能恢复自动制作，仍需当前活动项目授权。最终成功导入的简短操作记录留在项目中，不要求导出视频。
