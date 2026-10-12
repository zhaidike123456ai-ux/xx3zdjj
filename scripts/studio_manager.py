"""Local project, preference and reusable asset management for xx3zdjj.

All generated paths are ASCII. User-provided media is read-only. No network,
installation, application control, automatic sharing or inferred approvals.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid

from workflow_mode import (SETTINGS_DIGEST_VERSION, normalize_setting_value,
                           preserve_legacy_settings_binding, settings_digest,
                           stage_settings_digest)


PROJECT_DIRS = {
    "00_project_info": "项目说明、设置、进度与真实确认记录",
    "01_inputs": "原片位置、逐字稿与固定版本的工作素材",
    "02_analysis": "气口、重说分析与拟删方案",
    "03_edit_data": "剪辑映射、词时间和字幕",
    "04_previews": "各版本完整预览，旧版保留",
    "05_jianying": "剪映工程及其独立素材",
    "06_deliverables": "已经验收的最终成果",
    "90_logs_cache": "日志和可重新生成的缓存，不自动删除",
}
KINDS = ("backgrounds", "caption_styles", "mask_layouts", "background_motion")
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10))}
DEFAULT_SETTINGS = {
    "schema_version": 1,
    "workflow": {"mode": "unselected", "state": "pending", "revision": 0},
    "pipeline": {
        "analyze": {"retake_policy": "none"},
        "rough-cut": {},
        "captions": {"pos_x": 540, "pos_y": 1075, "font_size": 86, "max_chars": 11},
        "preview": {"canvas_width": 1080, "canvas_height": 1920,
                    "mask_center_x": 540, "mask_center_y": 1470, "mask_diameter": 620},
    },
    "confirmed_choices": {},
}
PREF_PREFIXES = ("pipeline.", "editing.", "delivery.")
ARTIFACT_STAGES = {"analysis": "analyze", "rough_cut": "rough-cut",
                   "captions": "captions", "preview": "preview", "native_project": None}
ARTIFACT_GATES = {"analysis": "analysis", "rough_cut": "rough-cut",
                  "captions": "captions", "preview": "preview", "native_project": "jianying-basic"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def object_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def artifact_settings_match(row, settings):
    """Read old artifact bindings exactly; new records use stable stage values."""
    stage = row.get("settings_stage")
    if not stage:
        return True
    values = settings.get("pipeline", {}).get(stage, {})
    version = row.get("settings_digest_version", 1)
    digest = object_hash(values) if version == 1 else stage_settings_digest(values) if version == SETTINGS_DIGEST_VERSION else None
    return digest is not None and digest == row.get("settings_sha256")


def migrate_artifact_settings(data, settings):
    """Upgrade only still-valid old bindings before a recorded settings change."""
    for row in data.get("artifacts", []):
        stage = row.get("settings_stage")
        if stage and row.get("settings_digest_version", 1) == 1 and artifact_settings_match(row, settings):
            row["settings_sha256"] = stage_settings_digest(settings.get("pipeline", {}).get(stage, {}))
            row["settings_digest_version"] = SETTINGS_DIGEST_VERSION


def setting_value(settings, key):
    cursor = settings
    for part in key.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor


def read(path, default=None):
    if not Path(path).exists() and default is not None:
        return default
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".writing_", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / ".studio_lock"
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(f"another studio mutation is active; inspect lock before retry: {target}")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        yield
    finally:
        target.unlink(missing_ok=True)


def slug(value):
    result = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:48]
    if not result:
        result = "project"
    if result in RESERVED:
        result = "project_" + result
    return result


def checked_slug(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,47}", value) or value in RESERVED:
        raise ValueError("slug must be lowercase ASCII letters/numbers/underscores, <=48 characters, and not a Windows reserved name")
    return value


def root_path(args):
    # Agents should provide the host's actual Documents location if redirected.
    return Path(args.studio_root).expanduser().resolve() if args.studio_root else Path.home() / "Documents" / "talking_head_studio"


def initialize_studio(root):
    for folder in ("preferences/confirmed", "preferences/feedback", "assets/catalog", "projects",
                   *("assets/" + kind for kind in KINDS)):
        (root / folder).mkdir(parents=True, exist_ok=True)
    guide = root / "README_zh.md"
    if not guide.exists():
        guide.write_text("# 口播工作室\n\n"
                         "文件夹使用英文命名，中文标题及原始文件名保存在项目记录中。\n\n"
                         "- preferences：个人偏好。confirmed为明确确认的长期偏好，feedback为反馈和候选习惯。\n"
                         "- assets：获准复用的背景、字幕样式、蒙版布局和动效。\n"
                         "- projects：每次制作的独立项目。原片保持原名和内容不变。\n\n"
                         "每个项目内的文件夹：\n\n" + "\n".join(f"- {k}：{v}" for k, v in PROJECT_DIRS.items()) +
                         "\n\n查找成果优先查看项目说明、04_previews和06_deliverables。\n"
                         "90_logs_cache可能仍被任务使用；不自动清理，清理前先检查。\n", encoding="utf-8")


def info(project):
    project = Path(project).expanduser().resolve()
    manifest_path = project / "00_project_info" / "project.json"
    data = read(manifest_path)
    if data.get("schema_version") != 1 or data.get("kind") != "xx3zdjj_project":
        raise ValueError("not an xx3zdjj project")
    return project, manifest_path, data


def settings_path(project):
    return Path(project) / "00_project_info" / "settings.json"


def init_project(args):
    root = root_path(args)
    sources = [Path(p).expanduser().resolve() for p in args.source]
    for path in sources:
        if not path.is_file():
            raise ValueError(f"source not found: {path}")
    date = args.date or datetime.now().strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", date):
        raise ValueError("date must be YYYYMMDD")
    datetime.strptime(date, "%Y%m%d")
    base = date + "_" + (checked_slug(args.slug) if args.slug else slug(args.title))
    with lock(root):
        initialize_studio(root)
        existing = {p.name.casefold() for p in (root / "projects").iterdir()}
        name, count = base, 1
        while name.casefold() in existing:
            count += 1
            name = f"{base}_{count:02d}"
        project = root / "projects" / name
        project.mkdir()
        for directory in PROJECT_DIRS:
            (project / directory).mkdir()
        rows = []
        for n, source in enumerate(sources, 1):
            digest = sha(source)
            row = {"id": f"video_{n:02d}", "path": str(source), "original_name": source.name,
                   "sha256": digest, "bytes": source.stat().st_size, "source_modified": False}
            if args.copy_inputs:
                ext = source.suffix.lower() if re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", source.suffix) else ".bin"
                destination = project / "01_inputs" / (row["id"] + ext)
                shutil.copy2(source, destination)
                if sha(destination) != digest:
                    raise ValueError("source changed while copying; inspect the incomplete project")
                row["working_copy"] = str(destination.relative_to(project))
            rows.append(row)
        data = {"schema_version": 1, "kind": "xx3zdjj_project", "id": str(uuid.uuid4()),
                "title": args.title, "created_at": now(), "stage": "analysis", "sources": rows,
                "assets": [], "artifacts": [], "settings_history": []}
        write(project / "00_project_info" / "project.json", data)
        write(settings_path(project), DEFAULT_SETTINGS)
        (project / "00_project_info" / "README_zh.md").write_text(
            f"# {args.title}\n\n原片只读；原始名称与位置见project.json。\n\n"
            "先选择半自动或全自动；未选择不当作全自动授权。半自动逐阶段确认；全自动先收齐选项和一次真实授权，再由AI质检后连续制作，遇到未决问题暂停。\n\n" +
            "\n".join(f"- {k}：{v}" for k, v in PROJECT_DIRS.items()) +
            "\n\nproject.json记录预览和确认。修改已确认文件会使其确认失效。\n", encoding="utf-8")
    return {"status": "created", "project": str(project), "settings": str(settings_path(project)),
            "guide": str(project / "00_project_info" / "README_zh.md"),
            "message": "完整预览在04_previews，最终成果在06_deliverables，剪映工程在05_jianying。"}


def assign(obj, key, value):
    parts = key.split(".")
    if not key.startswith(PREF_PREFIXES) or any(not re.fullmatch(r"[a-z][a-z0-9_-]*", p) for p in parts):
        raise ValueError("setting key must start with pipeline., editing., or delivery. and use safe ASCII keys")
    cursor = obj
    for p in parts[:-1]:
        if p in cursor and not isinstance(cursor[p], dict):
            raise ValueError("setting path conflicts with an existing value")
        cursor = cursor.setdefault(p, {})
    cursor[parts[-1]] = value


def invalidate_workflow(settings, reason):
    """Revoke active automatic progression without changing user approvals."""
    workflow = settings.get("workflow")
    if not isinstance(workflow, dict) or workflow.get("mode") != "full_auto":
        return
    if workflow.get("authorization"):
        workflow.setdefault("authorization_history", []).append({
            "authorization": workflow.pop("authorization"), "invalidated_at": now(),
            "reason": reason})
    workflow.update(state="pending", revision=int(workflow.get("revision", 0))+1,
                    invalidation_reason=reason)


def workflow_evidence(project, supplied, action):
    """Snapshot an actual UTF-8 message; this cannot authenticate its author."""
    source = Path(supplied).expanduser().resolve()
    if not source.is_file():
        raise ValueError("workflow needs an existing UTF-8 evidence file")
    text = source.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError("workflow evidence file must contain the actual message")
    target = project / "00_project_info" / "workflow_records" / (action + "_" + uuid.uuid4().hex + ".txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return {"path": str(target), "sha256": sha(target), "recorded_at": now(),
            "message": text, "note": "stored message evidence; structural validation does not authenticate its author"}


def selected_workflow(settings):
    """Legacy projects retain semi-automatic behavior; new ones stay unselected."""
    return settings.get("workflow", {"mode":"semi_auto", "state":"active", "legacy":True})


def workflow_record(settings, config):
    current = selected_workflow(settings)
    return {"mode":current.get("mode", "unselected"),
            "settings":{"path":str(Path(config).resolve())},
            "authorization":current.get("authorization")}


def prepare_workflow_choices(settings, choices):
    """Apply explicit user choices to the effective pipeline before binding it."""
    if not isinstance(choices, dict):
        raise ValueError("workflow choices must be a JSON object")
    required = ("retake_policy", "font_name", "mask_shape", "background", "background_motion", "delivery")
    if any(key not in choices or choices[key] in (None, "", {}) for key in required):
        raise ValueError("full_auto requires explicit choices: " + ", ".join(required))
    choices = json.loads(json.dumps(choices, ensure_ascii=False, allow_nan=False))
    if choices["retake_policy"] not in ("none", "last_complete"):
        raise ValueError("invalid retake policy")
    if choices["mask_shape"] not in ("circle", "rounded_square"):
        raise ValueError("invalid mask shape")
    if not isinstance(choices["font_name"], str) or not choices["font_name"].strip():
        raise ValueError("font_name must be an explicitly selected font")
    background = choices["background"]
    if isinstance(background, str):
        if background in ("default", "skill_default"):
            background = {"kind":"skill_default", "path":str(Path(__file__).resolve().parents[1]/"assets/default-background.jpg")}
        else:
            background = {"kind":"custom", "path":background}
    if not isinstance(background, dict) or not background.get("path"):
        raise ValueError("background needs the selected existing file path, or 'default'")
    background_path = Path(background["path"]).expanduser().resolve()
    if not background_path.is_file():
        raise ValueError("selected background file is missing")
    digest = sha(background_path)
    if background.get("sha256") and background["sha256"] != digest:
        raise ValueError("selected background changed")
    background.update(path=str(background_path), sha256=digest)
    choices["background"] = background
    motion = choices["background_motion"]
    if isinstance(motion, str):
        if motion != "static":
            raise ValueError("moving background choice needs direction and explicit positive speed")
        direction, speed = "static", 0.0
    elif isinstance(motion, dict):
        direction = motion.get("direction", motion.get("mode"))
        speed = float(motion.get("speed", motion.get("speed_px_per_second", 0)))
    else:
        raise ValueError("invalid background_motion choice")
    if direction not in ("static", "left", "right") or not math.isfinite(speed) or speed < 0 or (direction != "static" and speed <= 0):
        raise ValueError("background motion requires static, or left/right with positive finite speed")
    if direction == "static" and speed != 0:
        raise ValueError("static background must have zero speed")
    if isinstance(motion, dict):
        choices["background_motion"] = {**motion,"direction":direction,"speed":speed}
    pipeline = settings.setdefault("pipeline", {})
    pipeline.setdefault("analyze", {})["retake_policy"] = choices["retake_policy"]
    pipeline.setdefault("captions", {})["font_name"] = choices["font_name"]
    font_value = choices.get("font_file") or pipeline["captions"].get("font_file")
    if not font_value:
        raise ValueError("resolve the selected local font file before full_auto authorization")
    font = Path(font_value).expanduser().resolve()
    if not font.is_file():
        raise ValueError("selected font file is missing")
    choices["font_file"] = str(font)
    choices["font_asset"] = {"path":str(font),"sha256":sha(font)}
    pipeline["captions"]["font_file"] = str(font)
    pipeline.setdefault("preview", {}).update(mask_shape=choices["mask_shape"],
        background=str(background_path), background_motion=direction, background_speed=speed)
    settings.setdefault("confirmed_choices", {}).update(choices)
    return settings["confirmed_choices"]


def configure_workflow(args):
    """Select, authorize, pause or explicitly resume a project's workflow."""
    project, manifest, data = info(args.project)
    action = args.action
    if action not in ("select", "authorize", "pause", "resume"):
        raise ValueError("unknown workflow action")
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        settings = read(settings_path(project))
        current = dict(selected_workflow(settings))
        evidence = workflow_evidence(project, args.evidence_file, action)
        old_authorization = current.get("authorization")
        history = list(current.get("authorization_history", []))
        if action == "select":
            if args.mode not in ("semi_auto", "full_auto"):
                raise ValueError("select requires semi_auto or full_auto")
            if old_authorization:
                history.append({"authorization":old_authorization, "invalidated_at":now(), "reason":"workflow mode selected again"})
            current = {"mode":args.mode, "state":"pending" if args.mode == "full_auto" else "active",
                       "run_id":uuid.uuid4().hex, "revision":int(current.get("revision",0))+1,
                       "selection_evidence":evidence, "authorization_history":history}
        elif action == "pause":
            if old_authorization:
                history.append({"authorization":old_authorization, "invalidated_at":now(), "reason":"workflow paused"})
            current.pop("authorization", None)
            current.update(state="paused", revision=int(current.get("revision",0))+1,
                           pause_evidence=evidence, authorization_history=history)
        else:
            mode = current.get("mode")
            if mode not in ("semi_auto", "full_auto"):
                raise ValueError("select a workflow mode first")
            if action == "authorize" and mode != "full_auto":
                raise ValueError("authorize is only for the full_auto workflow")
            if action == "resume" and current.get("state") != "paused":
                raise ValueError("resume requires a paused workflow")
            if action == "authorize" and current.get("state") != "pending":
                raise ValueError("authorize requires a pending full_auto selection")
            if mode == "full_auto":
                if any(row["current_status"] != "unchanged" for row in source_states(data, project)):
                    raise ValueError("source media changed or missing; full_auto authorization is blocked")
                if not getattr(args,"choices_file",None):
                    raise ValueError("full_auto authorization/resume requires the collected choices JSON")
                choices = prepare_workflow_choices(settings, read(Path(args.choices_file).expanduser().resolve()))
                # A resumed run always gets a new identity; previous reports
                # cannot become valid by toggling paused back to active.
                current.update(run_id=uuid.uuid4().hex, state="pending",
                               revision=int(current.get("revision",0))+1)
                current.pop("authorization",None)
                settings["workflow"] = current
                from workflow_mode import create_authorization
                authorization = create_authorization(settings, data["sources"], choices, evidence["path"],
                    message=evidence["message"], recorded_at=evidence["recorded_at"],
                    settings_path=settings_path(project))
                target = project / "00_project_info" / "workflow_records" / ("authorization_"+uuid.uuid4().hex+".json")
                write(target,authorization)
                current["authorization"] = {"path":str(target), "sha256":sha(target)}
            current.update(state="active", last_evidence=evidence)
        settings["workflow"] = current
        write(settings_path(project), settings)
        data["settings_history"].append({"action":"workflow_"+action, "mode":current["mode"],
            "state":current["state"], "revision":current.get("revision",0), "evidence":evidence, "at":now()})
        write(manifest,data)
    return {"status":"updated", "workflow":current, "settings":str(settings_path(project)),
            "note":"workflow authorization is separate from per-artifact user approval and does not prove media quality"}


def set_setting(args):
    project, manifest, data = info(args.project)
    value = normalize_setting_value(args.key, json.loads(args.value))
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        settings = read(settings_path(project))
        previous = json.loads(json.dumps(settings, ensure_ascii=False))
        exists, old = setting_value(settings, args.key)
        changed = not exists or normalize_setting_value(args.key, old) != value
        # Validate the key even when its value is unchanged.
        assign({}, args.key, value)
        if changed:
            preserve_legacy_settings_binding(settings, base_dir=settings_path(project).parent)
            migrate_artifact_settings(data, previous)
            assign(settings, args.key, value)
            settings.setdefault("confirmed_choices", {})[args.key] = {"value": value, "evidence": args.evidence, "at": now()}
            if settings_digest(settings) != settings_digest(previous):
                invalidate_workflow(settings, "project settings changed")
            write(settings_path(project), settings)
        data["settings_history"].append({"key": args.key, "value": value, "evidence": args.evidence, "at": now(), "changed": changed})
        write(manifest, data)
    return {"status": "updated", "changed": changed, "settings": str(settings_path(project)), "key": args.key}


def preference(args):
    root = root_path(args)
    value = json.loads(args.value) if args.action == "record" else None
    if args.action == "record":
        assign({}, args.key, value)
    with lock(root):
        initialize_studio(root)
        target = root / "preferences" / "confirmed" / "preferences.json"
        current = read(target, {"schema_version": 1, "items": {}})
        history_path = root / "preferences" / "feedback" / "history.json"
        history = read(history_path, {"schema_version": 1, "items": []})
        record = {"id": str(uuid.uuid4()), "key": args.key, "value": value,
                  "status": args.scope if args.action == "record" else "withdrawn",
                  "context": args.context, "evidence": args.evidence, "at": now()}
        history["items"].append(record)
        if args.action == "forget":
            current["items"].pop(args.key + "|" + args.context, None)
        elif args.scope == "confirmed":
            current["items"][args.key + "|" + args.context] = record
        write(history_path, history)
        write(target, current)
    return {"status": record["status"], "preference": record}


def apply_preferences(args):
    root = root_path(args)
    project, manifest, data = info(args.project)
    prefs = read(root / "preferences" / "confirmed" / "preferences.json", {"items": {}})
    changes = []
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        settings = read(settings_path(project))
        previous = json.loads(json.dumps(settings, ensure_ascii=False))
        # Generic defaults first; an explicitly requested context can refine them.
        records = sorted(prefs["items"].values(), key=lambda row: row.get("context", "") != "all")
        selected = {}
        for row in records:
            if row.get("status") != "confirmed" or row.get("context") not in ("all", args.context):
                continue
            existing = settings.get("confirmed_choices", {}).get(row["key"], {})
            if existing and existing.get("origin") != "preference":
                continue
            selected[row["key"]] = row
        # Resolve context precedence before applying anything. A temporary
        # generic value must not revoke authorization when the final value is
        # exactly the current context-specific setting.
        for key, row in selected.items():
            value = normalize_setting_value(key, row["value"])
            exists, old = setting_value(settings, key)
            if exists and normalize_setting_value(key, old) == value:
                continue
            if not changes:
                preserve_legacy_settings_binding(settings, base_dir=settings_path(project).parent)
                migrate_artifact_settings(data, previous)
            assign(settings, key, value)
            settings.setdefault("confirmed_choices", {})[row["key"]] = {
                "value": value, "origin": "preference", "preference_id": row["id"],
                "evidence": row["evidence"], "at": now()}
            changes.append(row["key"])
        if changes and settings_digest(settings) != settings_digest(previous):
            invalidate_workflow(settings, "confirmed preferences changed effective settings")
        write(settings_path(project), settings)
        data["settings_history"].append({"action": "apply_confirmed_preferences", "keys": changes, "at": now()})
        write(manifest, data)
    return {"status": "applied", "keys": changes, "settings": str(settings_path(project))}


def asset_add(args):
    root = root_path(args)
    source = Path(args.file).expanduser().resolve()
    if not source.is_file():
        raise ValueError("asset source must be a file")
    if source.suffix.lower() in (".ttf", ".otf", ".ttc", ".woff", ".woff2"):
        raise ValueError("font binaries are not catalogued; record a local font reference in project settings")
    digest = sha(source)
    asset_id = "asset_" + digest[:24]
    ext = source.suffix.lower() if re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", source.suffix) else ".bin"
    with lock(root):
        initialize_studio(root)
        index_path = root / "assets" / "catalog" / "index.json"
        index = read(index_path, {"schema_version": 1, "items": {}})
        if asset_id in index["items"]:
            row = index["items"][asset_id]
            if sha(root / row["path"]) != digest:
                raise ValueError("existing asset content changed; keep it and inspect before reusing")
            return {"status": "reused", "asset": row}
        destination = root / "assets" / args.kind / (asset_id + ext)
        if destination.exists():
            raise ValueError("asset destination exists outside catalog; preserve it and inspect")
        temporary = destination.with_suffix(destination.suffix + ".partial")
        created_temporary = False
        try:
            with source.open("rb") as src, temporary.open("xb") as dst:
                created_temporary = True
                shutil.copyfileobj(src, dst)
            if sha(temporary) != digest:
                raise ValueError("asset changed during copy")
            os.replace(temporary, destination)
        finally:
            if created_temporary:
                temporary.unlink(missing_ok=True)
        row = {"id": asset_id, "kind": args.kind, "title": args.title or source.stem,
               "original_name": source.name, "path": str(destination.relative_to(root)),
               "sha256": digest, "bytes": destination.stat().st_size,
               "tags": args.tag, "source": args.origin or str(source), "reuse_rights": args.rights,
               "rights_evidence": args.evidence, "version": 1, "created_at": now(),
               "preview": str(destination.relative_to(root)) if ext in (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov") else None}
        index["items"][asset_id] = row
        write(index_path, index)
    return {"status": "added", "asset": row}


def asset_use(args):
    root = root_path(args)
    index = read(root / "assets" / "catalog" / "index.json")
    row = index["items"].get(args.asset_id)
    if not row:
        raise ValueError("asset id not found")
    source = (root / row["path"]).resolve()
    if not source.is_relative_to((root / "assets").resolve()) or sha(source) != row["sha256"]:
        raise ValueError("asset is missing, changed, or outside library")
    project, manifest, data = info(args.project)
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        destination = project / "01_inputs" / "assets" / source.name
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            if sha(destination) != row["sha256"]:
                raise ValueError("project has a modified asset snapshot; preserve it")
        else:
            fd, temporary = tempfile.mkstemp(prefix=".asset_copy_", dir=destination.parent)
            try:
                with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if sha(temporary) != row["sha256"]:
                    raise ValueError("asset changed during copy")
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
        if sha(destination) != row["sha256"]:
            raise ValueError("copied asset checksum mismatch")
        record = {"asset_id": row["id"], "path": str(destination.relative_to(project)),
                  "sha256": row["sha256"], "version": row["version"], "at": now()}
        if not any(x["asset_id"] == row["id"] and x["sha256"] == row["sha256"] for x in data["assets"]):
            data["assets"].append(record)
        write(manifest, data)
    return {"status": "snapshotted", "asset": record, "file": str(destination)}


def source_states(data, project):
    result = []
    for row in data["sources"]:
        paths = [Path(row["path"])]
        if row.get("working_copy"):
            paths.append(project / row["working_copy"])
        current = "unchanged"
        for path in paths:
            if not path.is_file():
                current = "missing"
                break
            if sha(path) != row["sha256"]:
                current = "changed"
                break
        result.append({**row, "current_status": current})
    return result


def artifact_state(row, rows, settings, visiting=None, sources_valid=True, project_config=None):
    if not sources_valid:
        return "source_changed_approval_invalid"
    visiting = set() if visiting is None else set(visiting)
    if row["id"] in visiting:
        return "invalid_dependency_cycle"
    visiting.add(row["id"])
    path = Path(row["path"])
    if not path.is_file() or sha(path) != row["sha256"]:
        return "changed_approval_invalid"
    stage = row.get("settings_stage")
    if not artifact_settings_match(row, settings):
        return "settings_changed_approval_invalid"
    for key in row.get("depends_on", []):
        parent = next((r for r in rows if r["id"] == key), None)
        acceptable = {"approved"}
        if settings.get("workflow", {}).get("mode") == "full_auto":
            acceptable.add("ai_reviewed")
        if not parent or artifact_state(parent, rows, settings, visiting,
                                        project_config=project_config) not in acceptable:
            return "upstream_not_approved"
    if row.get("approval"):
        return "approved"
    review = row.get("ai_review")
    if review:
        if settings.get("workflow", {}).get("mode") != "full_auto" or not project_config:
            return "workflow_authorization_invalid"
        try:
            report = Path(review["report"]["path"])
            if not report.is_file() or sha(report) != review["report"]["sha256"]:
                return "review_evidence_changed"
            inputs = {key: Path(value["path"]) for key, value in review["inputs"].items()}
            if any(not path.is_file() or sha(path) != review["inputs"][key]["sha256"]
                   for key, path in inputs.items()):
                return "review_inputs_changed"
            native_approval = review.get("native_approval_report")
            if native_approval and (not Path(native_approval["path"]).is_file()
                    or sha(native_approval["path"]) != native_approval["sha256"]):
                return "review_inputs_changed"
            from stage_gate import validate_report
            if validate_report(report, ARTIFACT_GATES[row["kind"]], inputs,
                               project_config=project_config):
                return "ai_review_invalid"
        except (OSError, ValueError, KeyError, TypeError):
            return "ai_review_invalid"
        return "ai_reviewed"
    return "awaiting_confirmation"


def register_artifact(args):
    project, manifest, data = info(args.project)
    file = Path(args.file).expanduser().resolve()
    if not file.is_file() or not file.is_relative_to(project):
        raise ValueError("artifact must be an existing file inside this project")
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        if any(row["current_status"] != "unchanged" for row in source_states(data, project)):
            raise ValueError("source media changed or missing; create a new project or restore the recorded source")
        known = {row["id"] for row in data["artifacts"]}
        if not set(args.depends_on) <= known:
            raise ValueError("unknown dependency artifact")
        settings = read(settings_path(project))
        stage = ARTIFACT_STAGES[args.kind]
        row = {"id": "artifact_" + uuid.uuid4().hex[:12], "kind": args.kind,
               "path": str(file), "sha256": sha(file), "at": now(), "depends_on": args.depends_on,
               "settings_stage": stage, "settings_digest_version": SETTINGS_DIGEST_VERSION,
               "settings_sha256": stage_settings_digest(settings.get("pipeline", {}).get(stage, {})) if stage else None}
        data["artifacts"].append(row)
        write(manifest, data)
    return {"status": "registered", "artifact": row}


def approve(args):
    project, manifest, data = info(args.project)
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        row = next((r for r in data["artifacts"] if r["id"] == args.artifact_id), None)
        if not row:
            raise ValueError("artifact id not found")
        sources_valid = all(row["current_status"] == "unchanged" for row in source_states(data, project))
        state = artifact_state(row, data["artifacts"], read(settings_path(project)), sources_valid=sources_valid,
                               project_config=settings_path(project))
        if state not in ("approved", "awaiting_confirmation", "ai_reviewed"):
            raise ValueError("cannot approve stale artifact: " + state)
        record = {"artifact_id": row["id"], "sha256": row["sha256"], "message": args.evidence,
                  "recorded_at": now(), "status": "approved", "note": "user confirmation record; not machine audio or native UI validation"}
        evidence = project / "00_project_info" / ("approval_" + row["id"] + ".json")
        write(evidence, record)
        row["approval"] = {**record, "evidence": str(evidence)}
        data["stage"] = row["kind"] + "_approved"
        write(manifest, data)
    return {"status": "recorded", "approval": record, "evidence": str(evidence)}


def review_artifact(args):
    """Record an actual full-auto AI gate without manufacturing user approval."""
    project, manifest, data = info(args.project)
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        settings = read(settings_path(project))
        if selected_workflow(settings).get("mode") != "full_auto":
            raise ValueError("ai_reviewed progression requires full_auto; semi_auto keeps user approval")
        from workflow_mode import validate_workflow
        errors = validate_workflow(workflow_record(settings, settings_path(project)),
                                   settings_path(project).parent, project_config=settings_path(project))
        if errors:
            raise ValueError("invalid workflow authorization: " + "; ".join(errors))
        if any(source["current_status"] != "unchanged" for source in source_states(data,project)):
            raise ValueError("source media changed or missing")
        row = next((r for r in data["artifacts"] if r["id"] == args.artifact_id), None)
        if not row:
            raise ValueError("artifact id not found")
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError("artifact changed; register the new version first")
        stage = row.get("settings_stage")
        if not artifact_settings_match(row, settings):
            raise ValueError("artifact settings changed; register the new version first")
        for parent_id in row.get("depends_on",[]):
            parent = next((r for r in data["artifacts"] if r["id"]==parent_id),None)
            if not parent or artifact_state(parent,data["artifacts"],settings,
                    project_config=settings_path(project)) not in ("approved","ai_reviewed"):
                raise ValueError("upstream artifact is not approved or AI reviewed")
        report_path = Path(args.report).expanduser().resolve()
        declared = read(Path(args.inputs_file).expanduser().resolve())
        if not isinstance(declared,dict) or not declared:
            raise ValueError("inputs-file must map gate input keys to actual file paths")
        inputs = {}
        for key,value in declared.items():
            value = value.get("path") if isinstance(value,dict) else value
            if not isinstance(key,str) or not isinstance(value,str):
                raise ValueError("invalid gate input mapping")
            candidate = Path(value).expanduser().resolve()
            if not candidate.is_file():
                raise ValueError("gate input is missing: " + key)
            inputs[key] = candidate
        if path.resolve() not in inputs.values():
            raise ValueError("review report must bind the registered artifact itself")
        report = read(report_path)
        if report.get("workflow",{}).get("mode") != "full_auto" or not report.get("ai_review"):
            raise ValueError("an actual full_auto AI review report is required, not a manufactured user approval")
        from stage_gate import validate_report
        errors = validate_report(report_path,ARTIFACT_GATES[row["kind"]],inputs,
                                 project_config=settings_path(project))
        if errors:
            raise ValueError("AI review gate failed: " + "; ".join(errors))
        native = None
        native_approval = None
        if row["kind"] == "native_project":
            if "project" not in inputs or "manifest" not in inputs:
                raise ValueError("native basic review requires project and manifest inputs")
            native_root = inputs["project"].parent
            if inputs["manifest"] != (native_root / "generation-manifest.json").resolve():
                raise ValueError("native manifest must belong to this exact project directory")
            manifest_data = read(inputs["manifest"])
            if not isinstance(manifest_data.get("content_file"),str) or (
                    native_root / manifest_data["content_file"]).resolve() != inputs["project"]:
                raise ValueError("native manifest must bind this exact project content file")
            native_approval_path = native_root / "approval-report.json"
            frozen = read(native_approval_path)
            frozen_auth = frozen.get("workflow",{}).get("authorization",{})
            current_auth = selected_workflow(settings).get("authorization",{})
            if frozen_auth.get("sha256") != current_auth.get("sha256"):
                raise ValueError("native project belongs to another workflow authorization")
            from jianying_adapter import validate
            native = validate(native_root)
            if native.get("errors") or native.get("status") != "STATIC_VALIDATED_NATIVE_UI_PENDING":
                raise ValueError("native basic validation failed: " + repr(native))
            native_approval = {"path":str(native_approval_path),"sha256":sha(native_approval_path)}
        record = {"status":"ai_reviewed", "recorded_at":now(),
                  "report":{"path":str(report_path),"sha256":sha(report_path)},
                  "inputs":{key:{"path":str(value),"sha256":sha(value)} for key,value in inputs.items()},
                  "workflow_authorization":selected_workflow(settings)["authorization"],
                  "native_basic_validation":native,
                  "native_approval_report":native_approval,
                  "note":"AI quality review under one workflow authorization; not per-artifact user approval or native UI acceptance"}
        row["ai_review"] = record
        data["stage"] = row["kind"] + "_ai_reviewed"
        write(manifest,data)
    return {"status":"ai_reviewed", "artifact_id":row["id"], "review":record}


def status(args):
    project, _, data = info(args.project)
    settings = read(settings_path(project))
    sources = source_states(data, project)
    sources_valid = all(row["current_status"] == "unchanged" for row in sources)
    artifacts = [{**row, "current_status": artifact_state(row, data["artifacts"], settings,
                  sources_valid=sources_valid, project_config=settings_path(project))} for row in data["artifacts"]]
    workflow = dict(selected_workflow(settings))
    if workflow.get("mode") == "full_auto":
        from workflow_mode import validate_workflow
        errors = validate_workflow(workflow_record(settings,settings_path(project)),settings_path(project).parent,
                                   project_config=settings_path(project))
        workflow.update(authorization_valid=not errors, errors=errors)
    return {"project": str(project), "title": data["title"], "recorded_stage": data["stage"],
            "artifacts": artifacts, "settings": settings, "sources": sources,
            "workflow":workflow,
            "guide": str(project / "00_project_info" / "README_zh.md"),
            "message": "确认状态依据当前文件和上游依赖重新检查；不代表已完成听校或剪映验收。"}


def main():
    # Deterministic UTF-8 JSON when Windows redirects stdout using a legacy code page.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio-root", help="persistent local studio root, outside the installed Skill")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("--title", required=True); p.add_argument("--slug"); p.add_argument("--date")
    p.add_argument("--source", action="append", default=[]); p.add_argument("--copy-inputs", action="store_true")
    p.set_defaults(func=init_project)
    p = sub.add_parser("set")
    p.add_argument("--project", required=True); p.add_argument("--key", required=True)
    p.add_argument("--value", required=True, help="JSON value"); p.add_argument("--evidence", required=True)
    p.set_defaults(func=set_setting)
    p = sub.add_parser("preference")
    p.add_argument("action", choices=("record", "forget")); p.add_argument("--key", required=True)
    p.add_argument("--value", default="null"); p.add_argument("--scope", choices=("candidate", "confirmed"), default="candidate")
    p.add_argument("--context", default="all"); p.add_argument("--evidence", required=True)
    p.set_defaults(func=preference)
    p = sub.add_parser("apply-preferences")
    p.add_argument("--project", required=True); p.add_argument("--context", default="all")
    p.set_defaults(func=apply_preferences)
    p = sub.add_parser("list-preferences")
    p.set_defaults(func=lambda a: {"confirmed": read(root_path(a)/"preferences/confirmed/preferences.json", {"items": {}}),
                                   "feedback": read(root_path(a)/"preferences/feedback/history.json", {"items": []})})
    p = sub.add_parser("asset-add")
    p.add_argument("--file", required=True); p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--title"); p.add_argument("--tag", action="append", default=[]); p.add_argument("--origin")
    p.add_argument("--rights", choices=("user_approved", "skill_bundled", "public_license"), required=True)
    p.add_argument("--evidence", required=True); p.set_defaults(func=asset_add)
    p = sub.add_parser("asset-use")
    p.add_argument("--project", required=True); p.add_argument("--asset-id", required=True); p.set_defaults(func=asset_use)
    p = sub.add_parser("asset-list")
    p.set_defaults(func=lambda a: read(root_path(a)/"assets/catalog/index.json", {"schema_version":1,"items":{}}))
    p = sub.add_parser("register-artifact")
    p.add_argument("--project", required=True); p.add_argument("--kind", choices=tuple(ARTIFACT_STAGES), required=True)
    p.add_argument("--file", required=True); p.add_argument("--depends-on", action="append", default=[]); p.set_defaults(func=register_artifact)
    p = sub.add_parser("approve")
    p.add_argument("--project", required=True); p.add_argument("--artifact-id", required=True)
    p.add_argument("--evidence", required=True, help="actual user confirmation, not an agent's proposed approval")
    p.set_defaults(func=approve)
    p = sub.add_parser("workflow")
    p.add_argument("action", choices=("select","authorize","pause","resume"))
    p.add_argument("--project",required=True)
    p.add_argument("--mode",choices=("semi_auto","full_auto"))
    p.add_argument("--evidence-file",required=True,help="existing UTF-8 file recording the actual user message; never synthesized approval")
    p.add_argument("--choices-file",help="collected explicit choices JSON for full_auto authorize/resume")
    p.set_defaults(func=configure_workflow)
    p = sub.add_parser("review-artifact")
    p.add_argument("--project",required=True);p.add_argument("--artifact-id",required=True)
    p.add_argument("--report",required=True);p.add_argument("--inputs-file",required=True)
    p.set_defaults(func=review_artifact)
    p = sub.add_parser("status")
    p.add_argument("--project", required=True); p.set_defaults(func=status)
    args = parser.parse_args()
    if hasattr(args, "evidence") and not args.evidence.strip():
        parser.error("evidence must not be empty")
    try:
        result = args.func(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
