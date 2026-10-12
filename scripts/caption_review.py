"""Bounded subtitle timing diagnostics and conservative Chinese layout rules.

Thresholds create review candidates, never shorter words or audio edits. Local
machine review files can retain a real prolonged syllable or replace measured
word bounds. Their source, original record and file digest must match. These
records document machine evidence; they never claim human listening.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path


DEFAULT_THRESHOLDS = {
    'short_word_characters': 2,
    'short_word_seconds': 0.9,
    'long_word_seconds': 1.5,
    'seconds_per_character': 0.65,
    'silence_overlap_seconds': 0.2,
    'silence_overlap_fraction': 0.25,
    'onset_disagreement_seconds': 0.1,
}
_PUNCTUATION = re.compile(r'[\s，。！？、,.!?；;：:\"\x27“”‘’（）()]+')
_WEAK_BREAKS = (
    ('不是先堆', '一大串复杂词'),
    ('真正要先想明白', '的是四件事'),
    ('再替换成', '自己的画面主题'),
)


def _text(value):
    return _PUNCTUATION.sub('', str(value))


def _number(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and not isinstance(value, bool) else None


def _range(record, duration):
    if not isinstance(record, dict):
        return None
    start, end = _number(record.get('start')), _number(record.get('end'))
    if start is None or end is None or not 0 <= start < end <= duration:
        return None
    return start, end


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(data)
    return digest.hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{64}', value) is not None


def _flag(source_hash, index, word, code, detail):
    identity = [source_hash, index, word, code, detail]
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'id': 'caption-' + digest[:24], 'code': code, 'word_index': index,
            'original_word': copy.deepcopy(word), 'detail': detail,
            'status': 'review_required', 'automatic_correction': False}


def _merged_silences(silences, duration):
    intervals = []
    for index, row in enumerate(silences):
        bounds = _range(row, duration)
        if bounds is None:
            raise ValueError(f'invalid silence measurement {index}')
        intervals.append(bounds)
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def _detect(words, duration, source_hash, silences, onsets, policy):
    flags = []
    previous = None
    for index, word in enumerate(words):
        bounds = _range(word, duration)
        if bounds is None:
            flags.append(_flag(source_hash, index, word, 'invalid_word_timing',
                               {'reason': 'finite positive media-bounded interval required'}))
            continue
        start, end = bounds
        if previous is not None and start < previous[1] - 1e-8:
            flags.append(_flag(source_hash, index, word, 'word_overlap',
                               {'previous_word_index': previous[0], 'previous_end': previous[1]}))
        previous = index, end
        characters = len(_text(word.get('word', '')))
        if not characters:
            continue
        limit = (policy['short_word_seconds'] if characters <= policy['short_word_characters']
                 else max(policy['long_word_seconds'], characters * policy['seconds_per_character']))
        if end - start > limit + 1e-8:
            flags.append(_flag(source_hash, index, word, 'unusually_long_word',
                               {'duration': end-start, 'threshold_seconds': limit,
                                'reason': 'possible timing error or intentional prolonged speech; neither is assumed'}))
        intersections = [[max(start, a), min(end, b)] for a, b in silences
                         if min(end, b) > max(start, a)]
        overlap = sum(b-a for a, b in intersections)
        if (overlap + 1e-8 >= policy['silence_overlap_seconds']
                and overlap / (end-start) + 1e-8 >= policy['silence_overlap_fraction']):
            flags.append(_flag(source_hash, index, word, 'word_silence_conflict',
                               {'silence_intersections': intersections, 'overlap_seconds': overlap,
                                'overlap_fraction': overlap / (end-start),
                                'reason': 'energy-based silence is a conflicting measurement, not proof of a missing word'}))
        for evidence in onsets.get(index, []):
            delta = start-evidence['onset']
            if abs(delta) > policy['onset_disagreement_seconds'] + 1e-8:
                flags.append(_flag(source_hash, index, word, 'onset_disagreement',
                                   {'asr_start': start, 'measured_onset': evidence['onset'],
                                    'asr_minus_measured_seconds': delta,
                                    'measurement': evidence,
                                    'reason': 'independent machine onset evidence disagrees with the ASR timestamp'}))
    return flags


def _read_local_review(reference, base):
    if not isinstance(reference, dict) or not reference.get('path') or not _sha(reference.get('sha256')):
        raise ValueError('local review requires a path and SHA-256')
    path = Path(reference['path']).expanduser()
    if not path.is_absolute():
        path = base / path
    if _hash(path).lower() != reference['sha256'].lower():
        raise ValueError('local review file hash changed')
    result = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('local review must be a JSON object')
    return result


def review_caption_timing(words, *, duration, source_sha256, silences=None,
                          onset_evidence=(), local_reviews=(), base_dir=None,
                          thresholds=None):
    """Review immutable ASR records; return only evidence-backed timing changes.

    ``onset_evidence`` rows require ``source_sha256``, ``word_index``, ``onset``
    and a nonempty machine ``method``. The caller supplies actual measurements,
    not an assumed onset; energy activity alone does not identify a phoneme.

    ``local_reviews`` is a list of {path, sha256} refs to UTF-8 JSON objects:
      kind: caption_local_machine_review; source_sha256; word_index;
      original_word: the COMPLETE original word object; window: {start, end};
      method; reviewer; recorded_at; assessment; verification: 'confirmed'; flag_ids: [reported IDs];
      resolution: retain | replace_timing; measured_word: {word, start, end}.
    The file must record the actual local measurement and assessment. A retain
    review may confirm a real drawn-out syllable. Replacement never interpolates
    time from text length, and cannot create an overlap or resolve a new flag.

    ``machine_checked`` means the declared machine scope has no unresolved
    diagnostics. It does not certify perceptual or phonetic accuracy.
    """
    duration = _number(duration)
    if duration is None or duration <= 0 or not _sha(source_sha256):
        raise ValueError('positive duration and source SHA-256 required')
    if not isinstance(words, list):
        raise ValueError('words must be a list')
    original = copy.deepcopy(words)
    policy = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        if set(thresholds)-set(policy):
            raise ValueError('unknown caption timing threshold')
        policy.update(thresholds)
    if any(_number(value) is None or float(value) <= 0 for value in policy.values()):
        raise ValueError('caption timing thresholds must be finite and positive')
    policy = {key: float(value) for key, value in policy.items()}
    if policy['silence_overlap_fraction'] > 1:
        raise ValueError('silence overlap fraction must not exceed 1')
    intervals = _merged_silences(silences or (), duration)
    onsets = {}
    for index, row in enumerate(onset_evidence):
        onset = _number(row.get('onset')) if isinstance(row, dict) else None
        wi = row.get('word_index') if isinstance(row, dict) else None
        if (not isinstance(wi, int) or isinstance(wi, bool) or not 0 <= wi < len(words)
                or row.get('source_sha256') != source_sha256 or onset is None
                or not 0 <= onset <= duration or not str(row.get('method', '')).strip()):
            raise ValueError(f'invalid or wrong-source onset evidence {index}')
        onsets.setdefault(wi, []).append(copy.deepcopy(row))
    flags = _detect(original, duration, source_sha256, intervals, onsets, policy)
    by_id = {row['id']: row for row in flags}
    updated = copy.deepcopy(original)
    accepted, rejected, resolved, touched = [], [], set(), set()
    base = Path(base_dir or '.').resolve()
    for position, reference in enumerate(local_reviews):
        try:
            review = _read_local_review(reference, base)
            wi = review.get('word_index')
            if (review.get('kind') != 'caption_local_machine_review'
                    or review.get('source_sha256') != source_sha256
                    or not isinstance(wi, int) or isinstance(wi, bool)
                    or not 0 <= wi < len(original)):
                raise ValueError('local review source, kind or word index mismatch')
            if review.get('original_word') != original[wi]:
                raise ValueError('local review does not bind the complete original word record')
            if review.get('verification') != 'confirmed':
                raise ValueError('local timing verification is inconclusive or failed; retaining is not clearance')
            if wi in touched:
                raise ValueError('multiple local reviews for the same word are ambiguous')
            for key in ('method', 'reviewer', 'recorded_at', 'assessment'):
                if not isinstance(review.get(key), str) or not review[key].strip():
                    raise ValueError(f'local review requires {key}')
            if any(term in review['method'].lower() for term in ('listening', 'human', 'interpolat')):
                raise ValueError('local review method must describe machine measurements, not listening or interpolation')
            ids = review.get('flag_ids')
            if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                    or any(key not in by_id or by_id[key]['word_index'] != wi for key in ids)):
                raise ValueError('local review must cover exact existing flags for this word')
            measured = review.get('measured_word')
            bounds, window = _range(measured, duration), _range(review.get('window'), duration)
            old_bounds = _range(original[wi], duration)
            if (bounds is None or window is None or old_bounds is None
                    or measured.get('word') != original[wi].get('word')
                    or not window[0] <= min(bounds[0], old_bounds[0])
                    or not max(bounds[1], old_bounds[1]) <= window[1]):
                raise ValueError('local measurement must preserve text and cover original and measured media bounds')
            resolution = review.get('resolution')
            if resolution == 'retain':
                if bounds != old_bounds:
                    raise ValueError('retain cannot change timing')
            elif resolution == 'replace_timing':
                if bounds == old_bounds:
                    raise ValueError('replacement must contain a measured change')
                updated[wi].update(start=bounds[0], end=bounds[1])
                updated[wi]['caption_timing_review'] = copy.deepcopy(reference)
            else:
                raise ValueError('unknown local review resolution')
            touched.add(wi)
            resolved.update(ids)
            accepted.append({'reference': copy.deepcopy(reference), 'word_index': wi,
                             'flag_ids': ids, 'resolution': resolution,
                             'measurement': copy.deepcopy(measured), 'assessment': review['assessment']})
        except (ValueError, TypeError, KeyError, OSError) as error:
            rejected.append({'review_index': position, 'reference': copy.deepcopy(reference), 'reason': str(error)})
    # Redetect changed bounds. A previous exception for a long syllable cannot
    # bless a newly introduced overlap, silence conflict or early start.
    final_flags = _detect(updated, duration, source_sha256, intervals, onsets, policy)
    for flag in flags:
        if flag['id'] in resolved:
            flag['status'] = 'resolved_by_local_machine_review'
    additional = [flag for flag in final_flags if flag['id'] not in by_id]
    all_flags = flags + additional
    unresolved = [flag for flag in all_flags if flag['status'] == 'review_required']
    # A correction resolves only explicitly reviewed old flags; any new conflict
    # remains visible. Review IDs deliberately change when measured inputs change.
    quality = 'review_required' if unresolved or rejected or not words else 'machine_checked'
    return {'schema_version': 1, 'source_sha256': source_sha256,
            'duration_seconds': duration, 'words': updated, 'flags': all_flags,
            'unresolved_flags': unresolved, 'accepted_reviews': accepted,
            'rejected_reviews': rejected, 'thresholds': policy, 'quality_status': quality,
            'scope': {'word_range_sanity': True, 'duration_diagnostics': True,
                      'silence_detection_status': 'not_supplied' if silences is None else 'executed',
                      'silence_measurements_supplied': len(intervals),
                      'onset_measurements_supplied': sum(map(len, onsets.values())),
                      'onset_review_scope': 'measured_words_only' if onsets else 'not_supplied',
                      'phonetic_accuracy_certified': False, 'listening_required': False},
            'empty_word_evidence': not bool(words)}


def _weak_break(left, right):
    left, right = _text(left), _text(right)
    return (any(left.endswith(a) and right.startswith(b) for a, b in _WEAK_BREAKS)
            or right.startswith(('的是', '的就是'))
            or left.endswith(('替换成', '变成', '改成', '写成', '分为', '包括', '不是先堆')))


def _two_line_event(text, max_chars, allowed_boundaries):
    """Visual line break within ONE event; no new timings or split ASR token."""
    if '\n' in text or len(_text(text)) <= max_chars:
        return text
    choices=[]
    for i in range(1,len(text)):
        a,b=text[:i],text[i:]
        if allowed_boundaries is None or len(_text(a)) not in allowed_boundaries:
            continue
        if max(len(_text(a)),len(_text(b))) > max_chars:
            continue
        if _weak_break(a,b):
            continue
        penalty=abs(len(_text(a))-len(_text(b)))
        if a.endswith(('的是','就是')):
            penalty-=10
        if _weak_break(a,b) or b.startswith(('的','是','了','着','过')):
            penalty+=20
        if a.endswith(('不','没','无','别','把','从','在')):
            penalty+=20
        choices.append((penalty,i,a+'\n'+b))
    return min(choices)[2] if choices else text


def _word_boundaries(words, full_text):
    if words is None:
        return None
    values = [_text(row.get('word', '')) for row in words]
    if ''.join(values) != _text(full_text):
        return set()
    result, count = {0}, 0
    for text in values:
        count += len(text)
        result.add(count)
    return result


def plan_caption_layout(chunks, *, words=None, max_chars=11, trusted_layout=None):
    """Merge three known dangling phrases; expose safe layout proposals.

    No word timestamps are generated or divided. ``trusted_layout`` is an
    explicit list of reviewed strings; it must preserve visible text and split
    only between whole measured ASR words when ``words`` is provided. This API
    does not authenticate user approval; the caller retains its stage gate.
    Width/font checks remain in the existing ASS/SRT exporter.
    """
    if not isinstance(chunks, list) or not chunks or any(not isinstance(x, str) or not x.strip() for x in chunks):
        raise ValueError('caption chunks must be nonempty strings')
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        raise ValueError('max_chars must be a positive integer')
    original = list(chunks)
    selected, suggestions, issues = [], [], []
    for chunk in original:
        if selected and _weak_break(selected[-1], chunk):
            old = [selected[-1], chunk]
            selected[-1] += chunk
            suggestions.append({'kind': 'merged_weak_boundary', 'before': old, 'after': [selected[-1]]})
        else:
            selected.append(chunk)
    explicit = trusted_layout is not None
    if explicit:
        if (not isinstance(trusted_layout, list) or not trusted_layout
                or any(not isinstance(x, str) or not x.strip() for x in trusted_layout)
                or ''.join(trusted_layout).replace('\n','') != ''.join(original).replace('\n','')):
            return {'chunks': original, 'suggestions': suggestions,
                    'issues': [{'code': 'layout_text_changed'}], 'status': 'review_required',
                    'text_preserved': False, 'explicit_layout_used': False}
        selected = list(trusted_layout)
    boundaries = _word_boundaries(words, ''.join(original))
    if boundaries == set():
        issues.append({'code': 'layout_word_text_mismatch'})
    # A long semantic unit may remain one synchronized event over two lines.
    # The visual break does not create a new timestamp or subdivide a token.
    if not explicit:
        reflowed = []
        offset=0
        for chunk in selected:
            allowed={b-offset for b in boundaries} if boundaries is not None else None
            proposal=_two_line_event(chunk,max_chars,allowed)
            if proposal != chunk:
                suggestions.append({'kind':'two_line_same_event','before':[chunk],'after':[proposal],
                                    'timing_changed':False})
            reflowed.append(proposal)
            offset+=len(_text(chunk))
        selected = reflowed
    offset = 0
    for index, chunk in enumerate(selected):
        if any(len(_text(line)) > max_chars for line in chunk.splitlines()):
            issues.append({'code': 'line_too_long', 'line_index': index, 'text': chunk,
                           'reason': 'provide an explicit semantic layout using whole word boundaries; no hard character split'})
        offset += len(_text(chunk))
        if index < len(selected)-1:
            if boundaries is not None and offset not in boundaries:
                issues.append({'code': 'boundary_inside_asr_word', 'line_index': index})
            if _weak_break(chunk, selected[index+1]):
                issues.append({'code': 'weak_semantic_boundary', 'line_index': index})
    return {'chunks': selected, 'suggestions': suggestions, 'issues': issues,
            'status': 'review_required' if issues else 'ready',
            'text_preserved': ''.join(selected).replace('\n','') == ''.join(original).replace('\n',''),
            'explicit_layout_used': explicit, 'timing_changed': False,
            'scope': 'finite phrase rules and complete-token boundaries; not general semantic understanding'}
