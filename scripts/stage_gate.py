"""Validate recorded checks and version-bound user approval before progressing."""
import argparse
import hashlib
import json
from pathlib import Path
from review_state import validate_review
from workflow_mode import AUDIO_METHODS, resolve_workflow, validate_ai_review


CHECKS = {
    "analysis": ("A1", "A2", "A3"),
    "analyze": ("A1", "A2", "A3"),
    "jianying-basic": ("B1", "B2"),
    "rough-cut": ("G1", "G2", "G3", "G4", "G5", "G6"),
    "captions": ("C1", "C2", "C3", "C4"),
    "preview": ("M1", "M2", "M3", "M4"),
    "jianying-project": ("J1", "J2", "J3", "J4"),
}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_report(report_path, expected_stage, inputs, project_config=None, *, live_config_required=True):
    report_path = Path(report_path).resolve()
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        if not isinstance(report, dict):
            raise ValueError("report must be an object")
        errors = []
        if expected_stage == "jianying-project" and not all(key in inputs for key in ("project", "manifest", "native_export")):
            errors.append("native gate requires project, manifest and native_export version inputs")
        normalized_stage = "analysis" if expected_stage == "analyze" else expected_stage
        recorded_stage = "analysis" if report.get("stage") == "analyze" else report.get("stage")
        if recorded_stage != normalized_stage:
            errors.append("wrong preceding stage")
        if expected_stage == "rough-cut":
            residual = report.get("residual_review", {})
            reference = residual.get("report", {}) if isinstance(residual, dict) else {}
            if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not reference.get("path") or not isinstance(reference.get("sha256"), str):
                errors.append("rough-cut requires a hashed residual-review report for the current media; legacy zero counts cannot pass")
            elif "source" not in inputs:
                errors.append("residual review requires current rough-cut source input")
            else:
                resolution = residual.get("resolutions")
                resolution_path = None
                resolution_hash = None
                if resolution is not None:
                    if not isinstance(resolution, dict) or not isinstance(resolution.get("path"), str) or not resolution.get("path") or not isinstance(resolution.get("sha256"), str):
                        errors.append("residual resolutions require path and SHA256")
                    else:
                        resolution_path = report_path.parent / resolution["path"]
                        resolution_hash = resolution["sha256"]
                errors.extend(validate_review(report_path.parent / reference["path"], inputs["source"],
                                              resolution_path, reference.get("sha256"), resolution_hash))
        if expected_stage == "jianying-project":
            if report.get("project_kind") != "full":
                errors.append("native acceptance requires a full project, not a pilot")
            verification = report.get("native_verification", {})
            for key in ("opened_full", "editability", "saved_reopened", "native_export"):
                if verification.get(key) is not True:
                    errors.append(f"native verification incomplete: {key}")
            for key in ("os", "app_version"):
                if not isinstance(verification.get(key), str) or not verification[key].strip():
                    errors.append(f"native verification missing: {key}")
        artifacts = report.get("artifacts", {})
        for key, path in inputs.items():
            if not Path(path).is_file():
                errors.append(f"missing input: {key}")
                continue
            if artifacts.get(key, {}).get("sha256") != file_hash(path):
                errors.append(f"input version changed or unrecorded: {key}")
        checks = report.get("checks", {})
        for key in CHECKS[expected_stage]:
            check = checks.get(key, {})
            if check.get("status") not in ("passed", "user_confirmed"):
                errors.append(f"{key}: not passed")
            if not isinstance(check.get("method"), str) or not check["method"].strip():
                errors.append(f"{key}: missing method")
            evidence = check.get("evidence", [])
            if not isinstance(evidence, list) or not evidence:
                errors.append(f"{key}: missing evidence")
            else:
                for value in evidence:
                    if not isinstance(value, str) or not value:
                        errors.append(f"{key}: invalid evidence path")
                    elif not (report_path.parent / value).is_file():
                        errors.append(f"{key}: evidence file missing")
        counts = report.get("blocking_counts", {})
        for key in ("approved_not_executed", "known_unfixed", "unresolved"):
            value = counts.get(key)
            if type(value) is not int or value != 0:
                errors.append(f"blocking count must be recorded as zero: {key}")
        context = resolve_workflow(report.get("workflow"), report_path.parent, project_config,
                                   live_config_required=live_config_required)
        errors.extend(context["errors"])
        if context["mode"] == "full_auto":
            if "user_approval" in report:
                errors.append("full_auto must use AI review, not a stage user_approval field")
            errors.extend(validate_ai_review(report, inputs, CHECKS[expected_stage], report_path.parent,
                                            require_audio=False))
            if expected_stage != "jianying-basic":
                review_method = report.get("ai_review", {}).get("method")
                if review_method not in ("combined_evidence_review", "machine_evidence_review", *AUDIO_METHODS):
                    errors.append("media stages require a speech-evidence AI assessment; static structure alone is insufficient")
            if normalized_stage == "analysis":
                auth = context.get("authorization") or {}
                authorized = {item.get("sha256") for item in auth.get("sources", []) if isinstance(item, dict)}
                source = inputs.get("source")
                if source is None or not Path(source).is_file() or file_hash(source) not in authorized:
                    errors.append("analysis source is not an authorized original source")
            elif expected_stage == "rough-cut":
                authorized = {item.get("sha256") for item in (context.get("authorization") or {}).get("sources", []) if isinstance(item, dict)}
                try:
                    residual_ref = report.get("residual_review", {}).get("report", {})
                    residual_path = report_path.parent / residual_ref["path"]
                    if file_hash(residual_path) != residual_ref.get("sha256"):
                        errors.append("authorized residual report hash changed")
                    else:
                        residual_data = json.loads(residual_path.read_text(encoding="utf-8-sig"))
                        lineage_ref = residual_data.get("source_review_lineage", {}).get("report", {})
                        lineage_path = residual_path.parent / lineage_ref["path"]
                        if file_hash(lineage_path) != lineage_ref.get("sha256"):
                            errors.append("authorized source lineage analysis hash changed")
                        else:
                            analysis_data = json.loads(lineage_path.read_text(encoding="utf-8-sig"))
                            if analysis_data.get("source_sha256") not in authorized:
                                errors.append("rough-cut original source lineage is not authorized for this run")
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    errors.append("rough-cut authorized original source lineage unavailable")
            elif expected_stage in ("captions", "preview"):
                provenance = report.get("source_provenance", {})
                ref = provenance.get("edit_map", {}) if isinstance(provenance, dict) else {}
                if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref["path"] or not isinstance(ref.get("sha256"), str):
                    errors.append("full_auto derived media requires a hashed source_provenance edit_map")
                else:
                    map_path = report_path.parent / ref["path"]
                    if not map_path.is_file() or file_hash(map_path) != ref["sha256"]:
                        errors.append("source provenance edit map missing or changed")
                    else:
                        mapping = json.loads(map_path.read_text(encoding="utf-8-sig"))
                        authorized = {item.get("sha256") for item in (context.get("authorization") or {}).get("sources", []) if isinstance(item, dict)}
                        if mapping.get("source_sha256") not in authorized:
                            errors.append("derived media original source is not authorized for this run")
                        source = inputs.get("source")
                        if source is None or not Path(source).is_file() or mapping.get("output_sha256") != file_hash(source):
                            errors.append("source provenance edit map belongs to another output media")
        elif expected_stage == "jianying-basic":
            errors.extend(validate_ai_review(report, inputs, CHECKS[expected_stage], report_path.parent,
                                            require_audio=False))
        else:
            approval = report.get("user_approval", {})
            if approval.get("status") != "approved":
                errors.append("specific version not approved by user")
            for key in ("message", "recorded_at", "evidence"):
                if not isinstance(approval.get(key), str) or not approval[key].strip():
                    errors.append(f"missing user approval {key}")
            if approval.get("evidence") and not (
                report_path.parent / approval["evidence"]
            ).is_file():
                errors.append("user approval evidence file missing")
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return [f"invalid gate report: {error}"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=tuple(CHECKS))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--native-export", type=Path)
    parser.add_argument("--ass", type=Path)
    parser.add_argument("--project-config", type=Path)
    args = parser.parse_args()
    if args.stage == "jianying-project":
        if not (args.project and args.manifest and args.native_export):
            parser.error("native gate requires --project --manifest --native-export")
        inputs = {"project": args.project, "manifest": args.manifest, "native_export": args.native_export}
    elif args.stage == "jianying-basic":
        if not (args.project and args.manifest):
            parser.error("basic native gate requires --project --manifest")
        inputs = {"project": args.project, "manifest": args.manifest}
    else:
        if not args.source:
            parser.error("this stage requires --source")
        inputs = {"source": args.source}
    if args.ass:
        inputs["ass"] = args.ass
    errors = validate_report(args.report, args.stage, inputs, project_config=args.project_config)
    print(json.dumps({"status": "blocked" if errors else "passed", "command_status": "completed",
                      "quality_status": "blocked" if errors else "passed", "errors": errors}))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
