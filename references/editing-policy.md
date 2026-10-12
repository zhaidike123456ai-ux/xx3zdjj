# 自然紧凑口播：可执行规则（2.3.0）

全自动与半自动共用本页规则；半自动额外取得阶段用户确认。保留已跑通的原片保护、原速、音画同剪、字幕导出、人物蒙版、独立背景及剪映流程，不为增加模式重写整套制作。

## 气口清单

把测得的静音作为气口候选。`analyze` 默认 `--silence-min 0.12 --propose-internal 0.30`，使用自然紧凑节奏：片头保留约0.10秒、句内0.14秒、句末0.24秒、分号分点0.34秒、片尾0.20秒。这是整个静音间隔的剩余长度，不是两端分别保留这么长；短于目标的不补长。默认阈值可按录音调整，不把低电平直接当作没有字音。

`silence-candidates.csv` 和 `deletion-decisions.csv` 包含每段测量的保留/缩短/冲突记录。不能只删首尾就称气口已处理；不能把多段低电平总时长直接视为可删除量。自动标点分类只提出目标，Agent结合实际上下文保护强调、转折与必要停顿。静音和词时间重叠时列为冲突，不产生可直接执行的删除范围，先局部复核。

## 重说分组与取舍

用户要求口播精剪、清理口误重说时，把取舍落实为 `--retake-policy last_complete`，提供了稿件则加 `--script /path/to/reference.txt`；仅分析或明确不删重说可用 `none`，检测仍照常运行。稿件用于对比，不替代实际发声，也不能凭稿件补造音频。

读取 `retake-candidates.json` 中整组 `attempts`、`selection`、差异和 `proposed_delete_ranges`，不要只读取旧的 `last_attempt_*` 字段。后者仅表示时间上最后出现的尝试。对全部尝试检查完整性、否定词、数字、条件和独有内容，选择最后一次完整正确表达；最后一次有错或没说完时选前面最近的合格表达。文本等价仅是候选证据，不能自动证明语义正确。

每次失败尝试独立提出删除区间；不从第一次开头连续删到最后一次开头，以免删除中间独有内容。相同ASR段中的短句、跨段重说、三个以上尝试都要处理；正常叠词、排比和强调不能机械删除。疑点用已有 `local-review --window START:END` 复核，必要时指定另一套已可用的本地模型，仅重跑有关窗口。没有检测到不等于证明没有。

## 执行剪点

所有重说删除须填源绑定 `acoustic_evidence`，按真实声学边界更新删除表，再生成对应模式的审核记录。若新声学起点早于已审核范围，程序拒绝静默扩大；全自动由Agent更新方案与AI审查，半自动对新范围按原阶段确认。不要借通用 `--confirmed-delete` 绕开尚未查清的重说候选。

所有入口的删除范围都向内对齐视频帧：开始向后取整、结束向前取整，实际删除不超出批准范围。`deleted-ranges.csv` 与 edit-map记录实际执行区间，`cut-quantization.json`保存量化输入与差值；若先做声学校正，edit-map 的 `boundary_evidence` 另保留原批准范围、校正值和差值。没有完整可删帧时保留或重新评估，不强切。

先处理重说，再调整剩余气口；更新声音后在新版音轨上重建/映射字幕时间。剪后必须检查对应重说是否残留、必要信息是否丢失，以及实际剪点是否侵入有效发音。

## 字幕时间与排版

`captions` 使用原有ASS/SRT导出器，增加 `caption-timing-review.json`：短词异常长、词时间跨明显静音、已测起音分歧及重叠均列疑点，不直接裁短词。长音可能真实存在，处理必须有局部机器证据。合法时间、完整字符覆盖、零导出提前量都不能证明真实起音准确。

局部复核通过 `--timing-review review-index.json` 接入。索引含 `local_reviews:[{path,sha256}]`，可另含 `onset_evidence:[{source_sha256,word_index,onset,method}]`。每份局部证据为UTF-8 JSON：

```json
{
  "kind": "caption_local_machine_review",
  "source_sha256": "caption-timing-review.json 中的 source_sha256",
  "word_index": 0,
  "original_word": {"word":"实际词","start":0.0,"end":1.0},
  "window": {"start":0.0,"end":2.0},
  "method":"实际局部转写与声学对照方法",
  "reviewer":"实际代理标识","recorded_at":"实际时间",
  "assessment":"具体窗口、测量结果及保留或修正依据",
  "verification":"confirmed",
  "flag_ids":["对应报告真实ID"],
  "resolution":"replace_timing",
  "measured_word":{"word":"实际词","start":0.1,"end":0.5}
}
```

这是格式说明，不是可用于放行的示例证据。`source_sha256`绑定 `captions --source` 当前媒体文件（通常是粗剪 MP4），直接复制 `caption-timing-review.json.source_sha256`，不要使用另行抽取的 WAV 哈希。`original_word`须从该报告的 `flags[].original_word` 或对应 `words[]` 复制完整对象，包括程序补入的 `local_start`、`local_end`、`source_word_index` 及原有概率等字段；不要只抄原转写中的简化词对象。时间和文本必须来自实际局部测量，不能均分词时长。真实拖音使用 `resolution: retain` 且 measured_word时间保持原值；`verification: inconclusive`仍未决，不因保留而通过。失败记录保留，新证据通过后仅替换对应词，不全片统一偏移。

自动排版合并明显悬空连接，必要时在完整词边界排成同一字幕事件的两行，不为视觉换行拆出两个时间段。`--caption-layout layout.json`可传经过AI语义审查的字符串数组，保留所有文字；字符串内换行表示同一事件两行。多个事件之间必须使用完整词边界，不推造字级时间。字体实际宽度继续检查，最长两行还须检查与人物窗口的间距。有限规则不等于通用语义理解，最终逐条复核仍由Agent完成。

## 完成条件

技术检查、语音取舍和样式检查分别报告。[证据协议](review-evidence-v2.md)区分保留动作与证据结论。无强制实际听校要求；未决问题不得改写为误报或虚构通过。两种模式最终仍交可编辑剪映工程，基础检查并实际导入后收尾，不增加剪映导出测试。
