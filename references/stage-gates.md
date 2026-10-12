# 阶段报告与版本闸门

`run_pipeline.py captions`现必须给`--approval-report rough-cut-gate.json`；`preview`必须给`--approval-report captions-gate.json`。检查在转写或合成前执行。缺报告、失败/未验证检查、未决问题或本模式授权不满足时退出2，不制作后续媒体。

报告放当前项目，不放技能目录。它记录真实检查及对应模式授权，不是让代理自动把所有字段填通过的模板。以下是半自动结构示意，全自动区别见下文：

```json
{
  "stage": "rough-cut",
  "artifacts": {
    "source": {"sha256": "批准的粗剪文件SHA256"}
  },
  "checks": {
    "G1": {"status": "passed", "method": "实际检查方法与覆盖范围", "evidence": ["实际证据文件"]}
  },
  "residual_review": {
    "report": {"path": "residual/review-report.json", "sha256": "报告文件SHA256"},
    "resolutions": {"path": "residual/resolutions.json", "sha256": "实际处理记录SHA256"}
  },
  "blocking_counts": {"approved_not_executed": 0, "known_unfixed": 0, "unresolved": 0},
  "user_approval": {
    "status": "approved",
    "message": "用户对具体版本的实际确认摘要",
    "recorded_at": "实际记录时间",
    "evidence": "用户确认记录文件"
  }
}
```

例子只说明结构，只有G1并不能通过；粗剪必须有G1至G6全部记录。证据路径相对报告文件，必须存在。源文件内容改变会使旧批准失效。确认记录需来自真实用户消息，不从另一个助手建议制造授权。检查器不能认证消息真实性或听懂媒体，仅检查记录完整性、版本一致性与状态；不得宣传为自动语义质量证明。

## 每阶段检查

- **analysis**（兼容别名 `analyze`）：A1 原片分析覆盖与来源；A2 拟删/保留计划、声学边界及重说策略；A3 原音复核和疑点处理。全自动 `rough-cut` 必须带此阶段的 `--decision-report`，绑定当前原片和实际删除参数。
- **jianying-basic**：B1 完整工程、素材与版本一致；B2 主要轨道、全长、字幕与预览对应。只记录基础质量，不代表剪映已导入；导入结束条件见剪映适配。
- **rough-cut**：G1全片分析覆盖；G2重录/气口删留清单；G3批准项实际执行；G4字头尾音及淡化边界保护；G5剪后逐组对照、残留/吞字/误删复核；G6全片解码、规格、音画时长与版本路径。
- **captions**：C1文字与实际声音校对；C2最终音轨词音同步及连续换条；C3语义拆分、无句尾孤字、实际渲染字高/最长条/字形可见；C4完整字幕试听文件解码及对应模式批准。报告的`artifacts`同时记录`source`（批准粗剪）与`ass`（批准字幕）的SHA256，进入蒙版时必须两者一致。
- **preview**：M1人物首帧与逐段取景；M2形状/背景/字号/位置符合已确认选项；M3原声与字幕内容时序未改变；M4完整MP4解码及对应模式批准。工程build使用此报告并绑定source/ass/preview/background/timeline五项hash，执行代理根据实际批准内容补齐记录，不自动制造确认。

状态只在证据支持时填`passed`；若无实际听校能力，对相应项目用`unverified`并交原音疑点，不能称通过。用户实际听校确认可记`user_confirmed`并保存该版本的确认记录。已知残留、误删、吞字未修时计入`known_unfixed`；等待疑点选择计入`unresolved`；删除批准却未执行计入`approved_not_executed`。三个数必须全部为整数0才能推进，不能省字段或把`false`写成0。

半自动要求该阶段具体用户批准；用户只是同意继续研究或选字体，不代表批准媒体。全自动要求一次有效的输入/设置授权及本版本完整 `ai_review`，不得包含伪造 `user_approval`。改媒体或字幕后需新版本检查，半自动再取得用户确认；只改样式无需重新转写，重剪声音须重新对齐。完整协议见 [模式与授权](workflow-modes.md#脚本与报告协议)。

小白只看完整预览和简短问题，不填写JSON。执行代理保存报告，命令与内部数据不要求用户操作。运行`python scripts/test_stage_gate.py`验证阻断行为；这是记录校验测试，不是媒体质量验收。

## 质检责任与阶段推进

按 [自主分派与质检](multi-agent.md) 对分析方案及每个新制或修改的产物执行检查。工具可用时由未制作/修改该版本的子智能体独立审查，主代理收集结果，将实际证据对应到本页检查项。剪映工程按 [导入即交付](jianying.md#基础检查与导入即交付) 执行一轮基础检查并确认成功导入，不要求试改、保存重开或原生导出。质检发现问题先修复，再检查新版受影响范围，不能将审查旧版本的结论用于新交付。

协作记录保存制作/检查者标识、版本、覆盖范围、结论和证据。它是代理必须执行的工作流要求；当前脚本校验媒体与报告，不自动创建子智能体，也不能认证审查者身份或真实听看行为。不得把脚本成功当成独立质检完成。

工具确实不可用或用户要求单代理时，主代理仍须质检，独立检查状态保持未完成并说明原因。独立代理缺席本身不制造媒体缺陷，也不永久锁住工程；只有既有检查证据、警报处理、版本与对应模式授权真实齐备时才能继续。任何实际听校/UI缺口仍按原有规则处理，不能因降级而自动通过。

## 粗剪警报闭环（v2.1.0 起）

`rough-cut` 的零计数不能替代 `residual_review`。检查器读取真正的残留报告，逐项校验执行状态、范围、警报 ID 和媒体 hash；缺失或 legacy 报告不能通过。`resolutions` 无需填写没有的处理结论，存在待核项时由执行代理根据真实听校记录生成。

残留报告必须保留 `source_review_lineage` 的分析报告和 edit-map 引用及 hash，绑定同一原片与当前成片。每个上游警报的保留分片或删除后衔接处都要进入当前复核。移走成片导致引用丢失不能当作无报警。

处理记录结构示意（占位内容不能用于通过检查）：

```json
{
  "schema_version": 1,
  "source_sha256": "当前成片SHA256",
  "report_sha256": "残留报告SHA256",
  "alerts": [{
    "alert_id": "报告中的真实警报ID",
    "outcome": "retain_normal_repetition",
    "assessment": "实际复听后的判断",
    "reviewer": {"kind": "user", "method": "user_listening", "recorded_at": "实际时间", "quote": "实际反馈"},
    "evidence": [{"path": "actual_listening_record.md", "sha256": "证据文件SHA256", "kind": "listening_confirmation"}]
  }],
  "check_resolutions": []
}
```

`check_resolutions` 用于机器未验证的检查：每项包含 `check_id`、`outcome: verified`、实际完整覆盖 `coverage: {scope: full_media, start: 0, end: 实际时长}`，以及同样的 assessment、reviewer、evidence。仅有 ASR 文本不算耳听。具备真实音频能力的代理可用 `kind: agent`、`method: agent_audio_listening` / `agent_av_review` 和对应 `capability: audio_listening` / `audio_video_review` 记录实际结果，不能虚构能力。

`fixed` 不能关闭旧媒体上的警报；修改媒体后必须重新生成残留报告。未解决警报一条也不能用补核记录绕过。校验器只验证结构与证据一致性，不认证听懂声音。见 [原音复核流程](speech-review.md)。
