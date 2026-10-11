"""Filesystem and approval invariants; no user's media or runtime is touched."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch
import studio_manager as m


def args(**kwargs):
    return argparse.Namespace(**kwargs)


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "studio"
        self.source = self.base / "中文 原片.mp4"
        self.source.write_bytes(b"source unchanged")
        self.init_args = args(studio_root=str(self.root), title="口播项目", slug="talking_head",
                              date="20261012", source=[str(self.source)], copy_inputs=True)
        self.project = Path(m.init_project(self.init_args)["project"])

    def test_ascii_tree_source_preservation_and_collision(self):
        second = Path(m.init_project(self.init_args)["project"])
        self.assertNotEqual(self.project, second)
        self.assertTrue(all(str(p.relative_to(self.root)).isascii() for p in self.root.rglob("*")))
        self.assertEqual(self.source.read_bytes(), b"source unchanged")
        self.assertEqual((self.project / "01_inputs/video_01.mp4").read_bytes(), self.source.read_bytes())
        self.assertIn("完整预览", (self.project / "00_project_info/README_zh.md").read_text())

    def test_reserved_and_traversal_slugs_rejected(self):
        for bad in ("con", "CON", "../other", "a:b", "a ", "中文", "a" * 49):
            with self.assertRaises(ValueError):
                m.checked_slug(bad)

    def record_preference(self, scope, value, context="all"):
        return m.preference(args(studio_root=str(self.root), action="record", key="pipeline.preview.mask_diameter",
                                 value=json.dumps(value), scope=scope, evidence="用户实际反馈", context=context))

    def test_candidates_do_not_become_defaults(self):
        self.record_preference("candidate", 800)
        result = m.apply_preferences(args(studio_root=str(self.root), project=str(self.project), context="all"))
        self.assertEqual(result["keys"], [])
        self.assertEqual(m.read(m.settings_path(self.project))["pipeline"]["preview"]["mask_diameter"], 620)

    def test_project_choice_overrides_confirmed_preference(self):
        self.record_preference("confirmed", 700)
        m.apply_preferences(args(studio_root=str(self.root), project=str(self.project), context="all"))
        self.assertEqual(m.read(m.settings_path(self.project))["pipeline"]["preview"]["mask_diameter"], 700)
        m.set_setting(args(project=str(self.project), key="pipeline.preview.mask_diameter", value="640", evidence="这次640"))
        self.record_preference("confirmed", 800)
        m.apply_preferences(args(studio_root=str(self.root), project=str(self.project), context="all"))
        self.assertEqual(m.read(m.settings_path(self.project))["pipeline"]["preview"]["mask_diameter"], 640)

    def test_context_and_forget(self):
        self.record_preference("confirmed", 700, "portrait")
        self.assertEqual(m.apply_preferences(args(studio_root=str(self.root), project=str(self.project), context="landscape"))["keys"], [])
        m.preference(args(studio_root=str(self.root), action="forget", key="pipeline.preview.mask_diameter", context="portrait", evidence="忘掉此偏好"))
        self.assertEqual(m.apply_preferences(args(studio_root=str(self.root), project=str(self.project), context="portrait"))["keys"], [])

    def add_asset(self):
        source = self.base / "我的背景.png"
        source.write_bytes(b"background")
        request = args(studio_root=str(self.root), file=str(source), kind="backgrounds", title="默认背景", tag=["grid"],
                       origin=None, rights="user_approved", evidence="允许本人以后复用")
        return source, request, m.asset_add(request)

    def test_dedup_and_project_snapshot_survives_library_change(self):
        source, request, result = self.add_asset()
        self.assertEqual(m.asset_add(request)["status"], "reused")
        copied = m.asset_use(args(studio_root=str(self.root), project=str(self.project), asset_id=result["asset"]["id"]))
        library_file = self.root / result["asset"]["path"]
        library_file.write_bytes(b"changed library")
        self.assertEqual(Path(copied["file"]).read_bytes(), b"background")
        with self.assertRaises(ValueError):
            m.asset_use(args(studio_root=str(self.root), project=str(self.project), asset_id=result["asset"]["id"]))

    def test_font_binary_not_distributed(self):
        _, request, _ = self.add_asset()
        font = self.base / "private.otf"
        font.write_bytes(b"font")
        request.file = str(font)
        with self.assertRaises(ValueError):
            m.asset_add(request)

    def register(self, kind, name, depends=None):
        path = self.project / "04_previews" / name
        path.write_bytes(name.encode())
        return m.register_artifact(args(project=str(self.project), file=str(path), kind=kind, depends_on=depends or []))["artifact"]

    def approve(self, row):
        return m.approve(args(project=str(self.project), artifact_id=row["id"], evidence="用户确认这个完整版本"))

    def test_changed_file_invalidates_downstream(self):
        parent = self.register("rough_cut", "rough_v001.mp4")
        self.approve(parent)
        child = self.register("captions", "captions_v001.ass", [parent["id"]])
        self.approve(child)
        Path(parent["path"]).write_bytes(b"edited")
        states = m.status(args(project=str(self.project)))["artifacts"]
        self.assertEqual(states[0]["current_status"], "changed_approval_invalid")
        self.assertEqual(states[1]["current_status"], "upstream_not_approved")
        with self.assertRaises(ValueError):
            self.approve(child)

    def test_style_only_change_does_not_invalidate_rough_cut(self):
        parent = self.register("rough_cut", "rough_v001.mp4")
        self.approve(parent)
        child = self.register("captions", "captions_v001.ass", [parent["id"]])
        self.approve(child)
        m.set_setting(args(project=str(self.project), key="pipeline.captions.pos_y", value="1000", evidence="字幕位置调整"))
        rows = m.status(args(project=str(self.project)))["artifacts"]
        self.assertEqual(rows[0]["current_status"], "approved")
        self.assertEqual(rows[1]["current_status"], "settings_changed_approval_invalid")

    def test_lock_excludes_second_mutation(self):
        with m.lock(self.root):
            with self.assertRaises(ValueError):
                with m.lock(self.root):
                    self.fail("concurrent writer admitted")

    def test_existing_partial_preserved(self):
        source = self.base / "new.png"
        source.write_bytes(b"new background")
        m.initialize_studio(self.root)
        partial = self.root / "assets/backgrounds" / ("asset_" + m.sha(source)[:24] + ".png.partial")
        partial.write_bytes(b"recovery file")
        request = args(studio_root=str(self.root), file=str(source), kind="backgrounds", title="new", tag=[],
                       origin=None, rights="user_approved", evidence="keep")
        with self.assertRaises(FileExistsError):
            m.asset_add(request)
        self.assertEqual(partial.read_bytes(), b"recovery file")

    def test_manifest_is_read_after_lock(self):
        real_lock = m.lock
        @contextmanager
        def concurrent_commit(root):
            _, path, data = m.info(self.project)
            data["settings_history"].append({"marker": "concurrent_commit"})
            m.write(path, data)
            with real_lock(root):
                yield
        with patch.object(m, "lock", concurrent_commit):
            m.set_setting(args(project=str(self.project), key="pipeline.preview.mask_diameter", value="650", evidence="650"))
        self.assertEqual(m.info(self.project)[2]["settings_history"][0]["marker"], "concurrent_commit")

    def test_changed_source_invalidates_confirmation(self):
        parent = self.register("rough_cut", "rough_v001.mp4")
        self.approve(parent)
        self.source.write_bytes(b"replacement source")
        state = m.status(args(project=str(self.project)))
        self.assertEqual(state["sources"][0]["current_status"], "changed")
        self.assertEqual(state["artifacts"][0]["current_status"], "source_changed_approval_invalid")
        with self.assertRaises(ValueError):
            self.approve(parent)


if __name__ == "__main__":
    unittest.main()
