# 阶段报告与版本闸门

`run_pipeline.py captions`现必须给`--approval-report rough-cut-gate.json`；`preview`必须给`--approval-report captions-gate.json`。检查在转写或合成前执行。缺报告、失败/未验证检查、未决问题或用户未批准时退出2，不制作后续媒体。

报告放当前项目，不放技能目录。它记录真实检查与用户确认，不是让代理自动把所有字段填通过的模板。字段如下：

```json
{
  "stage": "rough-cut",
  "artifacts": {
    "source": {"sha256": "批准的粗剪文件SHA256"}
  },
  "checks": {
    "G1": {"status": "passed", "method": "实际检查方法与覆盖范围", "evidence": ["实际证据文件"]}
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

- **rough-cut**：G1全片分析覆盖；G2重录/气口删留清单；G3批准项实际执行；G4字头尾音及淡化边界保护；G5剪后逐组对照、残留/吞字/误删复核；G6全片解码、规格、音画时长与版本路径。
- **captions**：C1文字与实际声音校对；C2最终音轨词音同步及连续换条；C3语义拆分、无句尾孤字、实际渲染字高/最长条/字形可见；C4完整字幕试听文件解码和用户批准。报告的`artifacts`同时记录`source`（批准粗剪）与`ass`（批准字幕）的SHA256，进入蒙版时必须两者一致。
- **preview**：M1人物首帧与逐段取景；M2形状/背景/字号/位置符合已确认选项；M3原声与字幕内容时序未改变；M4完整MP4解码及用户批准。工程build使用此报告并绑定source/ass/preview/background/timeline五项hash，执行代理根据实际批准内容补齐记录，不自动制造确认。

状态只在证据支持时填`passed`；若无实际听校能力，对相应项目用`unverified`并交原音疑点，不能称通过。用户实际听校确认可记`user_confirmed`并保存该版本的确认记录。已知残留、误删、吞字未修时计入`known_unfixed`；等待疑点选择计入`unresolved`；删除批准却未执行计入`approved_not_executed`。三个数必须全部为整数0才能推进，不能省字段或把`false`写成0。

当前规则要求该阶段具体用户批准；用户只是同意继续研究或选字体，不代表批准媒体。测试预览可交用户核对，但不能自动进入下一阶段。只改字幕显示位置/字号也会改变ASS，需新确认；不需要为此重新转写。重剪源音频需新对齐与确认。

小白只看完整预览和简短问题，不填写JSON。执行代理保存报告，命令与内部数据不要求用户操作。运行`python scripts/test_stage_gate.py`验证阻断行为；这是记录校验测试，不是媒体质量验收。
