"""Validate recorded checks and version-bound user approval before progressing."""
import argparse
import hashlib
import json
from pathlib import Path


CHECKS = {
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


def validate_report(report_path, expected_stage, inputs):
    report_path = Path(report_path).resolve()
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        if not isinstance(report, dict):
            raise ValueError("report must be an object")
        errors = []
        if expected_stage == "jianying-project" and not all(key in inputs for key in ("project", "manifest", "native_export")):
            errors.append("native gate requires project, manifest and native_export version inputs")
        if report.get("stage") != expected_stage:
            errors.append("wrong preceding stage")
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
    args = parser.parse_args()
    if args.stage == "jianying-project":
        if not (args.project and args.manifest and args.native_export):
            parser.error("native gate requires --project --manifest --native-export")
        inputs = {"project": args.project, "manifest": args.manifest, "native_export": args.native_export}
    else:
        if not args.source:
            parser.error("this stage requires --source")
        inputs = {"source": args.source}
    if args.ass:
        inputs["ass"] = args.ass
    errors = validate_report(args.report, args.stage, inputs)
    print(json.dumps({"status": "blocked" if errors else "passed", "errors": errors}))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
