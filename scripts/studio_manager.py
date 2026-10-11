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
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid


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
            "先分析，再按本次授权精剪；粗剪确认后字幕，字幕确认后蒙版，完整预览确认后工程。\n\n" +
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


def set_setting(args):
    project, manifest, data = info(args.project)
    value = json.loads(args.value)
    with lock(project / "00_project_info"):
        project, manifest, data = info(project)
        settings = read(settings_path(project))
        assign(settings, args.key, value)
        settings.setdefault("confirmed_choices", {})[args.key] = {"value": value, "evidence": args.evidence, "at": now()}
        write(settings_path(project), settings)
        data["settings_history"].append({"key": args.key, "value": value, "evidence": args.evidence, "at": now()})
        write(manifest, data)
    return {"status": "updated", "settings": str(settings_path(project)), "key": args.key}


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
        # Generic defaults first; an explicitly requested context can refine them.
        records = sorted(prefs["items"].values(), key=lambda row: row.get("context", "") != "all")
        for row in records:
            if row.get("status") != "confirmed" or row.get("context") not in ("all", args.context):
                continue
            existing = settings.get("confirmed_choices", {}).get(row["key"], {})
            if existing and existing.get("origin") != "preference":
                continue
            assign(settings, row["key"], row["value"])
            settings.setdefault("confirmed_choices", {})[row["key"]] = {
                "value": row["value"], "origin": "preference", "preference_id": row["id"],
                "evidence": row["evidence"], "at": now()}
            changes.append(row["key"])
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


def artifact_state(row, rows, settings, visiting=None, sources_valid=True):
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
    if stage and object_hash(settings.get("pipeline", {}).get(stage, {})) != row.get("settings_sha256"):
        return "settings_changed_approval_invalid"
    for key in row.get("depends_on", []):
        parent = next((r for r in rows if r["id"] == key), None)
        if not parent or artifact_state(parent, rows, settings, visiting) != "approved":
            return "upstream_not_approved"
    return "approved" if row.get("approval") else "awaiting_confirmation"


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
               "settings_stage": stage, "settings_sha256": object_hash(settings.get("pipeline", {}).get(stage, {})) if stage else None}
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
        state = artifact_state(row, data["artifacts"], read(settings_path(project)), sources_valid=sources_valid)
        if state not in ("approved", "awaiting_confirmation"):
            raise ValueError("cannot approve stale artifact: " + state)
        record = {"artifact_id": row["id"], "sha256": row["sha256"], "message": args.evidence,
                  "recorded_at": now(), "status": "approved", "note": "user confirmation record; not machine audio or native UI validation"}
        evidence = project / "00_project_info" / ("approval_" + row["id"] + ".json")
        write(evidence, record)
        row["approval"] = {**record, "evidence": str(evidence)}
        data["stage"] = row["kind"] + "_approved"
        write(manifest, data)
    return {"status": "recorded", "approval": record, "evidence": str(evidence)}


def status(args):
    project, _, data = info(args.project)
    settings = read(settings_path(project))
    sources = source_states(data, project)
    sources_valid = all(row["current_status"] == "unchanged" for row in sources)
    artifacts = [{**row, "current_status": artifact_state(row, data["artifacts"], settings, sources_valid=sources_valid)} for row in data["artifacts"]]
    return {"project": str(project), "title": data["title"], "recorded_stage": data["stage"],
            "artifacts": artifacts, "settings": settings, "sources": sources,
            "guide": str(project / "00_project_info" / "README_zh.md"),
            "message": "确认状态依据当前文件和上游依赖重新检查；不代表已完成听校或剪映验收。"}


def main():
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
