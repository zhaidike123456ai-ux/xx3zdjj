"""Project workflow authorization and artifact state; UTF-8, no real media."""
import argparse
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import studio_manager as studio
from workflow_mode import validate_workflow
from stage_gate import CHECKS


def args(**kwargs):
    return argparse.Namespace(**kwargs)


class StudioWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.source = self.base / "中文原片.mp4"
        self.source.write_bytes(b"synthetic source fixture")
        result = studio.init_project(args(studio_root=str(self.base / "studio"),
            title="流程夹具", slug="workflow_fixture", date="20261012",
            source=[str(self.source)], copy_inputs=False))
        self.project = Path(result["project"])
        self.config = studio.settings_path(self.project)
        self.message = self.base / "actual_message.txt"
        self.message.write_text("这是测试模拟的用户消息，不是真实制作授权。", encoding="utf-8")
        self.font = self.base / "fixture_font.ttf"
        self.font.write_bytes(b"font placeholder; not rendered")
        self.background = self.base / "fixture_background.jpg"
        self.background.write_bytes(b"background placeholder; not rendered")
        self.choices = {"retake_policy":"last_complete", "font_name":"Fixture Font",
                        "font_file":str(self.font), "mask_shape":"circle",
                        "background":str(self.background),
                        "background_motion":{"direction":"right","speed":25},
                        "delivery":"mp4_and_editable_project"}
        self.choices_file = self.base / "choices.json"
        studio.write(self.choices_file,self.choices)

    def workflow(self, action, mode=None, choices=True):
        return studio.configure_workflow(args(project=str(self.project),action=action,mode=mode,
            evidence_file=str(self.message), choices_file=str(self.choices_file) if choices else None))

    def authorize(self):
        self.workflow("select","full_auto")
        return self.workflow("authorize")

    def workflow_errors(self):
        settings = studio.read(self.config)
        return validate_workflow(studio.workflow_record(settings,self.config),self.config.parent,self.config)

    def register(self, kind, depends=()):
        index=len(studio.info(self.project)[2]["artifacts"])
        if kind == "native_project":
            folder=self.project/"05_jianying"/("native_"+str(index))
            folder.mkdir()
            path=folder/"draft_info.json"
            studio.write(folder/"generation-manifest.json",{"content_file":path.name})
            studio.write(folder/"approval-report.json",{"workflow":studio.workflow_record(studio.read(self.config),self.config)})
        else:
            path = self.project / "04_previews" / (kind+"_"+str(index)+".json")
        path.write_text('{"fixture":"这是结构测试产物"}',encoding="utf-8")
        return studio.register_artifact(args(project=str(self.project),kind=kind,
            file=str(path),depends_on=list(depends)))["artifact"]

    def ai_gate(self, row, inputs=None):
        stage = studio.ARTIFACT_GATES[row["kind"]]
        inputs = inputs or {"source":self.source,"artifact":Path(row["path"])}
        folder = self.project / "02_analysis" / (row["id"]+"_review")
        folder.mkdir(exist_ok=True)
        evidence = folder / "synthetic_evidence.txt"
        evidence.write_text("结构测试模拟证据，不代表真实听校。",encoding="utf-8")
        bindings = {key:{"sha256":studio.sha(path)} for key,path in inputs.items()}
        record = {"stage":stage,"workflow":studio.workflow_record(studio.read(self.config),self.config),
                  "artifacts":bindings,
                  "checks":{key:{"status":"passed","method":"synthetic fixture only",
                                 "evidence":[str(evidence)]} for key in CHECKS[stage]},
                  "blocking_counts":{"approved_not_executed":0,"known_unfixed":0,"unresolved":0},
                  "ai_review":{"status":"passed","reviewer_id":"fixture_reviewer",
                      "method":"agent_audio_listening","capability":"audio_listening",
                      "covered_checks":list(CHECKS[stage]),"artifacts":bindings,
                      "evidence":[{"path":str(evidence),"sha256":studio.sha(evidence)}]}}
        if stage in ("captions","preview"):
            mapping=folder/"source_edit_map.json"
            studio.write(mapping,{"source_sha256":studio.sha(self.source),
                                  "output_sha256":studio.sha(inputs["source"])})
            record["source_provenance"]={"edit_map":{"path":str(mapping),"sha256":studio.sha(mapping)}}
        report = folder / "gate.json"
        studio.write(report,record)
        input_file = folder / "inputs.json"
        studio.write(input_file,{key:str(value) for key,value in inputs.items()})
        return report,input_file

    def review(self, row, report=None, input_file=None):
        if report is None:report,input_file=self.ai_gate(row)
        return studio.review_artifact(args(project=str(self.project),artifact_id=row["id"],
            report=str(report),inputs_file=str(input_file)))

    def test_new_project_mode_is_unselected_and_pending(self):
        workflow = studio.read(self.config)["workflow"]
        self.assertEqual(workflow["mode"], "unselected")
        self.assertEqual(workflow["state"], "pending")
        self.assertNotIn("authorization", workflow)

    def test_evidence_snapshot_is_utf8_hashed_and_does_not_overwrite(self):
        first = studio.workflow_evidence(self.project, self.message, "select")
        second = studio.workflow_evidence(self.project, self.message, "select")
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(first["sha256"], studio.sha(first["path"]))
        self.assertEqual(Path(first["path"]).read_text(encoding="utf-8"),
                         self.message.read_text(encoding="utf-8"))
        self.message.write_text("后来修改的消息", encoding="utf-8")
        self.assertNotEqual(studio.sha(first["path"]), studio.sha(self.message))

    def test_missing_empty_or_non_utf8_evidence_rejected(self):
        with self.assertRaises(ValueError):
            studio.workflow_evidence(self.project, self.base / "missing.txt", "authorize")
        self.message.write_text(" \n", encoding="utf-8")
        with self.assertRaises(ValueError):
            studio.workflow_evidence(self.project, self.message, "authorize")
        self.message.write_bytes(b"\xff\xfe\xff")
        with self.assertRaises(UnicodeError):
            studio.workflow_evidence(self.project, self.message, "authorize")

    def test_effective_setting_change_revokes_full_auto_authorization(self):
        settings = studio.read(self.config)
        settings["workflow"] = {"mode":"full_auto", "state":"active", "revision":3,
                                "authorization":{"id":"old_auth"}}
        studio.write(self.config, settings)
        studio.set_setting(args(project=str(self.project), key="pipeline.captions.font_size",
                                value="90", evidence="测试消息：修改字号"))
        workflow = studio.read(self.config)["workflow"]
        self.assertEqual(workflow["state"], "pending")
        self.assertEqual(workflow["revision"], 4)
        self.assertNotIn("authorization", workflow)
        self.assertEqual(workflow["authorization_history"][0]["authorization"]["id"], "old_auth")

    def test_legacy_project_settings_remain_legacy(self):
        settings = studio.read(self.config)
        settings.pop("workflow")
        studio.write(self.config, settings)
        studio.set_setting(args(project=str(self.project), key="pipeline.captions.font_size",
                                value="90", evidence="测试消息：修改字号"))
        self.assertNotIn("workflow", studio.read(self.config))

    def test_select_full_auto_does_not_grant_authorization(self):
        self.workflow("select","full_auto")
        self.assertEqual(studio.read(self.config)["workflow"]["state"],"pending")
        self.assertTrue(self.workflow_errors())
        with self.assertRaises(ValueError):self.review(self.register("analysis"))

    def test_authorize_binds_real_sources_settings_and_selected_assets(self):
        self.authorize()
        self.assertEqual(self.workflow_errors(),[])
        settings = studio.read(self.config)
        workflow = settings["workflow"]
        authorization = studio.read(workflow["authorization"]["path"])
        self.assertEqual(workflow["authorization"]["sha256"],studio.sha(workflow["authorization"]["path"]))
        self.assertEqual(authorization["sources"][0]["sha256"],studio.sha(self.source))
        self.assertEqual(settings["pipeline"]["analyze"]["retake_policy"],"last_complete")
        self.assertEqual(settings["pipeline"]["preview"]["background_speed"],25)
        self.assertEqual(settings["pipeline"]["captions"]["font_file"],str(self.font.resolve()))
        self.assertEqual(authorization["choices"]["font_asset"]["sha256"],studio.sha(self.font))
        self.assertNotIn("approval",studio.info(self.project)[2])

    def test_authorize_requires_all_choices_and_resolved_local_font(self):
        self.workflow("select","full_auto")
        missing = copy.deepcopy(self.choices);missing.pop("mask_shape")
        studio.write(self.choices_file,missing)
        with self.assertRaises(ValueError):self.workflow("authorize")
        missing = copy.deepcopy(self.choices);missing.pop("font_file")
        studio.write(self.choices_file,missing)
        with self.assertRaises(ValueError):self.workflow("authorize")
        self.assertNotIn("authorization",studio.read(self.config)["workflow"])

    def test_existing_dotted_choice_records_remain_bound(self):
        studio.set_setting(args(project=str(self.project),key="pipeline.captions.font_size",
                                value="90",evidence="结构测试：90号字"))
        self.authorize()
        self.assertEqual(self.workflow_errors(),[])
        self.assertIn("pipeline.captions.font_size",studio.read(self.config)["confirmed_choices"])

    def test_pause_and_resume_issue_new_authorization_old_gate_stays_invalid(self):
        self.authorize()
        row=self.register("analysis");report,input_file=self.ai_gate(row)
        self.review(row,report,input_file)
        first=studio.read(self.config)["workflow"]
        self.workflow("pause")
        self.assertEqual(studio.read(self.config)["workflow"]["state"],"paused")
        self.assertTrue(self.workflow_errors())
        self.workflow("resume")
        current=studio.read(self.config)["workflow"]
        self.assertNotEqual(first["run_id"],current["run_id"])
        self.assertNotEqual(first["authorization"]["sha256"],current["authorization"]["sha256"])
        self.assertEqual(self.workflow_errors(),[])
        self.assertEqual(studio.status(args(project=str(self.project)))["artifacts"][0]["current_status"],"ai_review_invalid")

    def test_changed_source_or_settings_invalidates_authorization(self):
        self.authorize()
        before=self.source.read_bytes();self.source.write_bytes(b"different source")
        self.assertTrue(self.workflow_errors())
        self.source.write_bytes(before)
        self.assertEqual(self.workflow_errors(),[])
        settings=studio.read(self.config);settings["pipeline"]["captions"]["font_size"]=999
        studio.write(self.config,settings)
        self.assertTrue(self.workflow_errors())

    def test_ai_review_records_no_user_approval_and_allows_ai_upstream(self):
        self.authorize()
        parent=self.register("analysis");self.review(parent)
        child=self.register("captions",[parent["id"]]);self.review(child)
        rows=studio.status(args(project=str(self.project)))["artifacts"]
        self.assertEqual([row["current_status"] for row in rows],["ai_reviewed","ai_reviewed"])
        self.assertTrue(all("approval" not in row for row in rows))
        self.assertFalse(list((self.project/"00_project_info").glob("approval_*.json")))
        self.workflow("select","semi_auto")
        states=studio.status(args(project=str(self.project)))["artifacts"]
        self.assertEqual(states[0]["current_status"],"workflow_authorization_invalid")
        self.assertEqual(states[1]["current_status"],"upstream_not_approved")
        with self.assertRaises(ValueError):self.review(child)

    def test_ai_review_missing_or_changed_evidence_does_not_pass(self):
        self.authorize()
        row=self.register("analysis");report,input_file=self.ai_gate(row)
        data=studio.read(report);data["ai_review"]["status"]="unverified";studio.write(report,data)
        with self.assertRaises(ValueError):self.review(row,report,input_file)
        data["ai_review"]["status"]="passed";studio.write(report,data)
        self.review(row,report,input_file)
        evidence=Path(data["ai_review"]["evidence"][0]["path"])
        evidence.write_text("已修改测试证据",encoding="utf-8")
        self.assertEqual(studio.status(args(project=str(self.project)))["artifacts"][0]["current_status"],"ai_review_invalid")

    def test_review_cannot_bind_an_unrelated_artifact(self):
        self.authorize()
        row=self.register("analysis")
        report,input_file=self.ai_gate(row,inputs={"source":self.source})
        with self.assertRaises(ValueError):self.review(row,report,input_file)

    def test_selected_asset_change_invalidates_authorization(self):
        self.authorize()
        self.background.write_bytes(b"replaced background")
        self.assertTrue(self.workflow_errors())

    def test_default_background_is_resolved_before_authorization(self):
        self.choices["background"]="default"
        studio.write(self.choices_file,self.choices)
        self.authorize()
        choice=studio.read(self.config)["confirmed_choices"]["background"]
        self.assertEqual(choice["kind"],"skill_default")
        self.assertTrue(Path(choice["path"]).is_file())
        self.assertEqual(choice["sha256"],studio.sha(choice["path"]))

    def test_native_ai_review_invokes_static_validator_without_deep_native_gate(self):
        self.authorize()
        row=self.register("native_project")
        manifest=Path(row["path"]).parent/"generation-manifest.json"
        report,input_file=self.ai_gate(row,inputs={"project":Path(row["path"]),"manifest":manifest})
        with patch("jianying_adapter.validate",return_value={"status":"STATIC_VALIDATED_NATIVE_UI_PENDING","errors":[],"native_ui_verified":False}) as validate:
            result=self.review(row,report,input_file)
        validate.assert_called_once_with(Path(row["path"]).parent)
        self.assertEqual(result["status"],"ai_reviewed")
        self.assertFalse(result["review"]["native_basic_validation"]["native_ui_verified"])
        self.assertNotIn("user_approval",studio.read(report))
        self.assertNotIn("native_export",studio.read(input_file))

    def test_native_static_failure_blocks_ai_review_record(self):
        self.authorize()
        row=self.register("native_project")
        manifest=Path(row["path"]).parent/"generation-manifest.json"
        report,input_file=self.ai_gate(row,inputs={"project":Path(row["path"]),"manifest":manifest})
        with patch("jianying_adapter.validate",return_value={"status":"blocked","errors":["missing material"]}):
            with self.assertRaises(ValueError):self.review(row,report,input_file)
        self.assertNotIn("ai_review",studio.info(self.project)[2]["artifacts"][0])

    def test_native_project_from_other_authorization_cannot_be_ai_reviewed(self):
        self.authorize()
        row=self.register("native_project")
        native_root=Path(row["path"]).parent
        original=studio.read(native_root/"approval-report.json")
        original["workflow"]["authorization"]["sha256"]="b"*64
        studio.write(native_root/"approval-report.json",original)
        report,input_file=self.ai_gate(row,inputs={"project":Path(row["path"]),
                                    "manifest":native_root/"generation-manifest.json"})
        with patch("jianying_adapter.validate",return_value={"status":"STATIC_VALIDATED_NATIVE_UI_PENDING","errors":[]}) as validate:
            with self.assertRaisesRegex(ValueError,"another workflow authorization"):
                self.review(row,report,input_file)
        validate.assert_not_called()
        self.assertNotIn("ai_review",studio.info(self.project)[2]["artifacts"][0])

    def test_native_manifest_must_belong_to_same_project(self):
        self.authorize()
        row=self.register("native_project")
        elsewhere=self.project/"05_jianying"/"generation-manifest.json"
        studio.write(elsewhere,{"content_file":Path(row["path"]).name})
        report,input_file=self.ai_gate(row,inputs={"project":Path(row["path"]),"manifest":elsewhere})
        with self.assertRaisesRegex(ValueError,"exact project directory"):
            self.review(row,report,input_file)

    def test_native_frozen_approval_change_invalidates_recorded_state(self):
        self.authorize()
        row=self.register("native_project")
        native_root=Path(row["path"]).parent
        report,input_file=self.ai_gate(row,inputs={"project":Path(row["path"]),
                                    "manifest":native_root/"generation-manifest.json"})
        with patch("jianying_adapter.validate",return_value={"status":"STATIC_VALIDATED_NATIVE_UI_PENDING","errors":[]}):
            self.review(row,report,input_file)
        (native_root/"approval-report.json").write_text('{}',encoding="utf-8")
        self.assertEqual(studio.status(args(project=str(self.project)))["artifacts"][0]["current_status"],"review_inputs_changed")

    def test_copied_active_settings_cannot_bypass_pause(self):
        self.authorize()
        copied=self.project/"90_logs_cache"/"old_active_settings.json"
        studio.write(copied,studio.read(self.config))
        stale=studio.workflow_record(studio.read(copied),copied)
        self.workflow("pause")
        self.assertTrue(validate_workflow(stale,self.config.parent),
                        "an old active config copy must not re-enable a paused project")

    def test_cli_select_semi_auto_and_explicit_pause_resume(self):
        output=io.StringIO()
        with patch.object(studio.sys,"argv",["studio_manager.py","workflow","select",
                         "--project",str(self.project),"--mode","semi_auto",
                         "--evidence-file",str(self.message)]),redirect_stdout(output):
            self.assertEqual(studio.main(),0)
        self.assertEqual(json.loads(output.getvalue())["workflow"]["mode"],"semi_auto")
        self.workflow("pause",choices=False)
        self.assertEqual(studio.read(self.config)["workflow"]["state"],"paused")
        self.workflow("resume",choices=False)
        current=studio.read(self.config)["workflow"]
        self.assertEqual(current["state"],"active")
        self.assertNotIn("authorization",current)

    def test_workflow_mutation_obeys_existing_project_lock(self):
        with studio.lock(self.project/"00_project_info"):
            with self.assertRaises(ValueError):self.workflow("select","full_auto")
        self.assertEqual(studio.read(self.config)["workflow"]["mode"],"unselected")

    def test_preference_change_revokes_active_authorization(self):
        self.authorize()
        root=self.base/"studio"
        studio.preference(args(studio_root=str(root),action="record",key="pipeline.preview.mask_diameter",
            value="650",scope="confirmed",context="all",evidence="测试模拟已确认偏好"))
        studio.apply_preferences(args(studio_root=str(root),project=str(self.project),context="all"))
        current=studio.read(self.config)["workflow"]
        self.assertEqual(current["state"],"pending")
        self.assertNotIn("authorization",current)

    def test_mode_switch_revokes_old_run_and_moving_background_requires_speed(self):
        self.authorize()
        old=studio.read(self.config)["workflow"]["authorization"]
        self.workflow("select","semi_auto")
        current=studio.read(self.config)["workflow"]
        self.assertNotIn("authorization",current)
        self.assertEqual(current["authorization_history"][-1]["authorization"],old)
        self.workflow("select","full_auto")
        self.choices["background_motion"]="right"
        studio.write(self.choices_file,self.choices)
        with self.assertRaises(ValueError):self.workflow("authorize")


if __name__ == "__main__":
    unittest.main()
