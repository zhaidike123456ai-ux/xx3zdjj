# 测试与验收

## 自动测试

在Skill外的临时目录运行测试，避免写私人项目。测试名称/数量/结果以真实运行报告为准。

- test_studio_manager.py：ASCII路径、原片保留、项目冲突、偏好层级、资产去重和固定副本、上游变化使确认失效、锁。
- test_runtime.py：环境发现、平台分支、安装复用和失败恢复。mock下载安装不等于Windows真实安装。
- test_retake_detection.py、test_media_quality.py：短重说/正常重复、缓存、字幕对齐阻断、局部复核和媒体合成。构造词表测试不是识别准确率。
- test_rough_cut_portability.py：合成媒体实际删除/帧率、hash、非法删除阻断。
- test_opening_review.py：前导静音、多尺度窗口、覆盖与不可用状态；合成波形不是人声识别准确率。
- test_retake_pipeline.py、test_review_pipeline.py：默认策略不禁用检测、单次全片仍分窗、首尾提议边界、帧量化后字头保护、零候选仍未验证、反馈双源对照。
- test_review_state.py：报警与版本闭环、实际证据要求、上游来源与多分片覆盖；模拟听校夹具不代表真人听过。
- test_stage_gate.py：批准版本、证据、未解决项对后续阶段的阻断。
- test_jianying_adapter.py：草稿结构、唯一ID、时长覆盖、批准hash、冲突保护、密文快照。

## 真实媒体

保留原片对照，复听实际人声开头（包括前导静音后的首次起音）、所有剪点前后和结尾，检查字头尾音、失败发声残留、否定条件、自然停顿和爆音。ASR字符覆盖率不能代替耳听。

字幕逐句听校，检查每条边界、最长条、孤立尾字、真实字形大小与人物间距。蒙版检查首帧和每段主体活动，背景独立、比例正常、覆盖全长；动效方向和速度来自本次确认。

## 剪映工程

在验收副本实际打开完整工程，改一条字幕、一个蒙版、一个切点和背景，保存关闭重开，确认修改保留、素材完整、原声只播一次。从真实工程导出并核对首尾/切点/字幕及完整解码。FFmpeg独立预览不能证明工程显示结果。

pilot只证明兼容测试，full须匹配批准媒体全长/帧数/字幕/切段。密文草稿不能用旧明文覆盖。精剪中间片再分段不等于原片级无损编辑。

同错误两轮无新证据则换路线或报告阻塞。Windows文件结构测试不代表Windows剪映UI通过；Mac一台通过不代表所有版本通过。

## 状态

报告分通过/失败/未验证/等待输入，分别记录Skill结构、环境、模型推理、媒体、耳听、字幕渲染、原生静态结构、打开/编辑/保存重开/导出。用户实际听校可记user_confirmed并保留真实确认和版本。

开发审计结果保存在工作区，不把本机路径、私人素材、授权或动态通过结论写成通用前提。真实项目仍需检查环境与对应证据。

## 可选真实开场回归

`test_real_opening.py` 默认跳过，仓库不分发私人素材。仅对已经标注含开头重说的样本使用，不能拿任意正常视频运行并据此判断准确率。设置环境变量 `XX3ZDJJ_REAL_RESTART_SOURCE`、`XX3ZDJJ_REAL_RESTART_TRANSCRIPT`（含匹配 source_sha256 的全片缓存）、`XX3ZDJJ_REAL_RESTART_MODEL`（已安装本地模型），可选 `XX3ZDJJ_REAL_RESTART_EXPECTED_TOKEN`（默认“我”）与仓库外 `XX3ZDJJ_REAL_RESTART_OUTPUT`，运行：

```bash
python -m unittest discover -s scripts -p 'test_real_opening.py' -v
```

测试会实际执行有上限的开场短窗，要求合并短窗暴露标注重复、产生待复核候选、缺 ASR 时明确 unavailable，并核对原片 hash 不变。不会剪片或下载模型；需要安装好的 FFmpeg/FFprobe 和 faster-whisper。测试通过只证明该标注样本被发现，不能证明任意口误均被检出或成片已经完成听校。
