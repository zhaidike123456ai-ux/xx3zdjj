"""Text-based retake candidates, never semantic acceptance or executable cuts.

The source ASR text can be wrong, and a supplied script is a reference rather
than ground truth. Every row needs AI assessment and source-bound acoustic
boundaries before execution. Range proposals never bridge intervening speech.
"""
import math
import re
import unicodedata
from difflib import SequenceMatcher

MAX_ATTEMPT_SEGMENTS = 3
MAX_INTRA_ATTEMPT_GAP = .8
MAX_LONG_RETAKE_GAP = 20.
MAX_SHORT_RETAKE_GAP = 2.
PROTECTED_TERMS = ('不', '没', '无', '未', '非', '别', '如果', '除非', '否则', '只有', '只要', '才')
DANGLING_ENDS = ('就能', '如果', '只要', '但是', '因为', '除非', '否则')


def clean_token(text):
    return re.sub(r'[\s，。！？、,.!?；;：:\"\'“”‘’（）()]+', '',
                  unicodedata.normalize('NFKC', str(text))).lower()


def _segments(segments):
    result = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or not isinstance(segment.get('text'), str):
            raise ValueError('retake segments need text and verified numeric source ranges')
        start, end = segment.get('start'), segment.get('end')
        if type(start) not in (int, float) or type(end) not in (int, float) or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end:
            raise ValueError('invalid retake segment source range')
        result.append(dict(start=float(start), end=float(end), text=segment['text'],
                           normalized_text=clean_token(segment['text']), original_index=index))
    return sorted(result, key=lambda x: (x['start'], x['end'], x['original_index']))


def _blocks(segments):
    blocks = []
    for start in range(len(segments)):
        for size in range(1, min(MAX_ATTEMPT_SEGMENTS, len(segments)-start)+1):
            members = segments[start:start+size]
            if any(members[i]['start']-members[i-1]['end'] > MAX_INTRA_ATTEMPT_GAP for i in range(1,size)):
                break
            if size > 1 and any(_match(old['normalized_text'], members[-1]['normalized_text'])[0]
                                for old in members[:-1] if old['normalized_text']):
                # ABA/BAB windows can straddle retakes when the speaker restarts
                # rapidly. Do not turn that rolling window into a wider attempt.
                break
            text = ''.join(x['text'] for x in members).strip()
            norm = clean_token(text)
            if norm:
                blocks.append(dict(start=members[0]['start'], end=max(x['end'] for x in members),
                    text=text, normalized_text=norm,
                    segment_indices=[x['original_index'] for x in members]))
    return blocks


def _match(a, b):
    if a == b:
        return 'exact', 1.
    if a.startswith(b) or b.startswith(a):
        return 'prefix', SequenceMatcher(None, a, b, autojunk=False).ratio()
    ratio = SequenceMatcher(None, a, b, autojunk=False).ratio()
    # Similar short snippets are too ambiguous; only exact/prefix short restarts.
    if min(len(a),len(b)) >= 5 and ratio >= .78:
        return 'similar', ratio
    return None, ratio


def _overlap(a, b):
    return a['start'] < b['end']-1e-9 and b['start'] < a['end']-1e-9


def _candidate_groups(blocks):
    """Build whole chronological groups, deduplicating overlapping ASR block views."""
    groups = {}
    for seed in blocks:
        compatible = []
        for block in blocks:
            kind, ratio = _match(seed['normalized_text'], block['normalized_text'])
            if kind is not None:
                compatible.append((kind, ratio, block))
        # A phrase AB must win over an overlapping AB+unique-sentence view.
        # Source-overlapping views cannot count as independent takes.
        compatible.sort(key=lambda x: (x[0] != 'exact', -x[1],
                                       -len(x[2]['normalized_text']), x[2]['start'], x[2]['end']))
        attempts = []
        for _, _, block in compatible:
            if not any(_overlap(block, old) for old in attempts):
                attempts.append(block)
        attempts.sort(key=lambda x: (x['start'],x['end']))
        runs = []
        for attempt in attempts:
            if not runs:
                runs.append([attempt]); continue
            prior = runs[-1][-1]
            short = min(len(prior['normalized_text']),len(attempt['normalized_text'])) < 8
            maximum = MAX_SHORT_RETAKE_GAP if short else MAX_LONG_RETAKE_GAP
            gap = attempt['start']-prior['end']
            if -1e-9 <= gap <= maximum:
                runs[-1].append(attempt)
            else:
                runs.append([attempt])
        for run in runs:
            if len(run) < 2:
                continue
            # A transitive family may contain A and C with only an ambiguous B
            # connecting them. Preserve that fact, never claim an exact group.
            pairs = [_match(a['normalized_text'], b['normalized_text'])
                     for i,a in enumerate(run) for b in run[i+1:]]
            identity = tuple(tuple(x['segment_indices']) for x in run)
            exact = len({x['normalized_text'] for x in run}) == 1
            entry = dict(attempts=run, exact=exact, min_similarity=min(x[1] for x in pairs),
                         textual_width=min(len(x['normalized_text']) for x in run))
            groups.setdefault(identity, entry)
    # Favor wider coherent attempt views before their matching subfragments;
    # at equal coverage favor genuinely identical text over a view with extras.
    # Suppress component fragments only after all three (or more) takes are known.
    ordered = sorted(groups.values(), key=lambda x: (-x['textual_width'], not x['exact'],
                          -len(x['attempts']), -x['min_similarity'], x['attempts'][0]['start']))
    chosen = []
    for group in ordered:
        if any(_overlap(a,b) for old in chosen for a in group['attempts'] for b in old['attempts']):
            continue
        chosen.append(group)
    return sorted(chosen, key=lambda x: x['attempts'][0]['start'])


def _text_changes(attempts):
    warnings = []
    for prior, later in zip(attempts, attempts[1:]):
        a, b = prior['normalized_text'], later['normalized_text']
        if a == b:
            continue
        warnings.append('wording_changed_between_attempts')
        if a.startswith(b):
            warnings.append('later_attempt_missing_textual_tail')
        elif b.startswith(a):
            warnings.append('earlier_attempt_is_textual_prefix_restart')
        if any(a.count(term) != b.count(term) for term in PROTECTED_TERMS):
            warnings.append('negation_or_condition_changed')
        if re.findall(r'\d+(?:\.\d+)?', a) != re.findall(r'\d+(?:\.\d+)?', b):
            warnings.append('number_changed')
    if any(x['normalized_text'].endswith(DANGLING_ENDS) for x in attempts):
        warnings.append('possible_incomplete_textual_ending')
    return sorted(set(warnings))


def _suggest_selection(attempts, reference):
    support = [bool(reference and x['normalized_text'] in reference) for x in attempts]
    if reference and any(support):
        maximum = max(len(x['normalized_text']) for x,supported in zip(attempts,support) if supported)
        eligible = [x for x,supported in zip(attempts,support) if supported and len(x['normalized_text']) == maximum]
        preferred = eligible[-1]
        basis = 'latest_maximum_text_coverage_supported_by_reference_substring'
    else:
        maximum = max(len(x['normalized_text']) for x in attempts)
        preferred = [x for x in attempts if len(x['normalized_text']) == maximum][-1]
        basis = 'latest_maximum_text_coverage_candidate; correctness_and_completeness_unverified'
    if len({x['normalized_text'] for x in attempts}) == 1:
        basis = 'last_chronological_text_identical_attempt; semantics_unverified'
    return preferred, basis, support


def detect_retake_groups(segments, policy, script_text=None):
    """Return old row keys plus per-attempt, semantic and bounded-range evidence.

    ``last_attempt_*`` is always the chronological last attempt (alert coverage),
    not a statement that it is correct. Use ``selection`` for the provisional
    keep suggestion. Expand ``proposed_delete_ranges`` individually; legacy
    ``proposed_delete_*`` describes only the first proposed range. ``none``
    detects the same issues but never proposes a deletion.
    """
    if policy not in ('none','last_complete'):
        raise ValueError('retake policy must be none or last_complete')
    if script_text is not None and not isinstance(script_text,str):
        raise ValueError('script reference must be text')
    source_segments = _segments(segments)
    groups = _candidate_groups(_blocks(source_segments))
    reference = clean_token(script_text) if script_text else ''
    # Lexical/emphasis reduplication remains a low-confidence review item, never
    # an inferred intra-token cut. Long normal sentences are not flagged solely
    # because they contain 慢慢/斜斜/etc.
    for segment in source_segments:
        if len(segment['normalized_text']) <= 4 and re.search(r'([\u4e00-\u9fff])\1',segment['normalized_text']):
            if not any(_overlap(segment,a) for g in groups for a in g['attempts']):
                groups.append(dict(attempts=[dict(segment,segment_indices=[segment['original_index']])],
                                   exact=True,min_similarity=1.,textual_width=len(segment['normalized_text']),
                                   lexical=True))
    groups.sort(key=lambda x:x['attempts'][0]['start'])
    rows = []
    for index, group in enumerate(groups,1):
        gid = f'RT{index:03d}'
        attempts = [dict(x,id=f'{gid}_A{i:02d}') for i,x in enumerate(group['attempts'],1)]
        selected, basis, support = _suggest_selection(attempts,reference)
        first, latest = attempts[0],attempts[-1]
        changes = _text_changes(attempts)
        if reference and not any(support):
            changes.append('no_attempt_exactly_supported_by_reference_substring')
        if group.get('lexical') or group['textual_width'] < 5:
            changes.append('lexical_or_emphasis_repetition_possible')
        intervening = [dict(start=x['start'],end=x['end'],text=x['text'],segment_index=x['original_index'])
                       for x in source_segments if first['start'] <= x['start'] < latest['end']
                       and all(x['original_index'] not in a['segment_indices'] for a in attempts)]
        if intervening:
            changes.append('intervening_speech_must_be_preserved')
        # This is a text-equivalence proposal, not semantic high confidence.
        # Differences, small snippets, script disagreements or dangling endings
        # need assessment before a deletion range can be proposed.
        eligible = (policy == 'last_complete' and len(attempts)>1 and group['exact']
                    and group['textual_width'] >= 12
                    and 'possible_incomplete_textual_ending' not in changes
                    and (not reference or all(support)))
        ranges = [dict(attempt_id=a['id'],start=a['start'],end=a['end'],
                       boundary_status='asr_only',requires_acoustic_evidence=True)
                  for a in attempts if eligible and a['id'] != selected['id']]
        if any(_overlap(r,x) for r in ranges for x in intervening):
            changes.append('ASR_range_overlaps_intervening_speech; acoustic_review_required')
            ranges = []
        proposal = ranges[0] if ranges else None
        rows.append(dict(id=gid,first_attempt_start=f"{first['start']:.3f}",first_attempt_end=f"{first['end']:.3f}",
            first_attempt_text=first['text'],last_attempt_start=f"{latest['start']:.3f}",last_attempt_end=f"{latest['end']:.3f}",
            last_attempt_text=latest['text'],similarity=f"{group['min_similarity']:.3f}",
            gap_seconds=f"{latest['start']-attempts[-2]['end']:.3f}" if len(attempts)>1 else '0.000',
            policy=policy,decision='proposed_delete_first_attempt_keep_last_pending_confirmation' if proposal else 'review_range_unclear',
            proposed_delete_start=f"{proposal['start']:.3f}" if proposal else '',
            proposed_delete_end=f"{proposal['end']:.3f}" if proposal else '',
            kept_range=f"{selected['start']:.3f}-{selected['end']:.3f}",
            status='machine text candidate only; AI semantic assessment and source-bound acoustic evidence required; no deletion authorized',
            attempts=attempts,selection=dict(attempt_id=selected['id'],basis=basis,semantic_verified=False,
                reference_support='substring_text_support_only_not_ground_truth' if reference else 'not_provided'),
            needs_semantic_review=True,requires_acoustic_evidence=True,deletion_authorized=False,
            semantic_warnings=sorted(set(changes)),intervening_segments=intervening,
            proposed_delete_ranges=ranges,text_match_kind='exact' if group['exact'] else 'prefix_or_similar',
            proposal_scope='individual_attempts_only; pauses_and_intervening_speech_not_included'))
    return rows
