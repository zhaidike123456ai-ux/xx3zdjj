# 机器证据协议 v2

`analyze` / `residual-check`的新报告为schema_version=2。新项目推进使用v2处理记录；旧v1记录保留历史查询，不能将版本号直接改成2冒充新结论。媒体未变且原始机器证据仍有效时可复用，重新组织对应范围的v2判断，不要求重新剪片或实际听校。

处理记录顶层：`schema_version:2`、`source_sha256`、`report_sha256`、`alerts:[]`、`check_resolutions:[]`。

每条警报处理包含：

- `alert_id`：当前警报ID。
- `decision`：`retain` 或 `repair`，表达编辑动作。
- `verification`：`confirmed_benign`、`confirmed_issue` 或 `inconclusive`，表达证据结论。
- `coverage:{scope:"alert_window",start,end}`：实际复核范围，须覆盖警报。
- `assessment`：具体比较与判断。
- `reviewer:{kind:"agent",method:"machine_evidence_review",recorded_at,quote}`。
- `evidence:[{kind:"machine_verification",path,sha256}]`：实际机器证据。

只有 `retain + confirmed_benign` 且证据一致可以关闭无需修剪的警报。`retain + inconclusive`表示保守保留但仍未查清；不得改写成误报。`repair`不能关闭旧媒体报告：先修媒体，再生成新残留报告，检查原警报对应的删除后衔接位置。

每条检查补核使用 `check_id`、`verification:"confirmed"`、`coverage:{scope:"full_media",start:0,end:实际时长}` 和上述assessment/reviewer/evidence。真实检测失败不能被补核覆盖，先修检测或重跑。

每份机器证据JSON必须包含：

```json
{
  "schema_version":2,
  "kind":"machine_verification",
  "source_sha256":"当前媒体实际哈希",
  "alert_id":"该证据对应的真实警报ID",
  "coverage":{"scope":"alert_window","start":0.0,"end":1.0},
  "verification":"confirmed_benign",
  "observations":[{"method":"实际运行的机器方法","finding":"具体窗口、差异及支持该结论的实际观察"}]
}
```

检查补核用check_id替换alert_id，coverage为full_media，verification为confirmed。证据须绑定当前source及report_sha256或目标ID；若提供report_sha256，也必须与当前报告一致。占位字符串、无关范围与泛泛的“不确定所以保留”不能作为观察结论。

`validate_review(...,return_details=True)`返回派生的未决警报、未验证检查与未修问题数量；阶段门禁核对这些值，不能手填三个零绕过。协议校验能检查结构、来源、范围和状态，不能自动认证自由文本判断正确，独立AI质检仍须阅读实际机器产物。无需音频感知能力或听校证明。
