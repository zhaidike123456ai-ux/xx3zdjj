#!/usr/bin/env python3
"""Isolated, consent-gated runtime management. `check` never installs or writes state.

Only subprocess PATH is changed. No media are uploaded. Downloads use TLS and
publisher hashes; install generations are immutable and activated atomically.
"""
import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = SKILL_ROOT / 'assets' / 'dependencies.json'
REQUIRED_TOOLS = ('python', 'ffmpeg', 'ffprobe', 'faster_whisper', 'model', 'node', 'remotion', 'hyperframes')
FILTERS = {'ass', 'overlay', 'geq', 'trim', 'atrim', 'crop', 'scale', 'concat'}
ENCODERS = {'libx264', 'aac'}


def default_root():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'xx3zdjj' / 'runtime'
    return Path.home() / 'Library' / 'Application Support' / 'xx3zdjj' / 'runtime'


def machine():
    arch = platform.machine().lower()
    arch = {'aarch64': 'arm64', 'amd64': 'x64', 'x86_64': 'x64'}.get(arch, arch)
    return {'os': platform.system(), 'arch': arch, 'release': platform.release(),
            'macos': platform.mac_ver()[0], 'key': platform.system() + '-' + arch}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {} if default is None else default


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with temp.open('w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextlib.contextmanager
def install_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / 'install.lock'
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError('另一个安装仍持有锁；确认该进程已结束后再移除 install.lock，不自动抢锁。')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(json.dumps({'pid': os.getpid(), 'started': time.time()}))
        yield
    finally:
        lock.unlink(missing_ok=True)


def tls_context():
    # Never disable certificate verification. certifi is optional for imported venvs.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        # Framework Python on macOS may not have run Install Certificates.command.
        # Apple ships this trusted CA bundle; TLS verification still stays enabled.
        system_ca = Path('/etc/ssl/cert.pem')
        if platform.system() == 'Darwin' and system_ca.is_file():
            return ssl.create_default_context(cafile=str(system_ca))
        return ssl.create_default_context()


def fetch(url):
    if urllib.parse.urlsplit(url).scheme != 'https':
        raise ValueError('Only HTTPS publisher URLs are accepted')
    request = urllib.request.Request(url, headers={'User-Agent': 'xx3zdjj-runtime/1'})
    return urllib.request.urlopen(request, timeout=60, context=tls_context())


def remote_json(url):
    with fetch(url) as response:
        return json.load(response)


def publisher_hash(url, filename=None):
    with fetch(url) as response:
        data = response.read(2 * 1024 * 1024).decode('utf-8')
    for line in data.splitlines():
        parts = line.split()
        if parts and re.fullmatch(r'[a-fA-F0-9]{64}', parts[0]):
            if filename is None or any(p.lstrip('*') == filename for p in parts[1:]):
                return parts[0].lower()
    raise ValueError('Publisher SHA256 not found: ' + str(filename))


def download_verified(url, destination, digest, algorithm='sha256', opener=None):
    """Stream to a partial file; never expose corrupt or incomplete cached archives."""
    if not re.fullmatch(r'[a-fA-F0-9]+', digest or ''):
        raise ValueError('Missing publisher digest')
    opener = opener or fetch
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and file_digest(destination, algorithm) == digest.lower():
        return destination
    partial = destination.with_name(destination.name + '.partial-' + uuid.uuid4().hex)
    h = hashlib.new(algorithm)
    # HF small non-LFS files carry git blob SHA1, not ordinary SHA1.
    try:
        with opener(url) as response, partial.open('wb') as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != digest.lower():
            raise ValueError('下载校验失败: ' + destination.name)
        os.replace(partial, destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


def file_digest(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def extract_verified(archive, destination):
    """Reject traversal, links, device files and archive bombs before extraction."""
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    max_bytes = 3 * 1024 ** 3
    def safe_name(name):
        # Windows drive letters / backslashes are unsafe on every platform.
        if '\\' in name or ':' in name:
            raise ValueError('Unsafe archive path')
        target = (destination / name).resolve()
        if target != destination and destination not in target.parents:
            raise ValueError('Archive traversal blocked')
        return target
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            if sum(i.file_size for i in z.infolist()) > max_bytes:
                raise ValueError('Archive too large')
            for info in z.infolist():
                safe_name(info.filename)
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError('Archive links blocked')
            z.extractall(destination)
    else:
        with tarfile.open(archive) as t:
            members = t.getmembers()
            if sum(m.size for m in members) > max_bytes:
                raise ValueError('Archive too large')
            for member in members:
                safe_name(member.name)
                if member.issym():
                    # Node's official tarballs contain npm/npx internal symlinks.
                    safe_name(str(Path(member.name).parent / member.linkname))
                elif member.islnk():
                    safe_name(member.linkname)
                elif not (member.isfile() or member.isdir()):
                    raise ValueError('Archive device files blocked')
            # Links are extracted last, preventing a later member writing through one.
            members.sort(key=lambda m: m.issym() or m.islnk())
            # Validated members; Python 3.9 compatibility without filter argument.
            t.extractall(destination, members=members)


def run(argv, timeout=30, env=None, cwd=None, check=False):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout,
                            env=env or quiet_environment(), cwd=cwd)
    if check and result.returncode:
        raise RuntimeError('命令失败: ' + str(argv[0]) + '\n' + result.stderr[-3000:])
    return result


def quiet_environment():
    env = dict(os.environ)
    env.update({'PYTHONDONTWRITEBYTECODE': '1', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
                'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
                'HYPERFRAMES_NO_TELEMETRY': '1', 'HYPERFRAMES_NO_UPDATE_CHECK': '1',
                'DO_NOT_TRACK': '1', 'npm_config_update_notifier': 'false'})
    return env


def version_tuple(text):
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', text)
    return tuple(int(n or 0) for n in match.groups()) if match else ()


def candidate_paths(explicit, recorded, names):
    paths = []
    for value in [explicit, recorded] + [shutil.which(n) for n in names]:
        if value:
            p = str(Path(value).expanduser().absolute())
            if p not in paths:
                paths.append(p)
    return paths


def probe_executable(paths, args, predicate=None):
    failures = []
    for path in paths:
        try:
            result = run([path] + list(args))
            text = (result.stdout or result.stderr).strip()
            if result.returncode == 0 and (predicate is None or predicate(text)):
                return {'status': 'available', 'path': path, 'version': text.splitlines()[0] if text else ''}
            failures.append({'path': path, 'error': text[-1000:] or 'incompatible version'})
        except (OSError, subprocess.TimeoutExpired) as error:
            failures.append({'path': path, 'error': str(error)})
    return {'status': 'missing_or_incompatible', 'path': None, 'attempts': failures}


def runtime_environment(report, base=None):
    env = dict(base or quiet_environment())
    tools = report.get('tools', {})
    dirs = []
    for key in ('ffmpeg', 'ffprobe', 'python', 'node'):
        path = tools.get(key, {}).get('path')
        if path and str(Path(path).parent) not in dirs:
            dirs.append(str(Path(path).parent))
    projects = list(dict.fromkeys(tools.get(key, {}).get('project') for key in ('remotion', 'hyperframes') if tools.get(key, {}).get('project')))
    if projects:
        dirs.extend(str(Path(project) / 'node_modules' / '.bin') for project in projects)
        env['NODE_PATH'] = os.pathsep.join(str(Path(project) / 'node_modules') for project in projects)
    env['PATH'] = os.pathsep.join(dirs + [env.get('PATH', '')])
    model = tools.get('model', {}).get('path')
    if model:
        env['XX3ZDJJ_MODEL_PATH'] = model
    env['XX3ZDJJ_RUNTIME_PYTHON'] = tools.get('python', {}).get('path') or ''
    env['XX3ZDJJ_FFMPEG'] = tools.get('ffmpeg', {}).get('path') or ''
    env['XX3ZDJJ_FFPROBE'] = tools.get('ffprobe', {}).get('path') or ''
    return env


class RuntimeManager:
    def __init__(self, args, spec=None):
        self.args = args
        self.root = Path(args.runtime_root).expanduser().absolute()
        self.spec = spec or read_json(DEPENDENCIES)
        inventory_path = getattr(args, 'inventory', None)
        if inventory_path:
            old_tools = read_json(Path(inventory_path).expanduser()).get('tools', {})
            for attribute, tool, field in [('python','python','path'), ('node','node','path'), ('ffprobe','ffprobe','path'),
                                           ('model_path','faster_whisper_medium','directory')]:
                if not getattr(args, attribute):
                    setattr(args, attribute, old_tools.get(tool, {}).get(field))
            if not args.node_project:
                project = old_tools.get('remotion', {}).get('package_root')
                if project:
                    args.node_project = str(Path(project).parent if Path(project).name == 'node_modules' else Path(project))
        self.adopted_node_projects = [args.node_project] if args.node_project else []
        self.platform = machine()
        self.state = read_json(self.root / 'active.json')
        if self.state.get('platform') != self.platform['key']:
            self.state = {}

    def selected(self, name):
        return self.state.get('tools', {}).get(name, {}).get('path')

    def check(self):
        a, spec = self.args, self.spec
        tools = {}
        py_paths = candidate_paths(a.python, self.selected('python'), ['python3', 'python'])
        # The executing interpreter is a legitimate fallback, not an account-specific path.
        if sys.executable not in py_paths:
            py_paths.append(sys.executable)
        tools['python'] = probe_executable(py_paths, ['-B', '--version'],
                                           lambda s: (3, 9, 0) <= version_tuple(s) < (3, 14, 0))
        ff_paths = candidate_paths(a.ffmpeg, self.selected('ffmpeg'), ['ffmpeg'])
        if a.ffmpeg_dir:
            ff_paths.insert(0, str(Path(a.ffmpeg_dir).expanduser().absolute() / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')))
        local_ff = Path.cwd() / '.tools' / 'skill-media-bin' / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
        if local_ff.is_file() and str(local_ff) not in ff_paths:
            ff_paths.append(str(local_ff))
        failures = []
        ff = {'status': 'missing_or_incompatible', 'path': None}
        for path in ff_paths:
            p = probe_executable([path], ['-version'])
            if p['status'] == 'available':
                missing = {}
                for flag, required in [('-filters', FILTERS), ('-encoders', ENCODERS)]:
                    r = run([path, '-hide_banner', flag])
                    names = {line.split()[1] for line in r.stdout.splitlines() if len(line.split()) >= 2}
                    missing[flag] = sorted(required - names)
                p['missing_capabilities'] = missing
                if not any(missing.values()):
                    ff = p
                    break
                p['status'] = 'missing_capabilities'
            failures.append(p)
        ff['attempts'] = failures
        tools['ffmpeg'] = ff
        sibling_probe = str(Path(ff['path']).with_name('ffprobe' + ('.exe' if os.name == 'nt' else ''))) if ff['path'] else None
        probe_explicit = a.ffprobe or (str(Path(a.ffmpeg_dir).expanduser().absolute() / ('ffprobe.exe' if os.name == 'nt' else 'ffprobe')) if a.ffmpeg_dir else None)
        tools['ffprobe'] = probe_executable(candidate_paths(probe_explicit, self.selected('ffprobe') or sibling_probe, ['ffprobe']), ['-version'])
        py = tools['python']['path']
        if py:
            result = run([py, '-B', '-c', 'import json,faster_whisper,ctranslate2,ctranslate2._ext,numpy,av;print(json.dumps({"version":faster_whisper.__version__,"backend_version":ctranslate2.__version__,"numpy_version":numpy.__version__,"av_version":av.__version__,"module_paths":[faster_whisper.__file__,ctranslate2._ext.__file__]}))'], timeout=45)
            versions = json.loads(result.stdout) if result.returncode == 0 else {}
            tools['faster_whisper'] = {'status': 'available' if result.returncode == 0 else 'missing_or_broken',
                                      'path': py, **versions, 'error': result.stderr[-1000:] if result.returncode else '',
                                      'verified': 'import only; no speech listening or model inference'}
        else:
            tools['faster_whisper'] = {'status': 'missing', 'path': None}
        model_paths = []
        for value in (a.model_path, self.selected('model')):
            if value:
                model_paths.append(Path(value).expanduser().absolute())
        # Restricted known model caches; never search arbitrary private files.
        cache = Path.home() / '.cache' / 'huggingface' / 'hub' / ('models--' + spec['model']['repo'].replace('/', '--')) / 'snapshots'
        if cache.is_dir():
            model_paths.extend(sorted(cache.iterdir(), reverse=True))
        model_paths.extend(sorted((self.root / 'models').glob('*/model')) if (self.root / 'models').is_dir() else [])
        tools['model'] = {'status': 'missing', 'path': None, 'required_files': spec['model']['required']}
        for path in model_paths:
            missing = [name for name in spec['model']['required'] if not (path / name).is_file() or (path / name).stat().st_size == 0]
            if not any((path / name).is_file() and (path / name).stat().st_size for name in spec['model'].get('vocabulary_alternatives', [])):
                missing.append('vocabulary.json|vocabulary.txt')
            if not missing:
                tools['model'] = {'status': 'available', 'path': str(path), 'loading_verified': False,
                                  'verified': 'required files only; smoke loads model separately'}
                break
        tools['node'] = probe_executable(candidate_paths(a.node, self.selected('node'), ['node']), ['--version'],
                                         lambda s: version_tuple(s) >= (spec['node']['minimum_major'], 0, 0))
        node = tools['node']['path']
        js_candidates = []
        for value in [a.node_project, self.state.get('node_project')] + self.adopted_node_projects:
            if value and value not in js_candidates:
                js_candidates.append(str(Path(value).expanduser().absolute()))
        for key in ('remotion', 'hyperframes'):
            saved_project = self.state.get('tools', {}).get(key, {}).get('project')
            if saved_project:
                js_candidates.append(saved_project)
            local = Path.cwd() / '.tools' / key
            if (local / 'node_modules').is_dir():
                js_candidates.append(str(local))
        # Reuse globally discoverable CLI only by locating its package, never install globally.
        for command in ('remotion', 'hyperframes'):
            cli = shutil.which(command)
            if cli:
                resolved = Path(cli).resolve()
                for parent in resolved.parents:
                    if parent.name == 'node_modules':
                        js_candidates.append(str(parent.parent))
                        break
        for tool, package in [('remotion', 'remotion'), ('hyperframes', 'hyperframes')]:
            tools[tool] = {'status': 'missing', 'path': None}
            if not node:
                continue
            for project in dict.fromkeys(js_candidates):
                code = ('const fs=require("fs");let p=require.resolve(' + json.dumps(package + '/package.json') +
                        ',{paths:[' + json.dumps(project) + ']});let j=JSON.parse(fs.readFileSync(p,"utf8"));console.log(JSON.stringify({path:p,version:j.version,engines:j.engines||{}}));')
                result = run([node, '-e', code])
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    # Remotion requires CLI and renderer too, rather than presence of core alone.
                    if tool == 'remotion':
                        extra = run([node, '-e', 'for(const p of ["@remotion/cli/package.json","@remotion/renderer/package.json"])require.resolve(p,{paths:[' + json.dumps(project) + ']});'])
                        if extra.returncode:
                            continue
                    tools[tool] = {'status': 'available', 'path': info['path'], 'version': info['version'], 'project': project,
                                   'verified': 'package resolution only; rendering/browser not yet verified'}
                    break
        plan = []
        for key in REQUIRED_TOOLS:
            if tools[key]['status'] != 'available':
                d = spec['ffmpeg' if key == 'ffprobe' else key]
                plan.append({'tool': key, 'source': d['source'], 'binary_source': d.get('binary_source'),
                             'install_root': str(self.root), 'estimated_mb': d.get('estimated_mb', 0),
                             'note_zh': d.get('note_zh', '仅补装缺失或不兼容项；保留原环境。')})
        return {'schema_version': 1, 'platform': self.platform, 'runtime_root': str(self.root), 'tools': tools,
                'ready': not plan, 'missing_install_plan': plan, 'estimated_missing_mb': sum(p['estimated_mb'] for p in plan),
                'read_only': True, 'not_verified': ['speech_listening', 'subtitle_word_alignment', 'second_machine', 'browser_rendering']}

    def generation(self, label):
        generation = self.root / 'generations' / (label + '-' + uuid.uuid4().hex[:12])
        generation.mkdir(parents=True, exist_ok=False)
        return generation

    def install_python(self):
        key = self.platform['key']
        if key not in self.spec['uv']['archives']:
            raise RuntimeError('当前系统架构没有已核验uv发行包: ' + key)
        info = self.spec['uv']['archives'][key]
        target = self.root / 'cache' / info['name']
        download_verified(self.spec['uv']['base_url'] + info['name'], target, info['sha256'])
        generation = self.generation('python')
        extract_verified(target, generation / 'uv')
        executable = next((generation / 'uv').rglob('uv.exe' if os.name == 'nt' else 'uv'))
        executable.chmod(executable.stat().st_mode | 0o700)
        env = quiet_environment()
        env['UV_CACHE_DIR'] = str(self.root / 'cache' / 'uv')
        run([executable, 'python', 'install', self.spec['python']['version'], '--install-dir', generation / 'python', '--no-bin'], timeout=1200, env=env, check=True)
        paths = list((generation / 'python').rglob('python.exe' if os.name == 'nt' else 'python3.11'))
        if not paths:
            raise RuntimeError('uv未提供所需Python路径')
        self.args.python = str(paths[0])

    def install_ffmpeg(self):
        key = self.platform['key']
        name = self.spec['micromamba']['platform_names'].get(key)
        if not name:
            raise RuntimeError('当前架构无已核验FFmpeg补装方案；Windows ARM64需提供兼容ffmpeg/ffprobe路径。不会暗中安装x64版本。')
        binary_name = 'micromamba-' + name + ('.exe' if os.name == 'nt' else '')
        base = self.spec['micromamba']['base_url']
        digest = self.spec['micromamba']['sha256'][key]
        binary = self.root / 'cache' / binary_name
        download_verified(base + binary_name, binary, digest)
        binary.chmod(binary.stat().st_mode | 0o700)
        generation = self.generation('ffmpeg')
        prefix = generation / 'prefix'
        env = quiet_environment()
        env['MAMBA_ROOT_PREFIX'] = str(self.root / 'cache' / 'mamba')
        # --no-rc ignores user/global conda settings; exact conda-forge channel.
        run([binary, '--no-rc', 'create', '-y', '-p', prefix, '--override-channels', '-c', 'https://conda.anaconda.org/conda-forge',
             'ffmpeg=' + self.spec['ffmpeg']['version'] + '=gpl*'], timeout=1800, env=env, check=True)
        bindir = prefix / ('Library/bin' if os.name == 'nt' else 'bin')
        self.args.ffmpeg = str(bindir / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'))
        self.args.ffprobe = str(bindir / ('ffprobe.exe' if os.name == 'nt' else 'ffprobe'))
        # Preserve exact resolved builds + conda hashes for this machine outside Skill.
        result = run([binary, '--no-rc', 'list', '-p', prefix, '--explicit'], env=env, check=True)
        (generation / 'conda-explicit.lock').write_text(result.stdout, encoding='utf-8')

    def install_whisper(self, python):
        generation = self.generation('whisper')
        venv = generation / 'venv'
        run([python, '-B', '-m', 'venv', venv], timeout=120, check=True)
        py = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        wheels = generation / 'wheels'
        wheels.mkdir()
        env = quiet_environment()
        # An adopted environment may have private/global pip settings. Never reuse
        # extra indexes or trusted-host switches for this isolated official install.
        env = {k: v for k, v in env.items() if not k.upper().startswith('PIP_')}
        env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
        env['PIP_CONFIG_FILE'] = os.devnull
        # Wheel-only: never execute untrusted setup/build hooks; no global pip.
        run([py, '-B', '-m', 'pip', 'download', '--index-url', 'https://pypi.org/simple', '--only-binary=:all:',
             '--dest', wheels, 'faster-whisper==' + self.spec['faster_whisper']['version']], timeout=900, env=env, check=True)
        lock_lines = []
        for wheel in sorted(wheels.glob('*.whl')):
            name, version = wheel.name.split('-')[:2]
            meta = remote_json(self.spec['faster_whisper']['registry'] + '/' + urllib.parse.quote(name) + '/' + urllib.parse.quote(version) + '/json')
            digests = {r['filename']: r['digests']['sha256'] for r in meta['urls']}
            digest = digests.get(wheel.name)
            if not digest or file_digest(wheel) != digest:
                raise ValueError('PyPI wheel发布哈希校验失败: ' + wheel.name)
            lock_lines.append(name.replace('_', '-') + '==' + version + ' --hash=sha256:' + digest)
        lock = generation / 'requirements.lock'
        lock.write_text('\n'.join(lock_lines) + '\n', encoding='utf-8')
        run([py, '-B', '-m', 'pip', 'install', '--no-index', '--find-links', wheels, '--only-binary=:all:', '--require-hashes', '-r', lock], timeout=900, env=env, check=True)
        self.args.python = str(py)

    def install_node(self):
        os_name = {'Darwin': 'darwin', 'Windows': 'win'}.get(self.platform['os'])
        if not os_name or self.platform['arch'] not in ('x64', 'arm64'):
            raise RuntimeError('当前系统架构无已核验Node发行包')
        version = self.spec['node']['version']
        filename = 'node-v' + version + '-' + os_name + '-' + self.platform['arch'] + ('.zip' if os.name == 'nt' else '.tar.gz')
        base = self.spec['node']['base_url']
        digest = publisher_hash(base + 'SHASUMS256.txt', filename)
        archive = self.root / 'cache' / filename
        download_verified(base + filename, archive, digest)
        generation = self.generation('node')
        extract_verified(archive, generation)
        node = next(generation.rglob('node.exe' if os.name == 'nt' else 'bin/node'))
        node.chmod(node.stat().st_mode | 0o700)
        self.args.node = str(node)

    def install_javascript(self, node, report):
        generation = self.generation('javascript')
        deps = {}
        if report['tools']['remotion']['status'] != 'available':
            deps.update({p: self.spec['remotion']['version'] for p in self.spec['remotion']['packages']})
        if report['tools']['hyperframes']['status'] != 'available':
            deps['hyperframes'] = self.spec['hyperframes']['version']
        for key in ('remotion', 'hyperframes'):
            project = report['tools'][key].get('project')
            if project:
                self.adopted_node_projects.append(project)
        atomic_json(generation / 'package.json', {'name': 'xx3zdjj-local-runtime', 'private': True, 'version': '1.0.0', 'dependencies': deps})
        # Invoke npm-cli.js via the selected Node; avoids shell/bat quoting and PATH ambiguity.
        node_path = Path(node).resolve()
        candidates = [node_path.parent / 'node_modules/npm/bin/npm-cli.js', node_path.parent.parent / 'lib/node_modules/npm/bin/npm-cli.js']
        npm_cli = next((p for p in candidates if p.is_file()), None)
        if not npm_cli:
            npm_command = shutil.which('npm')
            if npm_command:
                resolved = Path(npm_command).resolve()
                if resolved.name == 'npm-cli.js':
                    npm_cli = resolved
        if not npm_cli:
            raise RuntimeError('所选Node缺少npm-cli.js；请提供完整Node分发包。')
        env = quiet_environment()
        env['PATH'] = str(node_path.parent) + os.pathsep + env.get('PATH', '')
        env['npm_config_cache'] = str(self.root / 'cache' / 'npm')
        env['npm_config_userconfig'] = str(generation / 'empty-npmrc')
        env['npm_config_globalconfig'] = str(generation / 'empty-global-npmrc')
        (generation / 'empty-npmrc').write_text('', encoding='utf-8')
        (generation / 'empty-global-npmrc').write_text('', encoding='utf-8')
        run([node, npm_cli, 'install', '--prefix', generation, '--ignore-scripts', '--no-audit', '--no-fund', '--registry=https://registry.npmjs.org/', '--package-lock=true'], timeout=1200, env=env, check=True)
        # npm validates SRI for registry packages; refuse a lock without integrity.
        lock = read_json(generation / 'package-lock.json')
        for name, package in lock.get('packages', {}).items():
            if name and not package.get('link') and not package.get('integrity'):
                raise RuntimeError('npm包缺少integrity: ' + name)
        self.args.node_project = str(generation)

    def install_model(self):
        repo = self.spec['model']['repo']
        meta = remote_json('https://huggingface.co/api/models/' + repo + '/revision/main?blobs=true')
        revision = meta['sha']
        if not re.fullmatch(r'[a-f0-9]{40}', revision):
            raise ValueError('Invalid model commit')
        destination = self.root / 'models' / revision / 'model'
        destination.mkdir(parents=True, exist_ok=True)
        files = {s['rfilename']: s for s in meta['siblings']}
        audit = {'repo': repo, 'revision': revision, 'files': {}}
        names = list(self.spec['model']['required'])
        vocabulary = next((n for n in self.spec['model'].get('vocabulary_alternatives', []) if n in files), None)
        if not vocabulary:
            raise RuntimeError('模型缺少词表')
        names.append(vocabulary)
        if 'preprocessor_config.json' in files:
            names.append('preprocessor_config.json')
        for name in names:
            info = files.get(name)
            if not info:
                raise RuntimeError('模型仓库缺少必需文件: ' + name)
            url = 'https://huggingface.co/' + repo + '/resolve/' + revision + '/' + name
            lfs = info.get('lfs', {})
            if lfs.get('sha256'):
                digest = lfs['sha256']
                download_verified(url, destination / name, digest)
                audit['files'][name] = {'sha256': digest, 'size': info.get('size')}
            else:
                # Git blob SHA1 covers "blob <size>\0" + content; small metadata only.
                target = destination / name
                expected = info.get('blobId')
                data = target.read_bytes() if target.is_file() else None
                def blob_hash(b):
                    return hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()
                if data is None or blob_hash(data) != expected:
                    with fetch(url) as response:
                        data = response.read(16 * 1024 * 1024)
                    if not expected or blob_hash(data) != expected:
                        raise ValueError('模型metadata Git hash校验失败: ' + name)
                    temp = target.with_name(name + '.partial')
                    temp.write_bytes(data)
                    os.replace(temp, target)
                audit['files'][name] = {'git_blob_sha1': expected, 'size': len(data)}
        atomic_json(destination.parent / 'download-lock.json', audit)
        self.args.model_path = str(destination)

    def ensure(self):
        policy_path = self.root / 'install-policy.json'
        machine_id = hashlib.sha256((platform.node() + '|' + str(Path.home()) + '|' + self.platform['key']).encode()).hexdigest()
        policy = read_json(policy_path)
        authorized = self.args.allow_install or (policy.get('allow_install') is True and policy.get('machine_id') == machine_id)
        if not authorized:
            report = self.check()
            report['authorization_required'] = not report['ready']
            report['message_zh'] = ('已有工具齐备，可以直接复用；没有发生安装或写入。' if report['ready'] else
                                    '仅检查；补装需用户已有授权后传入 --allow-install。')
            return report
        if self.platform['os'] not in ('Darwin', 'Windows'):
            raise RuntimeError('自动补装当前仅支持macOS和Windows；其他系统只可检查/显式采用已有工具。')
        if self.platform['key'] == 'Windows-arm64' and not self.check()['ready']:
            raise RuntimeError('Windows ARM64当前缺少已核验的CTranslate2原生wheel组合；只支持显式采用已验证环境，不自动回退x64模拟版本。')
        if self.platform['os'] == 'Darwin' and version_tuple(self.platform['macos']) < (15, 0, 0) and self.check()['tools']['remotion']['status'] != 'available':
            raise RuntimeError('当前固定Remotion版本渲染要求macOS 15+；此机器不能盲目补装当前版。请采用经实际验证的旧版环境。')
        with install_lock(self.root):
            if self.args.allow_install:
                atomic_json(policy_path, {'allow_install': True, 'machine_id': machine_id, 'recorded_at': time.time(),
                                         'authorization_note': self.args.authorization_note or '用户已授权补装本Skill必要本地工具',
                                         'scope': list(REQUIRED_TOOLS), 'source_manifest': str(DEPENDENCIES),
                                         'does_not_authorize': ['other_skills', 'payment', 'media_upload', 'global_install']})
            report = self.check()
            if report['missing_install_plan']:
                required_space = int(report['estimated_missing_mb'] * 1024 ** 2 * 1.5)
                if shutil.disk_usage(self.root).free < required_space:
                    raise RuntimeError('磁盘可用空间不足，含缓存需约' + str(round(required_space / 1024 ** 2)) + 'MB，未开始补装。')
            original = read_json(self.root / 'active.json')
            try:
                if report['tools']['python']['status'] != 'available':
                    self.install_python()
                    report = self.check()
                if report['tools']['ffmpeg']['status'] != 'available' or report['tools']['ffprobe']['status'] != 'available':
                    self.install_ffmpeg()
                    report = self.check()
                if report['tools']['faster_whisper']['status'] != 'available':
                    self.install_whisper(report['tools']['python']['path'])
                    report = self.check()
                if report['tools']['node']['status'] != 'available':
                    self.install_node()
                    report = self.check()
                if any(report['tools'][k]['status'] != 'available' for k in ('remotion', 'hyperframes')):
                    self.install_javascript(report['tools']['node']['path'], report)
                    report = self.check()
                if report['tools']['model']['status'] != 'available':
                    self.install_model()
                    report = self.check()
                if not report['ready']:
                    raise RuntimeError('补装后检查未通过，未启用新环境: ' + json.dumps(report['missing_install_plan'], ensure_ascii=False))
                # Validate functionality before activation; failures preserve the previous pointer.
                smoke = self.smoke(report)
                if not smoke['passed']:
                    raise RuntimeError('小测试失败，旧环境保持启用: ' + json.dumps(smoke, ensure_ascii=False))
                activation = {'schema_version': 1, 'platform': self.platform['key'], 'tools': report['tools'],
                              'node_project': self.args.node_project or report['tools']['remotion'].get('project'),
                              'activated_at': time.time(), 'smoke_fingerprint': smoke['fingerprint']}
                if original:
                    atomic_json(self.root / 'previous-active.json', original)
                atomic_json(self.root / 'active.json', activation)
                report.update({'read_only': False, 'activated': True, 'smoke': smoke})
                return report
            except Exception as error:
                # No original generations or pointers are removed, even on disk/full/network errors.
                atomic_json(self.root / 'last-failure.json', {'time': time.time(), 'error': str(error), 'old_activation_preserved': True})
                raise

    def fingerprint(self, report):
        # Candidate search diagnostics must not invalidate an unchanged selected runtime.
        relevant = {'path', 'version', 'backend_version', 'numpy_version', 'av_version',
                    'project', 'module_paths', 'missing_capabilities'}
        selected = {key: {k: v for k, v in tool.items() if k in relevant} for key, tool in report['tools'].items()}
        evidence = {'platform': self.platform, 'tools': selected, 'smoke_schema': 1}
        stats = {}
        for key, tool in report['tools'].items():
            p = tool.get('path')
            if p and Path(p).exists():
                paths = [Path(p)]
                if key == 'model':
                    paths = [Path(p) / n for n in self.spec['model']['required'] + self.spec['model'].get('vocabulary_alternatives', [])]
                elif key == 'faster_whisper':
                    paths.extend(Path(n) for n in tool.get('module_paths', []))
                elif key in ('remotion', 'hyperframes'):
                    paths.append(Path(tool['project']) / 'package-lock.json')
                for path in paths:
                    if path.exists():
                        s = path.stat()
                        stats[str(path)] = [s.st_size, s.st_mtime_ns]
        evidence['files'] = stats
        return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()

    def smoke(self, report=None):
        report = report or self.check()
        fingerprint = self.fingerprint(report)
        cached = read_json(self.root / 'smoke-cache' / (fingerprint + '.json'))
        if cached.get('passed'):
            return dict(cached, cached=True)
        if not report['ready']:
            return {'passed': False, 'fingerprint': fingerprint, 'error': '依赖未齐，未进行功能测试', 'tests': {}}
        env = runtime_environment(report)
        tools = report['tools']
        tests = {}
        # Temporary fixtures only, never user media. Node CLI no browser downloads.
        with tempfile.TemporaryDirectory(prefix='xx3zdjj-smoke-') as folder:
            folder = Path(folder)
            target = folder / 'smoke.mp4'
            try:
                run([tools['ffmpeg']['path'], '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=30:d=0.2',
                     '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', target], timeout=60, env=env, check=True)
                r = run([tools['ffprobe']['path'], '-v', 'error', '-show_streams', '-of', 'json', target], env=env, check=True)
                codecs = {s['codec_name'] for s in json.loads(r.stdout)['streams']}
                tests['ffmpeg_ffprobe'] = {'passed': {'h264', 'aac'} <= codecs, 'codecs': sorted(codecs)}
            except Exception as error:
                tests['ffmpeg_ffprobe'] = {'passed': False, 'error': str(error)}
            try:
                code = 'import sys,numpy as np;from faster_whisper import WhisperModel;m=WhisperModel(sys.argv[1],device="cpu",compute_type="int8",cpu_threads=4,local_files_only=True);s,i=m.transcribe(np.zeros(16000,dtype=np.float32),beam_size=1,vad_filter=False);list(s);print("model_loaded_and_synthetic_inference")'
                r = run([tools['python']['path'], '-B', '-c', code, tools['model']['path']], timeout=300, env=env, check=True)
                tests['whisper_model'] = {'passed': True, 'evidence': r.stdout.strip(), 'speech_listening_verified': False}
            except Exception as error:
                tests['whisper_model'] = {'passed': False, 'error': str(error)}
            for key, cli in [('remotion', '@remotion/cli'), ('hyperframes', 'hyperframes')]:
                try:
                    project = tools[key]['project']
                    code = 'const fs=require("fs"),path=require("path");let p=require.resolve(' + json.dumps(cli + '/package.json') + ',{paths:[' + json.dumps(project) + ']});let j=JSON.parse(fs.readFileSync(p,"utf8"));let b=typeof j.bin==="string"?j.bin:Object.values(j.bin)[0];console.log(path.resolve(path.dirname(p),b))'
                    r = run([tools['node']['path'], '-e', code], env=env, check=True)
                    r = run([tools['node']['path'], r.stdout.strip(), '--help'], timeout=60, env=env, check=True)
                    tests[key + '_cli'] = {'passed': True, 'evidence': r.stdout[:300], 'render_verified': False}
                except Exception as error:
                    tests[key + '_cli'] = {'passed': False, 'error': str(error)}
        result = {'passed': all(t['passed'] for t in tests.values()), 'fingerprint': fingerprint,
                  'cached': False, 'tests': tests, 'not_verified': ['human_speech_listening', 'browser_rendering', 'subtitle_timing', 'second_machine']}
        atomic_json(self.root / 'smoke-cache' / (fingerprint + '.json'), result)
        return result


def add_runtime_arguments(parser):
    parser.add_argument('--runtime-root', default=str(default_root()))
    parser.add_argument('--python', help='采用已有兼容Python，不修改它')
    parser.add_argument('--ffmpeg', help='采用带libass/libx264/aac的已有FFmpeg')
    parser.add_argument('--ffprobe', help='采用已有FFprobe')
    parser.add_argument('--ffmpeg-dir', help='已有ffmpeg/ffprobe所在目录；仍按能力核验')
    parser.add_argument('--node', help='采用已有Node >=22')
    parser.add_argument('--node-project', help='已有Remotion/HyperFrames node_modules所在项目；只读采用')
    parser.add_argument('--model-path', help='已有本地CTranslate2模型目录；不上传')
    parser.add_argument('--inventory', help='采用此前本地工具检查JSON中的路径；仍逐项校验，不采用其通过/授权声明')


def main(argv=None):
    parser = argparse.ArgumentParser(description='环境检查默认只读；补装需 --allow-install。')
    add_runtime_arguments(parser)
    parser.add_argument('--allow-install', action='store_true')
    parser.add_argument('--authorization-note', help='用户已有补装授权依据，仅记入本机外置策略')
    parser.add_argument('command', choices=['check', 'ensure', 'smoke', 'exec'])
    parser.add_argument('program', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    manager = RuntimeManager(args)
    try:
        if args.command == 'exec':
            report = manager.check()
            program = args.program[1:] if args.program[:1] == ['--'] else args.program
            if not program:
                parser.error('exec需要 -- 后的命令')
            if program[0] in ('python', 'python3'):
                program[0] = report['tools']['python'].get('path') or program[0]
            elif program[0] == 'node':
                program[0] = report['tools']['node'].get('path') or program[0]
            elif program[0] in ('ffmpeg', 'ffprobe'):
                key = program[0]
                if report['tools'][key]['status'] != 'available':
                    raise RuntimeError('所选' + key + '不可用')
                program[0] = report['tools'][key]['path']
            elif program[0] in ('remotion', 'hyperframes'):
                key = program[0]
                tool = report['tools'][key]
                if tool['status'] != 'available':
                    raise RuntimeError('所选' + key + '不可用')
                package = '@remotion/cli' if key == 'remotion' else 'hyperframes'
                package_json = Path(tool['project']) / 'node_modules' / package / 'package.json'
                meta = read_json(package_json)
                binary = meta['bin'] if isinstance(meta['bin'], str) else meta['bin'].get(key, next(iter(meta['bin'].values())))
                program = [report['tools']['node']['path'], str(package_json.parent / binary)] + program[1:]
            required = ['python'] if Path(program[0]).name.lower().startswith('python') else []
            if any(report['tools'][k]['status'] != 'available' for k in required):
                raise RuntimeError('所选Python不兼容；先检查环境。')
            return subprocess.call(program, env=runtime_environment(report))
        result = manager.ensure() if args.command == 'ensure' else manager.smoke() if args.command == 'smoke' else manager.check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('ready', result.get('passed', False)) else 1
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'failed', 'error': str(error), 'message_zh': '未启用失败的环境；原环境和用户项目保留。'}, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
