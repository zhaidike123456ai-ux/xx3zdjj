"""Behavior tests with tiny local HTTP fixtures and mock installers; no large downloads."""
import argparse
import functools
import hashlib
import http.server
import io
import json
import os
import subprocess
import tarfile
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path
from unittest import mock
import runtime_manager as runtime


def args(root, **kwargs):
    values = dict(runtime_root=str(root), python=None, ffmpeg=None, ffprobe=None, ffmpeg_dir=None,
                  node=None, node_project=None, model_path=None, allow_install=False, authorization_note=None)
    values.update(kwargs)
    return argparse.Namespace(**values)


def fixture_report(root, model=True):
    tools = {k: {'status': 'available', 'path': str(Path(root) / ('fake-' + k)), 'version': 'fixture'} for k in runtime.REQUIRED_TOOLS}
    for key in ('remotion', 'hyperframes'):
        tools[key]['project'] = str(Path(root) / 'js')
    tools['model'].update({'path': str(Path(root) / 'model') if model else None, 'status': 'available' if model else 'missing'})
    return {'tools': tools, 'ready': model, 'read_only': True, 'platform': runtime.machine(), 'missing_install_plan': []}


class FakeManager(runtime.RuntimeManager):
    """Exercise actual ensure transaction/authorization logic, not package networking."""
    def __init__(self, namespace, fail=False):
        super().__init__(namespace)
        self.platform = dict(self.platform, os='Darwin', key='Darwin-arm64', macos='26.0')
        self.fail = fail
        self.install_count = 0
    def check(self):
        return fixture_report(self.root, model=(self.root / 'model' / 'model.bin').is_file())
    def install_model(self):
        self.install_count += 1
        (self.root / 'model').mkdir(parents=True, exist_ok=True)
        (self.root / 'model' / 'model.bin').write_bytes(b'fixture')
        if self.fail:
            raise RuntimeError('mock download interrupted')
    def smoke(self, report=None):
        return {'passed': True, 'fingerprint': 'fixture-fingerprint', 'tests': {}}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xx3zdjj-test-')
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def server(self, folder):
        handler = functools.partial(QuietHandler, directory=str(folder))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return 'http://127.0.0.1:' + str(server.server_port)

    def test_verified_http_stream_cached_and_corrupt_download_preserves_previous(self):
        publisher = self.root / 'publisher'
        publisher.mkdir()
        (publisher / 'archive.bin').write_bytes(b'fixture-archive')
        url = self.server(publisher) + '/archive.bin'
        target = self.root / 'cache' / 'archive.bin'
        digest = hashlib.sha256(b'fixture-archive').hexdigest()
        runtime.download_verified(url, target, digest, opener=urllib.request.urlopen)
        self.assertEqual(target.read_bytes(), b'fixture-archive')
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('cached download must not request')):
            runtime.download_verified(url, target, digest, opener=urllib.request.urlopen)
        with self.assertRaises(ValueError):
            runtime.download_verified(url, target, '0' * 64, opener=urllib.request.urlopen)
        self.assertEqual(target.read_bytes(), b'fixture-archive')
        self.assertEqual(list(target.parent.glob('*.partial-*')), [])

    def test_zip_traversal_blocked_before_any_extraction(self):
        archive = self.root / 'bad.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('good.txt', 'good')
            z.writestr('../escape.txt', 'escape')
        with self.assertRaises(ValueError):
            runtime.extract_verified(archive, self.root / 'extract')
        self.assertFalse((self.root / 'escape.txt').exists())
        self.assertFalse((self.root / 'extract/good.txt').exists())

    def test_tar_escaping_symlink_blocked_safe_internal_node_link_allowed(self):
        archive = self.root / 'node.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            content = b'node-fixture'
            info = tarfile.TarInfo('node/lib/npm-cli.js'); info.size = len(content)
            t.addfile(info, io.BytesIO(content))
            link = tarfile.TarInfo('node/bin/npm'); link.type = tarfile.SYMTYPE; link.linkname = '../lib/npm-cli.js'
            t.addfile(link)
        runtime.extract_verified(archive, self.root / 'safe')
        self.assertEqual((self.root / 'safe/node/bin/npm').read_bytes(), b'node-fixture')
        archive = self.root / 'unsafe.tar.gz'
        with tarfile.open(archive, 'w:gz') as t:
            link = tarfile.TarInfo('node/bin/npm'); link.type = tarfile.SYMTYPE; link.linkname = '../../../outside'
            t.addfile(link)
        with self.assertRaises(ValueError):
            runtime.extract_verified(archive, self.root / 'unsafe')

    def test_lock_is_exclusive_and_cleanup_occurs_on_failure(self):
        with self.assertRaises(RuntimeError):
            with runtime.install_lock(self.root):
                with runtime.install_lock(self.root):
                    pass
        self.assertFalse((self.root / 'install.lock').exists())

    def test_check_and_unauthorized_ensure_do_not_create_runtime_root(self):
        root = self.root / 'does-not-exist'
        manager = FakeManager(args(root))
        self.assertFalse(manager.check()['ready'])
        report = manager.ensure()
        self.assertTrue(report['authorization_required'])
        self.assertFalse(root.exists())
        self.assertEqual(manager.install_count, 0)

    def test_authorized_install_atomic_activation_then_reuses_model_and_consent(self):
        root = self.root / 'runtime'
        manager = FakeManager(args(root, allow_install=True, authorization_note='fixture user approval'))
        self.assertTrue(manager.ensure()['activated'])
        self.assertEqual(manager.install_count, 1)
        policy = runtime.read_json(root / 'install-policy.json')
        self.assertEqual(policy['authorization_note'], 'fixture user approval')
        next_manager = FakeManager(args(root))
        self.assertTrue(next_manager.ensure()['activated'])
        self.assertEqual(next_manager.install_count, 0)
        self.assertEqual(runtime.read_json(root / 'active.json')['smoke_fingerprint'], 'fixture-fingerprint')

    def test_failed_install_keeps_old_activation_exactly(self):
        root = self.root / 'runtime'
        old = {'schema_version': 1, 'platform': 'Darwin-arm64', 'tools': {'old': {'path': 'preserved'}}}
        runtime.atomic_json(root / 'active.json', old)
        manager = FakeManager(args(root, allow_install=True), fail=True)
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            manager.ensure()
        self.assertEqual(runtime.read_json(root / 'active.json'), old)
        self.assertTrue(runtime.read_json(root / 'last-failure.json')['old_activation_preserved'])
        self.assertFalse((root / 'install.lock').exists())

    def test_foreign_machine_authorization_not_reused(self):
        root = self.root / 'runtime'
        runtime.atomic_json(root / 'install-policy.json', {'allow_install': True, 'machine_id': 'other-machine'})
        self.assertTrue(FakeManager(args(root)).ensure()['authorization_required'])

    def test_all_existing_needs_no_install_permission_and_search_diagnostics_do_not_retest(self):
        root = self.root / 'runtime'
        (root / 'model').mkdir(parents=True)
        (root / 'model/model.bin').write_bytes(b'fixture')
        manager = FakeManager(args(root))
        self.assertFalse(manager.ensure()['authorization_required'])
        self.assertFalse((root / 'active.json').exists())
        report = fixture_report(root)
        first = manager.fingerprint(report)
        report['tools']['ffmpeg']['attempts'] = [{'status': 'missing_capabilities', 'path': 'other-tool'}]
        self.assertEqual(manager.fingerprint(report), first)

    def test_model_install_revision_lock_small_local_http_and_no_second_download(self):
        publisher = self.root / 'publisher'; publisher.mkdir()
        files = {'model.bin': b'small-model', 'config.json': b'{}', 'tokenizer.json': b'{}', 'vocabulary.txt': b'word\n'}
        siblings = []
        for name, data in files.items():
            (publisher / name).write_bytes(data)
            siblings.append({'rfilename': name, 'size': len(data), **({'lfs': {'sha256': hashlib.sha256(data).hexdigest()}} if name == 'model.bin' else {'blobId': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()})})
        url = self.server(publisher)
        manager = runtime.RuntimeManager(args(self.root / 'runtime'))
        meta = {'sha': 'a' * 40, 'siblings': siblings}
        calls = []
        def local_fetch(request_url):
            name = request_url.rsplit('/', 1)[-1]
            calls.append(name)
            return urllib.request.urlopen(url + '/' + name)
        with mock.patch.object(runtime, 'remote_json', return_value=meta), mock.patch.object(runtime, 'fetch', side_effect=local_fetch):
            manager.install_model()
            manager.install_model()
        self.assertEqual(sorted(calls), sorted(files))
        lock = runtime.read_json(Path(manager.args.model_path).parent / 'download-lock.json')
        self.assertEqual(lock['revision'], 'a' * 40)
        self.assertEqual((Path(manager.args.model_path) / 'model.bin').read_bytes(), b'small-model')

    def test_wheel_only_isolated_install_verifies_pypi_hash_before_activation(self):
        manager = runtime.RuntimeManager(args(self.root / 'runtime'))
        wheel = 'faster_whisper-1.2.1-py3-none-any.whl'; content = b'fixture wheel content'
        calls = []
        def installer(argv, **kwargs):
            argv = [str(v) for v in argv]; calls.append(argv)
            if 'download' in argv:
                folder = Path(argv[argv.index('--dest') + 1]); (folder / wheel).write_bytes(content)
            return subprocess.CompletedProcess(argv, 0, '', '')
        meta = {'urls': [{'filename': wheel, 'digests': {'sha256': hashlib.sha256(content).hexdigest()}}]}
        with mock.patch.object(runtime, 'run', side_effect=installer), mock.patch.object(runtime, 'remote_json', return_value=meta):
            manager.install_whisper('/existing/python')
        pip_calls = [c for c in calls if 'pip' in c]
        self.assertEqual(len(pip_calls), 2)
        self.assertTrue(all('--only-binary=:all:' in c for c in pip_calls))
        install = pip_calls[-1]
        self.assertIn('--require-hashes', install)
        self.assertIn('--no-index', install)
        self.assertTrue(install[0].startswith(str(manager.root / 'generations')))
        self.assertNotIn('--user', install)
        bad = runtime.RuntimeManager(args(self.root / 'bad-runtime'))
        meta['urls'][0]['digests']['sha256'] = '0' * 64
        with mock.patch.object(runtime, 'run', side_effect=installer), mock.patch.object(runtime, 'remote_json', return_value=meta):
            with self.assertRaisesRegex(ValueError, 'wheel'):
                bad.install_whisper('/existing/python')
        self.assertFalse((bad.root / 'active.json').exists())

    def test_environment_is_subprocess_only_and_exposes_local_model(self):
        report = fixture_report(self.root)
        before = os.environ.get('PATH')
        env = runtime.runtime_environment(report)
        self.assertEqual(os.environ.get('PATH'), before)
        self.assertEqual(env['XX3ZDJJ_MODEL_PATH'], report['tools']['model']['path'])
        self.assertIn(str(self.root / 'js/node_modules/.bin'), env['PATH'])
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')
        self.assertEqual(env['XX3ZDJJ_FFMPEG'], report['tools']['ffmpeg']['path'])
        self.assertEqual(env['XX3ZDJJ_FFPROBE'], report['tools']['ffprobe']['path'])

    def test_two_independent_node_projects_both_exposed(self):
        report = fixture_report(self.root)
        report['tools']['remotion']['project'] = str(self.root / 'remotion')
        report['tools']['hyperframes']['project'] = str(self.root / 'hyperframes')
        env = runtime.runtime_environment(report)
        self.assertEqual(env['NODE_PATH'].split(os.pathsep), [str(self.root / 'remotion/node_modules'), str(self.root / 'hyperframes/node_modules')])
        self.assertIn(str(self.root / 'remotion/node_modules/.bin'), env['PATH'])
        self.assertIn(str(self.root / 'hyperframes/node_modules/.bin'), env['PATH'])

    def test_semantic_version_and_arch_detection(self):
        self.assertLess(runtime.version_tuple('Python 3.9.1'), runtime.version_tuple('Python 3.11.0'))
        with mock.patch('platform.system', return_value='Windows'), mock.patch('platform.machine', return_value='AMD64'):
            self.assertEqual(runtime.machine()['key'], 'Windows-x64')


if __name__ == '__main__':
    unittest.main(verbosity=2)
