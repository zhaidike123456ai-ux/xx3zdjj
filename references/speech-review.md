# 重说检测、警报与原音复核

## 检测与删除分开

`analyze` 始终执行长句、短片段和有效开场检测，`retake_policy=none` 只是不提出重说删除范围，不能关闭检测。`last_complete` 也不能证明最后一遍完整，不能直接拿 ASR 词时间切字。正常叠词、强调和排比允许保留，必须记录为什么保留，不能机械删。

`--single-pass` 只跳过第二路全片转写，不跳过开场分窗。同一模型两路全片 ASR 一致，不构成没有重说的独立证据。

## 有效开场

先从 16 kHz PCM 音频找实际活动段，并与首个 ASR 词交叉定位。前导静音可能很长；检查文件 0–2 秒并不等于检查人声开头。声学阈值可能漏掉弱音，因此窗口同时保护更早的 ASR 起点，不把低能量自动视为无发音。

开场使用首活动段隔离窗、第二活动段上下文窗、两段合并窗及重叠上下文窗。每个窗口独立解码，记录原片时间和覆盖范围。不同窗口覆盖同一次发声时，不能将两个相同词拼成两次重说。短活动段与相邻起音之间存在疑点时，即使 ASR 仍省略重复，也留下原音复核警报。

窗口与声学活动只是定位证据。气口、弱声母、自然叠词和刻意强调需要听校；候选绝不自动产生删除授权。任何示例时间都只适用于该例。

## 机器状态与警报

`review-report.json` 每项检查分别保存：

- `status`: `executed` / `skipped` / `unavailable`，即实际运行、跳过或不可用。
- `result`: `passed` / `review_required` / `failed` / `unverified`，即检查结论。
- `coverage`、`method`、`reason`：覆盖哪段、如何检查及未完成原因。

`command_status=completed` 或退出码 0 仅表示命令运行完成。`quality_status` 独立记录质量状态。零候选、成功解码、音轨相似或时长一致都不能证明没有口误、吞字或重说。机器没有听校能力时，字音完整性保持 `unavailable/unverified`。

每个警报有稳定 ID，`review_required=true` 必须有处理记录。不能把异常长单字解释为“时间偏差”后自行消警；先完成重叠原音复查，再记录证据。未解决时可交标注待核的完整预览，但不得宣称已修复或进入字幕。

## 用户反馈后的专项复查

用户说“重复”“吞字”“断句”时，先确定当前媒体版本和对应原片范围，检查两者的原音、局部独立转写和声学活动。不能拿旧全片转写反驳用户，也不能只扩大首尾保护范围就宣布修复。

`local-review` 的显式窗口会增加重叠上下文。传 `--feedback` 时须同时传 `--reference-source` 与 `--reference-window`，分别保存当前成片和原片报告、hash；时间依照 edit-map 换算，不把原片秒数直接当成片秒数。

```bash
python scripts/run_pipeline.py local-review \
  --source /path/to/current.mp4 --output-dir /path/to/current_review \
  --model /path/to/local_model --window START:END \
  --feedback "用户指出开头单字重复" \
  --reference-source /path/to/original.mp4 --reference-window ORIGINAL_START:ORIGINAL_END
```

这些是由代理填写的参数模板，用户不需要组织命令。先读取每条原音再选择范围，不使用固定示例剪点。

## 修复与关闭警报

粗剪 `edit-map.json` 保存原片分析报告及成片 hash。`residual-check` 检查当前成片的全片、有效开场与静音，并把原片警报映射到保留声音；已经删除的警报映射到删除后衔接位置，要求后验检查完整起音。不能通过复制成片、丢掉 edit-map 或换个报告目录来绕过原片警报。

保持成片、edit-map 和被引用的分析报告一起可访问。旧版缺少这些记录时，重新分析、生成新版粗剪与残留报告；旧的“全通过”计数不能替代新证据。

保留正常叠词或误报时，用绑定当前媒体和报告 hash 的 resolution 记录 `retain_normal_repetition` 或 `false_positive`，附实际试听方法、结论与带 hash 的证据。已具备真实音频听看能力的代理可记录自己的实际核验；只有文本 ASR 的代理不得冒充听过。没有该能力时提供少量原音给用户判断。

需要修改的警报不能在同一旧报告里写 `fixed` 消除。先修媒体，再运行新残留检测；旧报告与旧确认失效。字音完整性和机器未覆盖部分须有明确范围的实际听校补核。校验器检查证据记录和版本一致性，无法证明代理真的听懂声音。
