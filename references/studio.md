# 英文目录、偏好与资产

`scripts/studio_manager.py`使用标准库，`--help`列出命令。`--studio-root`是全局参数，放子命令前。缺省为当前用户Documents/talking_head_studio；若Documents被重定向，代理发现真实位置后显式传入。

## 开工

`init --title 中文项目名 --slug ascii_name --source 原片路径`；多条原片重复`--source`。`--date YYYYMMDD`取用户本地日期。默认只记录源位置/hash，源文件不变；明确需要英文工作副本才加`--copy-inputs`。重复运行自动新建带编号目录。

根目录为preferences/confirmed、preferences/feedback、assets/{backgrounds,caption_styles,mask_layouts,background_motion,catalog}、projects/YYYYMMDD_slug。项目内为00_project_info、01_inputs、02_analysis、03_edit_data、04_previews、05_jianying、06_deliverables、90_logs_cache。自动生成README_zh.md，向用户解释预览/工程/交付目录。

输入清单在00_project_info/project.json，参数在settings.json。媒体入口用`--project-config settings.json`读取pipeline.analyze、pipeline.rough-cut、pipeline.captions、pipeline.preview中的可选参数，显式CLI优先。各阶段必需的source、script、ASS、background、font-name、font-file、mask-shape、subject-crop-y、output/output-dir和approval-report仍由代理显式传入；代理从本次已确认设置补齐适用参数，不重复询问用户，不让用户填写JSON。subject-crop-y必须根据本条视频实际取景决定，不能直接作为跨视频默认；素材、输出和批准报告不得自动指向另一视频。

`set --project PROJECT --key pipeline.preview.mask_shape --value '"circle"' --evidence 用户本次选择`记录本次设置。使用工具结构参数或正确shell引用传JSON值，不能拼接未转义用户文本。动效键为background_motion（static/right/left）和background_speed（px/s）；未确认动态时保持静态。

新项目的 workflow 为 unselected/pending，先选择模式再制作；旧无模式项目兼容半自动。全自动一次授权、配置变更失效与暂停恢复见 [模式协议](workflow-modes.md#脚本与报告协议)。

## 产物与确认

`register-artifact --project PROJECT --kind rough_cut --file 本项目内完整预览`登记。后续产物给`--depends-on ARTIFACT_ID`绑定上游；半自动要求 approved，全自动也接受当前有效 ai_reviewed；kind有analysis、rough_cut、captions、preview、native_project。工程登记生成清单文件而非整个目录。

`approve --project PROJECT --artifact-id ID --evidence 用户真实确认摘要`保存当前hash，仅记录用户确认，不自动声称声音或UI检查完成。阶段报告仍按stage-gates.md保存真实证据。

全自动使用 `review-artifact --project PROJECT --artifact-id ID --report REPORT --inputs-file INPUTS_JSON` 记录实际 AI 检查。报告经阶段门禁验证，inputs 文件将输入键映射到绝对路径，必须包含登记产物本身；不写用户 approval。native_project 使用 jianying-basic 并执行实际静态验证，ai_reviewed 状态不表示成功导入剪映。

`status --project PROJECT`重新核对原片/工作副本、产物hash、对应阶段设置和上游批准。原片丢失或内容改变时，旧批准全部失效并阻止登记/批准；需恢复原文件或为新素材建立新项目。改变字幕使其下游旧确认失效；只改字幕样式不影响粗剪。新版本用新文件和新artifact，旧版保留。

## 偏好

`preference record --key pipeline.captions.font_name --value '"字体名"' --scope candidate --context portrait --evidence 反馈依据`记录候选。用户明确要求以后沿用才设`--scope confirmed`。context=all只有真正全局时使用，否则指定portrait/tutorial等范围。

`list-preferences`展示记录；`preference forget --key KEY --context CONTEXT --evidence 撤销要求`撤销默认；`apply-preferences --project PROJECT --context portrait`仅应用适用confirmed记录，不覆盖本次明确选择。候选多次出现仍是建议，不静默升级。

## 资产

`asset-add --file FILE --kind backgrounds --rights user_approved --evidence 允许本人复用的依据 --tag grid`入库。rights可用user_approved、skill_bundled、public_license，须有真实依据。标题可中文，物理文件名为ASCII内容ID，按hash去重。

`asset-list`检索；`asset-use --asset-id ID --project PROJECT`建立项目固定副本并记录ID/hash/version。源库被修改后阻止复用，不偷偷换相似素材；已完成项目副本不随库改变。新内容再次入库产生新ID并保留旧资产。

原片/稿件/转写默认留项目。系统字体不入库，记录本机可用名称/路径。随包网格可按skill_bundled登记，采用到画布仍按本次背景选择。图片/视频直接作为可打开预览；模板JSON未渲染时不声称有视觉预览。

## 维护

状态位于Skill外，写入带锁与原子替换。锁冲突先检查正在运行的任务，不能直接删除别人的锁。Skill升级保留用户项目/环境/偏好/资产。分享不出现在默认引导或完成建议中，仅用户要求时进入显式工程快照流程。
