"""Version-bound review state. A completed command is not a quality approval.

Reports/resolutions are local evidence records, not proof of actual human hearing.
Callers must record actual machine-evidence assessments, user statements, or
capable-agent listening observations without relabeling machine checks as hearing.
Synthetic fixtures never authorize real media. Evidence
cannot be replaced by an explanation or a zero count.
"""
import hashlib
import json
import math
from pathlib import Path

REQUIRED_CHECKS = ('repeated_speech', 'breath_gaps', 'word_integrity')
CHECK_STATUSES = ('executed', 'skipped', 'unavailable')
CHECK_RESULTS = ('passed', 'review_required', 'failed', 'unverified')
RETAIN_OUTCOMES = ('retain_normal_repetition', 'false_positive')
EVIDENCE_KINDS = ('local_audio', 'listening_confirmation', 'machine_verification')


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stable_alert_id(source_sha256, check_id, start, end, kind='', text=''):
    """Stable across reruns with the same source, detector and normalized bounds."""
    content = [source_sha256, check_id, round(float(start), 6), round(float(end), 6), kind, text]
    return 'alert-' + hashlib.sha256(json.dumps(content, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]


def full_coverage(duration):
    return {'scope': 'full_media', 'start': 0.0, 'end': float(duration)}


def machine_review_report(source, duration, checks, alerts):
    """Build a report without inferring quality from the command exit code."""
    source = Path(source).resolve()
    digest = file_hash(source)
    items = []
    for raw in alerts:
        item = dict(raw)
        item.setdefault('review_required', True)
        if not item.get('id'):
            item['id'] = stable_alert_id(digest, item['check_id'], item['start'], item['end'], item.get('kind', ''), item.get('text', ''))
        items.append(item)
    complete = all(
        key in checks and checks[key].get('status') == 'executed' and checks[key].get('result') == 'passed'
        and coverage_is_full(checks[key].get('coverage'), float(duration))
        for key in REQUIRED_CHECKS
    )
    return {'schema_version': 1, 'stage': 'residual-check', 'source': str(source),
            'source_sha256': digest, 'duration_seconds': float(duration),
            'command_status': 'completed',
            'quality_status': 'review_required' if any(i.get('review_required') for i in items) else 'passed' if complete else 'unverified',
            'checks': checks, 'alerts': items, 'human_listening': 'not performed by this report builder'}


# Short public factory name for the pipeline; same signature, no media processing.
make_report = machine_review_report


def load_object(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('report must be an object')
    return data


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def coverage_is_full(value, duration):
    if not isinstance(value, dict) or value.get('scope') != 'full_media':
        return False
    start, end = value.get('start'), value.get('end')
    return numeric(start) and numeric(end) and abs(start) <= 0.001 and abs(end - duration) <= 0.001


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def evidence_errors(evidence, base, require_listening=False, require_machine=False):
    errors = []
    if not isinstance(evidence, list) or not evidence:
        return ['missing hashed evidence']
    confirmation = False
    machine = False
    for item in evidence:
        if not isinstance(item, dict) or not nonempty(item.get('path')):
            errors.append('invalid evidence object/path')
            continue
        if item.get('kind') not in EVIDENCE_KINDS:
            errors.append('invalid evidence kind')
        if item.get('kind') == 'listening_confirmation':
            confirmation = True
        if item.get('kind') == 'machine_verification':
            machine = True
        path = Path(base) / item['path']
        if not path.is_file():
            errors.append('evidence file missing: ' + item['path'])
        elif item.get('sha256') != file_hash(path):
            errors.append('evidence changed or hash missing: ' + item['path'])
    if require_listening and not confirmation:
        errors.append('actual listening confirmation evidence required')
    if require_machine and not machine:
        errors.append('hashed machine_verification evidence required')
    if require_machine and confirmation:
        errors.append('machine review cannot label evidence as listening_confirmation')
    return errors


def listening_claim_errors(record):
    """Check explicit structured claims; this is not authentication of free-form prose."""
    errors = []
    for key in ('human_listening_performed', 'audio_listening_performed', 'listening_performed'):
        if record.get(key) is True:
            errors.append('machine review cannot claim performed listening')
    value = record.get('human_listening')
    if value is True or isinstance(value, str) and value.strip().lower().startswith(('performed', 'completed', 'verified', 'passed', '已听', '已完成听')):
        errors.append('machine review cannot claim performed human listening')
    return errors


def human_resolution_errors(item, base):
    """Legacy public name: accepts honest machine review or evidenced listening."""
    errors = []
    if not nonempty(item.get('assessment')):
        errors.append('missing structured assessment')
    reviewer = item.get('reviewer', {})
    machine = isinstance(reviewer, dict) and reviewer.get('kind') == 'agent' and reviewer.get('method') == 'machine_evidence_review'
    if not isinstance(reviewer, dict) or reviewer.get('kind') not in ('user', 'agent'):
        errors.append('resolution needs an identified user or agent reviewer')
    elif not all(nonempty(reviewer.get(k)) for k in ('recorded_at', 'quote')):
        errors.append('resolution needs recorded reviewer time and statement')
    elif reviewer['kind'] == 'user' and reviewer.get('method') != 'user_listening':
        errors.append('user resolution needs explicit user_listening method')
    elif reviewer['kind'] == 'agent' and not machine:
        capabilities = {'agent_audio_listening': 'audio_listening', 'agent_av_review': 'audio_video_review'}
        if reviewer.get('method') not in capabilities or reviewer.get('capability') != capabilities.get(reviewer.get('method')):
            errors.append('unsupported agent review method; listening claims need actual matching capability, ASR alone is not listening')
    if machine:
        errors.extend(listening_claim_errors(item))
        errors.extend(listening_claim_errors(reviewer))
    errors.extend(evidence_errors(item.get('evidence'), base, require_listening=not machine, require_machine=machine))
    return errors


def lineage_errors(report, source_digest, base):
    """An output-local ASR pass cannot erase its original source warnings."""
    lineage = report.get('source_review_lineage')
    if not isinstance(lineage, dict) or lineage.get('status') != 'executed':
        return ['source review lineage unavailable; reanalyze and render a version-bound rough cut']
    errors = []
    objects = {}
    for key in ('edit_map', 'report'):
        reference = lineage.get(key)
        if not isinstance(reference, dict) or not nonempty(reference.get('path')):
            errors.append('lineage missing hashed ' + key + ' reference')
            continue
        path = Path(base) / reference['path']
        if not path.is_file() or reference.get('sha256') != file_hash(path):
            errors.append('lineage ' + key + ' missing or changed')
            continue
        objects[key] = load_object(path)
    if len(objects) != 2:
        return errors
    mapping, upstream = objects['edit_map'], objects['report']
    if mapping.get('output_sha256') != source_digest:
        errors.append('lineage edit map belongs to another output media')
    if not nonempty(mapping.get('source_sha256')) or mapping.get('source_sha256') != upstream.get('source_sha256'):
        errors.append('lineage source analysis belongs to another original media')
    recorded = mapping.get('analysis_review', {})
    if not isinstance(recorded, dict) or recorded.get('sha256') != lineage['report'].get('sha256'):
        errors.append('lineage analysis report is not the one recorded during rendering')
    if upstream.get('schema_version') != 1 or upstream.get('stage') != 'analyze' or upstream.get('command_status') != 'completed':
        errors.append('legacy or incomplete source analysis cannot establish lineage')
    old_alerts = upstream.get('alerts')
    if not isinstance(old_alerts, list):
        errors.append('source analysis alert list missing; zero counts do not establish lineage')
        return errors
    current_alerts = report.get('alerts', [])
    if not isinstance(current_alerts, list):
        return errors + ['current alert list missing for lineage']
    carried = {}
    for alert in current_alerts:
        if isinstance(alert, dict) and alert.get('upstream_alert_id'):
            if alert.get('upstream_report_sha256') != lineage['report']['sha256']:
                errors.append('carried alert belongs to another source analysis report')
            carried.setdefault(alert['upstream_alert_id'], []).append(alert)
    old_ids = set()
    segments = mapping.get('kept_segments')
    if not isinstance(segments, list) or not segments:
        errors.append('lineage edit map has no kept-segment mapping')
        segments = []
    valid_segments = []
    for segment in segments:
        if not isinstance(segment, dict) or not all(numeric(segment.get(k)) for k in ('source_start', 'source_end', 'output_start', 'output_end')):
            errors.append('lineage has invalid kept-segment coordinates')
        elif segment['source_start'] >= segment['source_end'] or segment['output_start'] >= segment['output_end']:
            errors.append('lineage has empty/reversed kept segment')
        else:
            valid_segments.append(segment)
    duration = report.get('duration_seconds')
    duration = duration if numeric(duration) and duration > 0 else 0
    def covers(intervals, start, end):
        cursor = start
        for a, b in sorted(intervals):
            if b < cursor:
                continue
            if a > cursor + .001:
                return False
            cursor = max(cursor, b)
            if cursor >= end - .001:
                return True
        return False
    for old in old_alerts:
        if not isinstance(old, dict) or not nonempty(old.get('id')) or type(old.get('review_required')) is not bool:
            errors.append('source analysis alert has invalid ID/review_required')
            continue
        if old['id'] in old_ids:
            errors.append('duplicate source alert ID: ' + old['id'])
        old_ids.add(old['id'])
        if old['review_required'] is True:
            matches = carried.get(old['id'], [])
            if not matches:
                errors.append('source review_required alert was discarded: ' + old['id'])
            elif not all(a.get('review_required') is True for a in matches):
                errors.append('source alert cannot be cleared by editing alone: ' + old['id'])
            if not numeric(old.get('start')) or not numeric(old.get('end')) or old['start'] >= old['end']:
                errors.append('source alert has invalid coordinates: ' + old['id'])
                continue
            expected = []
            for segment in valid_segments:
                a = max(old['start'], segment['source_start'])
                b = min(old['end'], segment['source_end'])
                if b > a:
                    expected.append((max(0, segment['output_start'] + a - segment['source_start']),
                                     min(duration, segment['output_start'] + b - segment['source_start'])))
            if not expected:
                # Match the renderer's 300ms-before/500ms-after deletion-boundary
                # review window. An arbitrary window elsewhere cannot stand in.
                after = next((s for s in valid_segments if s['source_start'] >= old['end']), None)
                point = after['output_start'] if after else duration
                expected = [(max(0, point - .3), min(duration, point + .5))]
            intervals = [(a['start'], a['end']) for a in matches if numeric(a.get('start')) and numeric(a.get('end'))]
            for a, b in expected:
                if b <= a or not covers(intervals, a, b):
                    errors.append('source alert mapping portion or deletion boundary not fully covered: ' + old['id'])
    for aid in carried:
        if aid not in old_ids:
            errors.append('current report references unknown source alert: ' + aid)
    return errors


def validate_review(report_path, source_path, resolutions_path=None,
                    expected_report_sha256=None, expected_resolutions_sha256=None):
    """Fail closed on legacy reports, missing coverage, unresolved alerts or stale evidence.

    `fixed` cannot erase a current-media alert: repair changes the media hash and
    needs a fresh residual report. Retaining a normal repetition/false positive
    requires a version-bound machine assessment or actual listening conclusion
    and hashed evidence. Listening capability is not required for machine review.
    """
    try:
        report_path, source_path = Path(report_path).resolve(), Path(source_path).resolve()
        if not source_path.is_file():
            return ['current review media missing']
        if not report_path.is_file():
            return ['residual review report missing']
        digest = file_hash(report_path)
        source_digest = file_hash(source_path)
        report = load_object(report_path)
        errors = []
        if expected_report_sha256 is not None and digest != expected_report_sha256:
            errors.append('residual report changed or hash missing')
        if report.get('schema_version') != 1 or report.get('stage') != 'residual-check':
            errors.append('legacy or wrong residual review schema/stage')
        if report.get('source_sha256') != source_digest:
            errors.append('residual review belongs to another media version')
        if report.get('command_status') != 'completed':
            errors.append('residual command did not complete')
        errors.extend(lineage_errors(report, source_digest, report_path.parent))
        if report.get('quality_status') not in ('passed', 'review_required', 'unverified'):
            errors.append('residual quality status missing or failed')
        duration = report.get('duration_seconds')
        if not numeric(duration) or duration <= 0:
            errors.append('invalid residual review duration')
            duration = 0
        checks = report.get('checks')
        alerts = report.get('alerts')
        if not isinstance(checks, dict):
            errors.append('machine checks missing')
            checks = {}
        if not isinstance(alerts, list):
            errors.append('machine alerts missing (legacy counts do not imply no alerts)')
            alerts = []
        alert_by_id = {}
        for alert in alerts:
            if not isinstance(alert, dict) or not nonempty(alert.get('id')):
                errors.append('invalid alert or missing stable ID')
                continue
            aid = alert['id']
            if aid in alert_by_id:
                errors.append('duplicate alert ID: ' + aid)
            alert_by_id[aid] = alert
            if alert.get('check_id') not in checks:
                errors.append('alert references missing check: ' + aid)
            if type(alert.get('review_required')) is not bool:
                errors.append('alert review_required must be explicit boolean: ' + aid)
            if not numeric(alert.get('start')) or not numeric(alert.get('end')) or not 0 <= alert['start'] < alert['end'] <= duration + 0.001:
                errors.append('alert invalid source bounds: ' + aid)
            # Explicit detector diagnostics need no review; detected issues cannot
            # be hidden with review_required=false unless clearly typed informational.
            if alert.get('review_required') is False and alert.get('severity') != 'informational':
                errors.append('non-informational alert cannot bypass review: ' + aid)
        if report.get('quality_status') == 'review_required' and not any(a.get('review_required') is True for a in alert_by_id.values()) and not any(isinstance(c, dict) and c.get('result') == 'review_required' for c in checks.values()):
            errors.append('review_required status has no tracked issue; cannot treat as zero alerts')
        resolutions = {}
        resolution_base = report_path.parent
        if resolutions_path:
            resolutions_path = Path(resolutions_path).resolve()
            resolutions = load_object(resolutions_path)
            resolution_base = resolutions_path.parent
            if expected_resolutions_sha256 is not None and file_hash(resolutions_path) != expected_resolutions_sha256:
                errors.append('resolutions document changed or hash missing')
            if resolutions.get('schema_version') != 1:
                errors.append('invalid resolutions schema')
            if resolutions.get('report_sha256') != digest:
                errors.append('resolutions belong to another residual report')
            if resolutions.get('source_sha256') != source_digest:
                errors.append('resolutions belong to another media version')
        alert_resolutions = {}
        for item in resolutions.get('alerts', []):
            if not isinstance(item, dict) or not nonempty(item.get('alert_id')):
                errors.append('invalid alert resolution')
                continue
            aid = item['alert_id']
            if aid in alert_resolutions:
                errors.append('duplicate alert resolution: ' + aid)
            if aid not in alert_by_id:
                errors.append('resolution references unknown alert: ' + aid)
            alert_resolutions[aid] = item
        for aid, alert in alert_by_id.items():
            if alert.get('review_required') is not True:
                continue
            resolution = alert_resolutions.get(aid)
            if not resolution:
                errors.append('unresolved review_required alert: ' + aid)
                continue
            if resolution.get('outcome') not in RETAIN_OUTCOMES:
                errors.append('alert not validly retained; repair requires a fresh media/report: ' + aid)
            for error in human_resolution_errors(resolution, resolution_base):
                errors.append(aid + ': ' + error)
        supplements = {}
        for item in resolutions.get('check_resolutions', []):
            if not isinstance(item, dict) or item.get('check_id') not in REQUIRED_CHECKS:
                errors.append('invalid check supplement')
                continue
            key = item['check_id']
            if key in supplements:
                errors.append('duplicate check supplement: ' + key)
            supplements[key] = item
        for key in REQUIRED_CHECKS:
            check = checks.get(key, {})
            if not isinstance(check, dict):
                errors.append(key + ': malformed check')
                continue
            valid_status = check.get('status') in CHECK_STATUSES
            valid_result = check.get('result') in CHECK_RESULTS
            if not valid_status:
                errors.append(key + ': missing execution status')
            if not valid_result:
                errors.append(key + ': missing check result')
            if not nonempty(check.get('method')):
                errors.append(key + ': missing check method')
            if check.get('status') != 'executed' and not nonempty(check.get('reason')):
                errors.append(key + ': skip/unavailable reason missing')
            relevant_alerts = [a for a in alert_by_id.values() if a.get('check_id') == key and a.get('review_required')]
            adequate = (check.get('status') == 'executed' and coverage_is_full(check.get('coverage'), duration)
                        and (check.get('result') == 'passed' or (check.get('result') == 'review_required' and bool(relevant_alerts))))
            if adequate:
                continue
            supplement = supplements.get(key)
            if not supplement:
                errors.append(key + ': full-media check coverage/result unverified; needs evidenced review supplement')
                continue
            if supplement.get('outcome') != 'verified' or not coverage_is_full(supplement.get('coverage'), duration):
                errors.append(key + ': supplement lacks verified full-media coverage')
            for error in human_resolution_errors(supplement, resolution_base):
                errors.append(key + ': ' + error)
        return errors
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return ['invalid residual review state: ' + str(error)]
