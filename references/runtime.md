# 本地环境与可复用安装

环境检查默认只读。已有工具逐项核验后复用，不因版本比固定新安装版本低就重新安装；FFmpeg必须实际包含 `ass/overlay/geq/trim/atrim/crop/scale/concat` 和 `libx264/aac`。只看 `-version` 不算可用。所有补装都放在本机用户目录，不写全局 pip/npm、不覆盖其他项目，不收费、不上传媒体。不会自动安装其他 Skill，不运行 Remotion/HyperFrames 的 Skill/init/scaffold 子命令。

## 入口

下例在 Skill 根目录执行；环境选项须放 `check/ensure/smoke/exec` **之前**。实际用户路径由代理检查填写，不能把某个人的账户路径写回 Skill。

```bash
# macOS：没有Python也能做只读入口检查；没有兼容Python时解释缺项并退出。
bash scripts/bootstrap.sh check

# Windows：在现有允许本地脚本的PowerShell中运行；不修改ExecutionPolicy。
.\scripts\bootstrap.ps1 check

# 采用已有工具（例中的路径需替换）
python scripts/runtime_manager.py --python /path/to/python --ffmpeg-dir /path/to/bin \
  --model-path /path/to/faster-whisper-medium --node /path/to/node \
  --node-project /path/to/existing-project check

# 可用此前本地检查记录提供已有路径，仍重新验证，不采信其“通过”或授权声明。
python scripts/runtime_manager.py --inventory /path/to/toolchain-check.json check

# 用户已授权必要工具补装后：代理传授权开关与简短依据。
bash scripts/bootstrap.sh --allow-install --authorization-note '用户已授权补齐必要本地工具' ensure

# 同一机器后续ensure采用外置授权记录，不需再次重复询问。
bash scripts/bootstrap.sh ensure

# 功能小测试；仅合成素材，首次加载模型，按环境指纹缓存成功结果。
python scripts/runtime_manager.py smoke

# 所有后续管线使用此入口：检测与执行选择的是同一实际工具。
python scripts/runtime_manager.py exec -- python scripts/run_pipeline.py --help
python scripts/runtime_manager.py exec -- ffmpeg -version
python scripts/runtime_manager.py exec -- hyperframes --help
```

`--python/--ffmpeg/--ffprobe/--ffmpeg-dir/--node/--node-project/--model-path/--inventory/--runtime-root` 均支持已有环境采用。显式路径仍需通过版本或功能检查；不可用时会报告并寻找已记录/PATH候选。当前工作目录 `.tools/skill-media-bin`、`.tools/remotion`、`.tools/hyperframes` 是限定候选，不扫描私人文件夹。Hugging Face仅查对应模型的标准缓存目录；其他位置的模型传 `--model-path`。

`exec -- python ...` 替换为所选Python，`node/ffmpeg/ffprobe` 也替换实际路径。Remotion/HyperFrames直接通过所选Node执行已核验包的CLI，不用 `npx` 隐式下载。子进程PATH和NODE_PATH包含两套JS项目；不持久修改系统环境。管线读取 `XX3ZDJJ_FFMPEG/XX3ZDJJ_FFPROBE/XX3ZDJJ_MODEL_PATH`，模型使用本地目录、`local_files_only=True`、CPU默认4线程。需要仅用于copy/remux的另一FFmpeg时管线可显式传 `--muxer-bin /path/to/ffmpeg`；ASS渲染版本仍由环境入口选择。

退出码：0为依赖齐备/测试通过/子命令成功；1为有缺失或功能测试失败；2为授权或安装/执行错误。`exec` 返回所运行子命令的退出码。`preflight.py` 与环境管理器采用相同选择逻辑，额外支持 `--source/--font`；不把文件存在称为字幕渲染或语音听校通过。

## 来源、位置与空间

固定版本、官方来源、平台发行包SHA256及大致空间见 `assets/dependencies.json`。用户确认补装前展示 `check` 的 `missing_install_plan`，内容含来源、安装根目录和空间估算；已有明确持续授权可直接执行 `ensure`。

| 项目 | 缺失时的来源与安装方式 | 约新增磁盘空间 |
| --- | --- | --- |
| Python | Astral官方uv校验归档；uv管理的python-build-standalone，固定3.11.13 | 120MB |
| FFmpeg/FFprobe | FFmpeg官网仅发源码；采用mamba-org官方校验micromamba和conda-forge原生GPL二进制，固定8.1.2 | 800MB |
| faster-whisper | SYSTRAN项目/PyPI，固定1.2.1；隔离venv，wheel-only，逐包PyPI发布SHA256核验并生成hash锁 | 500MB |
| 本地medium模型 | Systran/faster-whisper-medium；固定下载时commit，LFS SHA256及Git blob SHA1核验 | 1700MB |
| Node.js | Node官网22.23.3 LTS归档及SHASUMS256，按架构 | 120MB |
| Remotion | 官方npm包4.0.534（core/cli/renderer一致版本） | 300MB |
| HyperFrames | HeyGen官方hyperframes npm包0.8.149 | 300MB |

空间是估算，会随平台依赖/缓存改变；新安装全套约3.8GB，缓存和保留旧代需额外余量。不因新版本固定号与可用旧版不同就升级。npm仅在独立generation中安装缺失框架，使用 `--ignore-scripts --no-audit --no-fund`；registry锁的integrity逐项检查。不执行远端 shell/PowerShell安装脚本。

macOS默认根目录：`~/Library/Application Support/xx3zdjj/runtime`；Windows默认：`%LOCALAPPDATA%\xx3zdjj\runtime`。可用 `--runtime-root` 指定本机其他目录。**该目录不在分享Skill内**。`active.json` 保存已选路径，`install-policy.json` 保存绑定机器/用户的必要工具安装授权，`generations/` 保存隔离环境，`models/` 保存按commit缓存的模型，`cache/` 保存核验下载。机器状态、日志和成功测试缓存不能打进分享包。撤销持续授权可删除本机 `install-policy.json`；不能把它复制给别的机器当授权。

## 平台边界与失败保护

支持 macOS ARM64/x64 和 Windows x64自动补装。当前固定Remotion渲染版本要求macOS 15+；较老系统只允许显式采用经实际验证的兼容环境，不盲装当前版本。Windows ARM64的当前CTranslate2发布缺少原生wheel组合，检查可采用已有验证环境，自动补装明确阻断，不悄悄使用x64模拟。32位/其他平台检查可报告已有环境，自动补装不伪称支持。

无兼容Python时bootstrap先寻找已有版本；授权后只下载并执行校验过的uv可执行分发。Windows不更改脚本执行策略；若本机策略禁止`.ps1`，由用户现有安全策略决定，不能自动绕过。TLS证书始终核验；macOS可使用系统CA或已有certifi，不允许 `--insecure`。

安装锁阻止并发，未知/残留锁不会被抢占。下载先写partial，校验后原子放入缓存；解包拒绝路径逃逸/设备文件，Node官方归档中的安全内部链接允许。每次缺失工具使用新的隔离generation，验证完才原子写 `active.json`，失败保留原启用环境和原项目；未完成代保留供诊断，不自动删除用户数据。venv不在安装后搬家，避免shebang失效。模型文件按同一commit逐个核验，第二次无需重复下载完整模型。

`ensure` 激活前会验证：合成H.264/AAC编码及FFprobe、CPU int8本地模型加载与合成静音推理、两框架CLI能运行。浏览器/完整框架视频渲染不在这个小测中自动下载或假称通过；输出明确 `browser_rendering: not_verified`，若任务实际需要动效，再采用已有浏览器做当地渲染验收。模型加载或机器ASR不能证明人耳听校、重复字完整性或字幕声画同步。成功重测试按工具版本/文件mtime与大小/包锁/模型指纹缓存；工具或模型改变后失效。

## 模块测试

```bash
python -B scripts/test_runtime.py
```

测试用临时目录、极小本地HTTP内容和mock安装器，覆盖下载损坏/缓存重用、归档逃逸、安装锁、只读与无授权零写入、持久授权的机器绑定、失败保留旧激活、模型commit锁/二次零下载、隔离wheel哈希安装和子进程环境。Windows分支需在Windows机器原生验证；Mac上的mock测试不能标Windows安装通过。真实本机检查结果存工作区，不放Skill资产。
