"""Version-bound full-auto authorization; no helper grants consent itself.

The host must supply an actual user message/evidence, never an invented approval.
Legacy reports use semi_auto. Frozen snapshots are offline validation only.
"""
import copy
import hashlib
import json
from pathlib import Path

REQUIRED_CHOICES = ('retake_policy', 'font_name', 'mask_shape', 'background',
                    'background_motion', 'delivery')
AUDIO_METHODS = {'agent_audio_listening': 'audio_listening',
                 'agent_av_review': 'audio_video_review'}
STATIC_METHODS = {'static_inspection', 'combined_evidence_review', 'structural_review', 'machine_evidence_review'}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('JSON must be an object')
    return value


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _path(value, base):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (Path(base) / path).resolve()


def settings_digest(settings):
    """Bind all effective settings, including confirmed choices, except workflow state."""
    if not isinstance(settings, dict):
        raise ValueError('settings must be an object')
    return _digest({key: value for key, value in settings.items() if key != 'workflow'})


def validate_choices(choices):
    errors = []
    if not isinstance(choices, dict):
        return ['initial choices must be an object']
    for key in REQUIRED_CHOICES:
        value = choices.get(key)
        if not (_text(value) or isinstance(value, dict) and bool(value)):
            errors.append(f'initial choice missing: {key}')
    if choices.get('retake_policy') not in ('none', 'last_complete'):
        errors.append('invalid retake_policy choice')
    if choices.get('mask_shape') not in ('circle', 'rounded-square', 'rounded_square'):
        errors.append('invalid mask_shape choice')
    motion = choices.get('background_motion')
    if isinstance(motion, dict):
        direction = motion.get('direction', motion.get('mode', motion.get('motion')))
        speed = motion.get('speed', motion.get('speed_px_per_second', motion.get('speed_px_s')))
        if direction not in ('static', 'right', 'left'):
            errors.append('background motion needs an explicit supported direction')
        if direction != 'static' and (type(speed) not in (int, float) or not 0 < speed < float('inf')):
            errors.append('moving background needs a finite positive speed')
    elif motion != 'static':
        errors.append('moving background must include direction and speed')
    return errors


def create_authorization(settings, sources, choices, evidence_file, *, message,
                         recorded_at, settings_path=None):
    """Build a record from supplied real consent; caller writes an immutable JSON file."""
    errors = validate_choices(choices)
    workflow = settings.get('workflow', {}) if isinstance(settings, dict) else {}
    if workflow.get('mode') != 'full_auto' or not _text(workflow.get('run_id')):
        errors.append('authorization requires full_auto mode and run_id')
    if type(workflow.get('revision', 0)) is not int or workflow.get('revision', 0) < 0:
        errors.append('workflow revision must be a nonnegative integer')
    confirmed = settings.get('confirmed_choices', {})
    if not isinstance(confirmed, dict) or any(confirmed.get(key) != value for key, value in choices.items()):
        errors.append('choices must match settings.confirmed_choices')
    if not _text(message) or not _text(recorded_at):
        errors.append('real user authorization message and recorded_at are required')
    evidence_path = Path(evidence_file).resolve()
    if not evidence_path.is_file() or not evidence_path.read_text(encoding='utf-8-sig').strip():
        errors.append('real UTF-8 user authorization evidence is required')
    source_refs = []
    if not isinstance(sources, (list, tuple)) or not sources:
        errors.append('authorization needs original source references')
    else:
        for source in sources:
            reference = source if isinstance(source, dict) else {'path': str(source)}
            path = Path(reference.get('path', '')).resolve()
            if not path.is_file():
                errors.append('original source file missing')
                continue
            digest = file_hash(path)
            if reference.get('sha256') is not None and reference['sha256'] != digest:
                errors.append('original source hash changed')
            source_refs.append({'path': str(path), 'sha256': digest})
    for key in ('background', 'font_asset'):
        asset = choices.get(key)
        if isinstance(asset, dict) and 'path' in asset:
            _check_ref(asset, Path(settings_path).parent if settings_path else Path.cwd(), f'authorized {key}', errors)
    if errors:
        raise ValueError('; '.join(errors))
    result = {'schema_version': 1, 'kind': 'xx3zdjj_full_auto_authorization',
              'mode': 'full_auto', 'run_id': workflow['run_id'],
              'revision': workflow.get('revision', 0),
              'settings_digest': settings_digest(settings),
              'choices': copy.deepcopy(choices), 'choices_digest': _digest(choices),
              'sources': source_refs,
              'user_authorization': {'kind': 'user', 'method': 'explicit_user_authorization',
                                     'message': message, 'recorded_at': recorded_at,
                                     'evidence': {'path': str(evidence_path), 'sha256': file_hash(evidence_path)}}}
    if settings_path is not None:
        result['settings_path'] = str(Path(settings_path).resolve())
    return result


def _check_ref(reference, base, label, errors):
    if not isinstance(reference, dict) or not _text(reference.get('path')) or not _sha(reference.get('sha256')):
        errors.append(f'{label} needs path and SHA256')
        return None
    path = _path(reference['path'], base)
    if not path.is_file():
        errors.append(f'{label} file missing')
        return None
    if file_hash(path) != reference['sha256']:
        errors.append(f'{label} hash changed')
        return None
    return path


def resolve_workflow(workflow_record, report_base, project_config=None, *, live_config_required=True):
    """Return mode/context plus errors. Explicit project settings take precedence.

    Offline validation requires an explicitly marked frozen snapshot. It verifies
    copied settings/auth/evidence bytes but cannot attest current original media.
    """
    errors = []
    result = {'mode': 'semi_auto', 'settings': None, 'authorization': None, 'errors': errors}
    try:
        record = workflow_record if isinstance(workflow_record, dict) else {}
        if workflow_record is not None and not isinstance(workflow_record, dict):
            errors.append('workflow report must be an object')
        frozen = record.get('frozen_snapshot') is True
        if frozen and live_config_required:
            errors.append('frozen workflow cannot authorize live execution')
        if not live_config_required and not frozen:
            errors.append('offline workflow validation requires frozen_snapshot')
        settings_ref = record.get('settings', {})
        settings_path = Path(project_config).resolve() if project_config is not None else None
        if settings_path is None and isinstance(settings_ref, dict) and _text(settings_ref.get('path')):
            settings_path = _path(settings_ref['path'], report_base)
        if settings_path is None:
            if record:
                errors.append('workflow requires actual project settings')
            return result
        if not settings_path.is_file():
            errors.append('workflow project settings missing')
            return result
        settings = _read(settings_path)
        result['settings'] = settings
        result['settings_path'] = str(settings_path)
        workflow = settings.get('workflow')
        if workflow is None:
            workflow = {'mode': 'semi_auto', 'state': 'active'}
        if not isinstance(workflow, dict) or workflow.get('mode') not in ('semi_auto', 'full_auto'):
            errors.append('workflow mode is not selected')
            return result
        mode = workflow['mode']
        result['mode'] = mode
        if record and record.get('mode') != mode:
            errors.append('report workflow mode differs from actual project configuration')
        if workflow.get('state') != 'active':
            errors.append('workflow is pending or paused')
        if mode == 'semi_auto':
            return result
        if not record or record.get('mode') != 'full_auto':
            errors.append('full_auto needs a version-bound workflow report')
        if project_config is not None and isinstance(settings_ref, dict) and _text(settings_ref.get('path')):
            if _path(settings_ref['path'], report_base) != settings_path:
                errors.append('workflow settings reference differs from supplied project configuration')
        if frozen:
            _check_ref(settings_ref, report_base, 'frozen settings', errors)
        auth_ref = record.get('authorization')
        auth_path = _check_ref(auth_ref, report_base, 'workflow authorization', errors)
        selected_ref = workflow.get('authorization')
        if not frozen:
            if not isinstance(selected_ref, dict) or not isinstance(auth_ref, dict) or selected_ref.get('sha256') != auth_ref.get('sha256'):
                errors.append('report authorization is not the current project authorization')
            elif _text(selected_ref.get('path')) and auth_path is not None and _path(selected_ref['path'], settings_path.parent) != auth_path:
                errors.append('authorization path is not the current project authorization')
        if auth_path is None:
            return result
        auth = _read(auth_path)
        result['authorization'] = auth
        if not frozen:
            original_settings_path = auth.get('settings_path')
            if _text(original_settings_path):
                if _path(original_settings_path, auth_path.parent) != settings_path:
                    errors.append('workflow settings path differs from the authorized live project configuration')
            elif project_config is None:
                errors.append('inferred full_auto settings require an authorization-bound settings_path')
        if auth.get('schema_version') != 1 or auth.get('kind') != 'xx3zdjj_full_auto_authorization' or auth.get('mode') != 'full_auto':
            errors.append('invalid full_auto authorization schema')
        if not _text(workflow.get('run_id')) or auth.get('run_id') != workflow.get('run_id') or auth.get('revision') != workflow.get('revision', 0):
            errors.append('authorization belongs to a different run or revision')
        if auth.get('settings_digest') != settings_digest(settings):
            errors.append('effective settings changed since authorization')
        choices = auth.get('choices')
        errors.extend(validate_choices(choices))
        confirmed = settings.get('confirmed_choices', {})
        if not isinstance(confirmed, dict) or not isinstance(choices, dict) or any(confirmed.get(key) != value for key, value in choices.items()) or auth.get('choices_digest') != _digest(choices):
            errors.append('authorized initial choices changed or are inconsistent')
        if not frozen and isinstance(choices, dict):
            for key in ('background', 'font_asset'):
                asset = choices.get(key)
                if isinstance(asset, dict) and 'path' in asset:
                    _check_ref(asset, settings_path.parent, f'authorized {key}', errors)
        consent = auth.get('user_authorization', {})
        if not isinstance(consent, dict) or consent.get('kind') != 'user' or consent.get('method') != 'explicit_user_authorization' or not all(_text(consent.get(key)) for key in ('message', 'recorded_at')):
            errors.append('authorization must record actual explicit user consent')
            consent = {}
        evidence_ref = record.get('user_evidence') if frozen else consent.get('evidence')
        evidence_path = _check_ref(evidence_ref, report_base, 'user authorization evidence', errors)
        if frozen and (not isinstance(consent.get('evidence'), dict) or not isinstance(evidence_ref, dict) or evidence_ref.get('sha256') != consent['evidence'].get('sha256')):
            errors.append('frozen user evidence does not match original authorization')
        if evidence_path is not None and not evidence_path.read_text(encoding='utf-8-sig').strip():
            errors.append('user authorization evidence is empty')
        sources = auth.get('sources')
        if not isinstance(sources, list) or not sources:
            errors.append('authorization has no original source references')
        else:
            for source in sources:
                if not isinstance(source, dict) or not _text(source.get('path')) or not _sha(source.get('sha256')):
                    errors.append('authorization has invalid original source reference')
                elif not frozen:
                    _check_ref(source, auth_path.parent, 'authorized original source', errors)
        return result
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        errors.append(f'invalid workflow authorization: {error}')
        return result


def validate_workflow(workflow_record, report_base, project_config=None, *, live_config_required=True):
    return resolve_workflow(workflow_record, report_base, project_config,
                            live_config_required=live_config_required)['errors']


def validate_ai_review(report, inputs, covered_checks, base, *, require_audio=False):
    """Validate recorded AI evidence, not manufacture checks or claim human listening."""
    errors = []
    review = report.get('ai_review', {}) if isinstance(report, dict) else {}
    if not isinstance(review, dict):
        return ['AI review must be an object']
    if review.get('status') != 'passed' or not _text(review.get('reviewer_id')):
        errors.append('AI review needs passed status and an actual reviewer_id')
    method = review.get('method')
    if not isinstance(method, str):
        method = None
    if require_audio:
        if method not in AUDIO_METHODS or review.get('capability') != AUDIO_METHODS.get(method):
            errors.append('AI review requires actual audio-listening capability; ASR alone is insufficient')
    elif method not in set(AUDIO_METHODS) | STATIC_METHODS:
        errors.append('AI review method is missing or unsupported')
    if method in AUDIO_METHODS and review.get('capability') != AUDIO_METHODS[method]:
        errors.append('AI listening claim requires matching actual capability')
    evidence = review.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        errors.append('AI review needs hashed evidence')
    else:
        for item in evidence:
            _check_ref(item, base, 'AI review evidence', errors)
    evidence_kinds = {item.get('kind') for item in evidence if isinstance(item, dict) and isinstance(item.get('kind'), str)} if isinstance(evidence, list) else set()
    if method in AUDIO_METHODS and 'listening_confirmation' not in evidence_kinds:
        errors.append('AI listening claim requires hashed listening_confirmation evidence')
    if method == 'machine_evidence_review' and 'machine_verification' not in evidence_kinds:
        errors.append('AI machine review requires hashed machine_verification evidence')
    if method in STATIC_METHODS:
        from review_state import listening_claim_errors
        errors.extend(listening_claim_errors(review))
        errors.extend(listening_claim_errors(report))
        if 'listening_confirmation' in evidence_kinds:
            errors.append('machine/static AI review cannot label evidence as listening_confirmation')
    covered = review.get('covered_checks')
    if not isinstance(covered, list) or not all(key in covered for key in covered_checks):
        errors.append('AI review does not cover every required check')
    artifacts = review.get('artifacts')
    if not isinstance(artifacts, dict):
        errors.append('AI review needs version-bound artifact hashes')
        artifacts = {}
    for key, path in inputs.items():
        reference = artifacts.get(key, {})
        if not Path(path).is_file() or not isinstance(reference, dict) or reference.get('sha256') != file_hash(path):
            errors.append(f'AI review artifact changed or unrecorded: {key}')
    return errors
