"""Quiet-gap proposals and inward frame quantization; no speech classification claims."""
import math
from fractions import Fraction


def plan_pauses(silences, words, duration, *, minimum_internal=.30):
    """Ledger every measured quiet interval, including retained/conflicting ones.

    Targets describe the *total* remaining gap. Words are contradictory evidence,
    not expendable merely because a detector called their range quiet.
    """
    rows = []
    for index, item in enumerate(silences, 1):
        start, end = max(0., float(item['start'])), min(duration, float(item['end']))
        if end <= start:
            continue
        previous = [w for w in words if float(w['end']) <= start + .001]
        following = [w for w in words if float(w['start']) >= end - .001]
        conflicts = [i for i,w in enumerate(words)
                     if min(end,float(w['end']))-max(start,float(w['start'])) > .015]
        punctuation = str(previous[-1].get('word','')).rstrip() if previous else ''
        if start <= .02:
            kind, target = 'leading', .10
        elif end >= duration-.02:
            kind, target = 'trailing', .20
        elif punctuation.endswith(('。','！','？','.','!','?')):
            kind, target = 'sentence', .24
        elif punctuation.endswith(('；',';')):
            kind, target = 'paragraph', .34
        else:
            kind, target = 'within_sentence', .14
        gap = end-start
        row = dict(id=f'S{index:03d}', silence_start=f'{start:.6f}', silence_end=f'{end:.6f}',
                   silence_duration=f'{gap:.6f}', pause_kind=kind,
                   target_pause_seconds=target, retained_seconds=gap,
                   context_before=''.join(str(w.get('word','')) for w in previous[-12:]),
                   context_after=''.join(str(w.get('word','')) for w in following[:12]),
                   decision='retain_short_pause', proposed_delete_start='', proposed_delete_end='',
                   word_conflicts=conflicts, review_required=False,
                   reason='already short enough; no padding or deletion proposed')
        if conflicts:
            row.update(decision='review_word_silence_conflict', review_required=True,
                       reason='quiet measurement overlaps ASR words; resolve local timing/acoustic evidence before cutting')
        elif gap > target+.04 and (kind in ('leading','trailing') or gap >= minimum_internal):
            if kind == 'leading':
                a,b = start,end-target
            elif kind == 'trailing':
                a,b = start+target,end
            else:
                a,b = start+target/2,end-target/2
            row.update(decision='proposed_shorten_pending_review', review_required=True,
                       proposed_delete_start=f'{a:.6f}', proposed_delete_end=f'{b:.6f}',
                       retained_seconds=target,
                       reason='natural-tight quiet-gap proposal; contextual pacing requires AI assessment')
        rows.append(row)
    return rows


def quantize_deletions(deletes, fps, duration):
    """Keep executed removal inside the authorized interval on both sides."""
    rate = Fraction(str(fps))
    if rate <= 0:
        raise ValueError('fps must be positive')
    actual, audit = [], []
    for start,end,reason in deletes:
        if not 0 <= start < end <= duration:
            raise ValueError('invalid authorized deletion bounds')
        a = float(Fraction(math.ceil(Fraction(str(start))*rate))/rate)
        b = float(Fraction(math.floor(Fraction(str(end))*rate))/rate)
        if b <= a:
            raise ValueError('deletion contains no complete video frame; retain it or review a new range')
        actual.append((a,b,reason))
        audit.append(dict(requested_start=start, requested_end=end, actual_start=a, actual_end=b,
                          start_adjustment=a-start, end_adjustment=b-end, reason=reason))
    return actual,audit
