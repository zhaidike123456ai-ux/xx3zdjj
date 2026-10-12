# 剪映工程适配、验证与快照

这里生成原生可编辑候选，不把静态 JSON 检查、5 秒测试或单个平台的历史成功称为完整工程验收。Python 标准库加已发现的 FFprobe（显式 `--ffprobe` 优先，其次 runtime 的 `XX3ZDJJ_FFPROBE`，最后 PATH）；不安装 pyJianYingDraft，不执行下载的上游代码。

## CLI

```text
python scripts/jianying_adapter.py discover [--platform mac|windows] [--app-path PATH] [--draft-root EXISTING_ROOT]
python scripts/jianying_adapter.py build --timeline timeline.json --approval-report preview-checks.json --output PROJECT/new-candidate --name 中文显示名 --platform mac [--registered-root EXISTING_ROOT] [--ffprobe PATH]
python scripts/jianying_adapter.py validate --project PROJECT/new-candidate [--report NEW_REPORT.json] [--native-report native-checks.json]
python scripts/jianying_adapter.py install --project PROJECT/new-candidate --draft-root CONFIRMED_EXISTING_ROOT
python scripts/jianying_adapter.py snapshot --project ONE_SAVED_DRAFT --output PROJECT/new-snapshot --saved-and-closed
```

所有子命令可接受 `--project-config PATH`；build 从配置的 `jianying` 对象取同名下划线键缺省值，命令行优先。配置内路径建议绝对路径，timeline 内媒体路径则相对于 timeline 文件解析。工具不会自动分享、上传、打包 ZIP 或提示分享。只有用户明确要求副本／交换时使用 snapshot。

- discover 只读实际 app 的 plist／Windows exe 版本信息和草稿目录标记；未知版本明确记 unknown。自定义目录需要显式已有路径，不创建猜测目录，不读旧草稿内容。自动发现结果不是写入授权。
- build 只写指定的全新工作区目录；目录最后一级使用 ASCII，中文显示名另设。禁止写 Skill 安装目录。`--registered-root` 仅为将来的 Resources 引用生成路径，不写 profile。
- install 仅新建一个名字，不覆盖同名，不改全局 `root_meta_info.json` 或其他工程。不自动启动/关闭 App；安装前由执行者确保本次写入已授权、App 正常保存且目标名字不会与用户工程冲突。若首页不发现新目录，走本机 UI 支持的导入/恢复途径，不猜改全局索引。
- snapshot 必须先保存并关闭项目，复制 opaque draft 与 Timelines 原始字节。所有字体文件排除；不解析、不改写密文路径。复制后可能要在 UI 重链接同目录 Resources。跨设备兼容始终另验，不把 SHA 校验当成兼容验收。

## 中立 timeline JSON v1

由工作室入口根据已批准的视频和布局生成；新手无需填写这些底层字段。路径可以相对，也可以绝对。示意：

```json
{
  "schema_version": 1,
  "project_kind": "full",
  "mode": "approved-clean",
  "source": {"path":"../media/clean.mp4","sha256":"ACTUAL_SHA256","width":720,"height":1280,"fps":"30/1","frame_count":600},
  "background": {"path":"../media/full-background.mp4","sha256":"ACTUAL_SHA256","width":1080,"height":1920,"fps":"30/1","frame_count":600},
  "preview": {"path":"../approved/final.mp4","sha256":"ACTUAL_SHA256"},
  "captions": {"path":"../approved/captions.ass","sha256":"ACTUAL_SHA256","format":"ass"},
  "keep_ranges": [{"start_frame":0,"end_frame":240},{"start_frame":240,"end_frame":600}],
  "layout": {
    "width":1080,"height":1920,
    "person":{"scale":0.574074074,"center_x":540,"center_y":1521.666667},
    "mask":{"shape":"circle","center_x":360,"center_y":580,"diameter":720},
    "caption":{"center_x":540,"center_y":1075,"size":12,"bold":false}
  },
  "originals": []
}
```

- source 是有证据、已批准的精剪源，含已处理声音。keep_ranges 是此源的 **输出帧** 切点，必须连续覆盖全部帧，源内与时间线同区间、速度 1、音量 1，无新增淡化或音效。originals 可记录原片媒体同结构，仅登记素材库，不播放。
- 默认工程的切点可移动，但精剪源内已删内容没有原片前后余量。不能叫原片级无损非破坏工程。`mode: original-ranges` 本版明确拒绝：还未实现原片画面映射＋批准音轨独立播放及严格音画等价验证。后续实现时不得悄悄替换批准边界。
- background 必须已经独立渲染为相同 fps 和帧数的全长媒体；工具不改变它的动画速度、不重复错帧、不拉伸人物。视频维度、CFR、帧数及零起点由 FFprobe 实测。批准 preview 还须匹配相同全长／fps 和画布；source 与 preview 的唯一音轨全部包（PTS/DTS/duration/size/SHA）必须一致，否则拒绝重建，先查清差异再批准新源。
- layout.person 是整幅人物素材变换；scale 是相对 App 默认 fit 的统一缩放。mask 的中心／直径是 **源素材像素**，circle 保持圆形，无羽化、边框、装饰。实际取景与默认 fit 由当前版本 UI 验证，不能仅凭参数宣称不裁头。
- caption 位置是画布像素，size 是原生 App 字号，不能与 ASS 字号直接视为同一个单位。白字、黑影、无描边，不自动换行。可配置 `font_path`（本机已安装字体路径）及 bold；不复制系统字体。未选字体时留 App 默认并记录待 UI 校准，不能称为指定字形已匹配。
- captions 可用 ASS 或 SRT；保留每条原生文字和确切起止微秒，不推平均句时长。ASS 去掉覆盖标记，仅使用文本／时序，视觉样式以经批准的 layout 为准；不支持将 ASS 的逐字动画完整转换为原生动画。
- project_kind 必须为 full 或 pilot。pilot 只记录兼容性，禁止以正式 install 命令安装。正式完整度按 source 实测全长、全帧、全字幕／切段覆盖校验；上游工作室需把该源与批准全长绑定，不能把一段测试视频伪标 full。

## 蒙版形状的当前边界

完整预览入口支持圆形和圆角方形；当前原生候选适配器仅实现 `circle`。用户选择圆角方形时，先说明原生适配尚未实现，询问是否开展适配探索；用户同意后才在本机新测试工程验证原生蒙版／UI配置，成功后制作正式工程。不能自动换成圆形，也不能把烘焙人物视频冒充原生可编辑蒙版。未授权探索或缺少实机证据时记录该形状适配未完成，保留已批准预览与中立时间线，不虚构另一种形状schema。

## 版本和批准闸门

build 的 preview 报告沿用 stage_gate 格式：M1–M4 有方法及存在的证据，blocking_counts 三项严格为 0。半自动需要具体版本的用户原始消息、时间与证据；全自动需要有效 workflow 授权及当前版本 ai_review，不填 user_approval，build 应传 --project-config。artifacts 必须包含 `source`、`ass`（即 captions 文件，无论 ASS/SRT）、`preview`、`background`、`timeline` 五项真实 SHA-256。改变任一内容或布局参数会阻止构建，不能自动补写批准。证据在候选里冻结，同时保留原始批准 JSON 字节和哈希。

validate 的 `STATIC_VALIDATED_NATIVE_UI_PENDING` 仅说明文件哈希、素材登记、引用、唯一 ID、原生字幕时序、圆形配置和全长切段结构一致。不是 UI 渲染、听感、字体、保存重开或原生导出通过。

以下历史高级接口 `stage: jianying-project` 仅保留给用户另行明确要求完整原生验证的调用；两种模式默认不执行、不主动询问，不作为正常交付前置条件：

- J1：完整工程与批准版的全长、帧数、字幕／切段覆盖和素材版本对应；5 秒 pilot 不得代替。
- J2：本机 App 实际打开全部时间线，字幕、每个蒙版、切点、独立背景能编辑；在验收副本上做修改，不改变用户交付稿。
- J3：保存、关闭并重开后修改仍在，素材权限和引用有效。
- J4：从 App 原生导出完整 MP4，完整解码、声音无重复、音画／字幕／取景与批准版对应。FFmpeg 预览不能替代原生导出。

报告另需 `project_kind: full`、`native_verification` 中 `opened_full/editability/saved_reopened/native_export` 都为 true，`os/app_version` 为实测字符串，并提供项目文件、manifest、原生导出的真实版本哈希与证据。仅记录已实际完成的步骤。未完成项保持 unverified；validate 不替用户批准。保存后 draft JSON 可能变成密文，静态 validate 不解析密文，此时保留快照并用独立 stage_gate 验证实际验收报告。

## 基础检查与导入即交付

工程交付默认只执行一次基础完整性检查，复用 build/install 对同版本已完成的校验，不再重复整套 validate。核对工程与素材文件存在、引用正确、全长/主要轨道/字幕与批准版对应；独立审查者读取实际工程和已有报告，避免重复哈希扫描、渲染或全量转写。若缺少静态报告，调用一次 `validate`，不传 `--native-report`。基础失败项先修，只复查受影响范围；没有新问题或版本变化就停止检查。

全自动与半自动统一在成功导入剪映后交付：基础检查完成，使用本机实际支持的导入/草稿发现途径，由唯一操作者确认剪映已识别本次完整工程。只需记录工程名、路径、操作结果及对应 UI/工具证据，不试改、不保存重开、不从剪映导出视频，也不主动询问这些额外验收。成功后立即交付可编辑剪映工程文件及所需素材，提供完整工程目录路径和工程名，让用户检查成果。两种模式的最终交付相同；过程预览 MP4 保留在项目内。

`install` 只复制工程，`STATIC_VALIDATED_NATIVE_UI_PENDING` 只证明静态结构，两者均不能单独证明导入成功。当前没有自动认证剪映识别的 CLI：代理用实际可用的 UI 工具检查首页工程项或打开结果，保留简短证据即可。无法确认时明确报告“工程已生成，导入待确认”及具体原因，给出文件和本机导入说明，不能虚报成功或不断重复质检。

## Mac／Windows 与替代路线

模板源自原作者 GuanYixuan/pyJianYingDraft，Apache-2.0 许可证与模板文件哈希在 `assets/jianying/`；上游源码仅作为数据参考，不 vendoring 执行整个库。Mac 的 draft_info 文件名依据开放 PR198；common_mask 圆形方案在本次 Mac11 的 5 秒测试中实际可用。模板 schema 声明仅为 App 迁移线索，**不代表当前 App 的实测版本**。

Mac 候选输出 draft_info.json；Windows 候选输出 draft_content.json。Windows 只完成候选结构测试，没有本次 Windows UI、保存重开或原生导出证据，不宣称兼容。Mac 本次成功也不能推广到别的版本。

用户授权兼容探索后，未知格式每个具体问题最多两轮针对性尝试，保留失败证据后停止猜改。PR／FCP XML 只是后续探索路线：本版没有实现或验证这些导出／导入，不写“支持”。若本机软件确有可验证交换格式，再按用户所选范围在新测试工程验证并记录损失。中立 timeline、素材清单、字幕与批准预览供重建，不等同于已可跨平台直接打开。
