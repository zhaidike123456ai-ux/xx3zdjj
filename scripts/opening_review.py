"""Plan overlapping opening reviews from real audio activity, never auto-delete.

PCM16 mono 16 kHz is the input contract. Energy activity is not a speech
classifier: breaths/noise and weak consonants remain explicit uncertainty.
An ASR callback performs actual recognition; this module never loads a model.
"""
from __future__ import annotations

import array
import copy
import hashlib
import math
import sys
import wave
from pathlib import Path


def _finite(value):
    return math.isfinite(float(value))


def _db(value):
    return 20 * math.log10(max(float(value), 1e-9))


def _quantile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, int((len(ordered)-1)*fraction))] if ordered else -180.0


def acoustic_activity(samples, sample_rate=16000, *, frame_seconds=.01,
                      threshold_dbfs=None, min_burst_seconds=.025,
                      smooth_gap_seconds=.02):
    """Pure PCM16 sample -> frame activity evidence. No speech/cut assertion."""
    if sample_rate != 16000 or not _finite(frame_seconds) or frame_seconds <= 0:
        raise ValueError('expected 16 kHz PCM and a positive frame duration')
    if min_burst_seconds < 0 or smooth_gap_seconds < 0:
        raise ValueError('activity durations must be nonnegative')
    size = max(1, round(sample_rate*frame_seconds))
    frames = []
    for index in range(0, len(samples), size):
        chunk = samples[index:index+size]
        if not chunk: continue
        rms = math.sqrt(sum(float(x)*x for x in chunk)/len(chunk))/32768
        peak = max(abs(x) for x in chunk)/32768
        differences = [chunk[i]-chunk[i-1] for i in range(1, len(chunk))]
        highpass = math.sqrt(sum(float(x)*x for x in differences)/max(1,len(differences)))/32768
        zcr = sum((chunk[i]>=0)!=(chunk[i-1]>=0) for i in range(1,len(chunk)))/max(1,len(chunk)-1)
        frames.append({'start':index/sample_rate,'end':(index+len(chunk))/sample_rate,
                       'rms_dbfs':_db(rms),'peak_dbfs':_db(peak),
                       'first_difference_dbfs':_db(highpass),'zero_crossing_rate':zcr})
    noise = _quantile([x['rms_dbfs'] for x in frames], .10)
    threshold = min(-28.0, max(-52.0, noise+10.0)) if threshold_dbfs is None else float(threshold_dbfs)
    if not _finite(threshold): raise ValueError('threshold must be finite')
    runs = []
    for frame in frames:
        if frame['rms_dbfs'] < threshold: continue
        if runs and frame['start']-runs[-1]['end'] <= smooth_gap_seconds+1e-8:
            runs[-1]['end']=frame['end']; runs[-1]['peak_rms_dbfs']=max(runs[-1]['peak_rms_dbfs'],frame['rms_dbfs'])
        else:
            runs.append({'start':frame['start'],'end':frame['end'],'peak_rms_dbfs':frame['rms_dbfs']})
    intervals = [dict(x, duration=x['end']-x['start']) for x in runs if x['end']-x['start'] >= min_burst_seconds-1e-8]
    duration = len(samples)/sample_rate
    quiet=[]; cursor=0.0
    for interval in intervals:
        if interval['start']>cursor: quiet.append({'start':cursor,'end':interval['start'],'duration':interval['start']-cursor})
        cursor=interval['end']
    if cursor<duration: quiet.append({'start':cursor,'end':duration,'duration':duration-cursor})
    return {'duration':duration,'sample_rate':sample_rate,'frame_seconds':size/sample_rate,
            'noise_floor_dbfs':noise,'activity_threshold_dbfs':threshold,
            'activity_intervals':intervals,'below_threshold_intervals':quiet,
            'frames':frames,'speech_verified':False,
            'uncertainty':'Energy activity may include breaths/noise; weak phonemes may fall below threshold. Never use as a deletion boundary.'}


def _words(words):
    if isinstance(words, dict):
        words = [w for s in words.get('segments',[]) for w in s.get('words',[])]
    return sorted([dict(w,start=float(w['start']),end=float(w['end'])) for w in (words or []) if w.get('start') is not None and w.get('end') is not None
                   and _finite(w['start']) and _finite(w['end']) and 0<=float(w['start'])<float(w['end'])],key=lambda w:float(w['start']))


def _union(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if end<=start: continue
        if merged and start<=merged[-1][1]+1e-8: merged[-1][1]=max(end,merged[-1][1])
        else: merged.append([start,end])
    return merged


def coverage(target, windows):
    """Pure union coverage of requested source-time interval."""
    start,end=target
    length=max(0,end-start)
    covered=_union([(max(start,float(w['start'])),min(end,float(w['end']))) for w in windows])
    seconds=sum(b-a for a,b in covered)
    gaps=[]; cursor=start
    for a,b in covered:
        if a>cursor+1e-8: gaps.append([cursor,a])
        cursor=max(cursor,b)
    if cursor<end-1e-8: gaps.append([cursor,end])
    return {'target':[start,end],'covered_seconds':seconds,'required_seconds':length,
            'fraction':seconds/length if length else 0.0,'uncovered':gaps,'complete':bool(length) and not gaps}


def plan_opening_windows(duration, activity_intervals, words=None, *, window_seconds=2.5,
                         hop_seconds=1.0, opening_span=6.0, cluster_gap_seconds=1.0,
                         context_seconds=.25, max_windows=10):
    """Pure planning anchored to acoustic activity near the first ASR words.

    All earlier bursts in the connected first-word cluster are included, even
    when ASR merged them into one token. At least two differently positioned
    windows cover a short opening when the recording permits this.
    """
    values=(duration,window_seconds,hop_seconds,opening_span,cluster_gap_seconds,context_seconds)
    if not isinstance(max_windows,int) or max_windows<4: raise ValueError('max_windows must be at least four')
    if not all(_finite(x) for x in values) or duration<=0 or window_seconds<=0 or not 0<hop_seconds<window_seconds or opening_span<=0 or cluster_gap_seconds<0 or context_seconds<0:
        raise ValueError('invalid duration/window settings; hop must be smaller than window')
    activities=sorted([dict(x) for x in activity_intervals if _finite(x['start']) and _finite(x['end']) and 0<=float(x['start'])<float(x['end'])<=duration+.001],key=lambda x:float(x['start']))
    valid_words=_words(words)
    if not activities:
        return {'status':'skipped','reason':'no sustained acoustic activity; no opening recognition claimed',
                'effective_start':None,'media_duration':duration,'windows':[],'coverage':coverage((0,0),[]),
                'speech_verified':False,'asr_word_support':False}
    clusters=[]
    for interval in activities:
        a,b=float(interval['start']),float(interval['end'])
        if clusters and a-clusters[-1]['end']<=cluster_gap_seconds+1e-8:
            clusters[-1]['end']=b;clusters[-1]['intervals'].append(interval)
        else: clusters.append({'start':a,'end':b,'intervals':[interval]})
    support=False; reason='first sustained acoustic cluster; no ASR word support'
    selected=clusters[0]
    if valid_words:
        first=valid_words[0]; a,b=float(first['start']),float(first['end'])
        nearby=[x for x in clusters if x['start']<=b+context_seconds and x['end']>=a-cluster_gap_seconds]
        if nearby:
            if b-a>=.9:
                # A stretched ASR token may span a leading quiet region plus
                # several attempts. Prefer sustained overlapping activity,
                # rather than a stray earlier click closest to timestamp zero.
                selected=max(nearby,key=lambda x:(max(0,min(x['end'],b)-max(x['start'],a)),x['end']))
            else:
                selected=min(nearby,key=lambda x:abs(max(x['start'],a)-min(x['end'],b)))
            support=True; reason='activity cluster connected to first ASR word; earlier short restarts included'
        else:
            reason='ASR first word has no nearby activity; using first activity cluster with unresolved speech identity'
    effective=selected['start']
    # Acoustic threshold onset may trail a quiet consonant. An earlier ASR
    # anchor is included in context, never used as a guaranteed speech onset.
    nearby_asr_anchor=support and float(valid_words[0]['start'])>=effective-cluster_gap_seconds
    review_start=min(effective,float(valid_words[0]['start'])) if nearby_asr_anchor else effective
    start=max(0,review_start-context_seconds)
    end=min(duration,effective+opening_span)
    specials=[]
    opening=selected['intervals']
    if len(opening)>=2 and float(opening[0]['end'])-float(opening[0]['start'])<=.7:
        first,second=opening[:2]
        # Do not infer the split inside one ASR token. These source-time windows
        # are based only on actual acoustic activity gaps, never deletion cuts.
        isolated_start=max(0,float(first['start'])-.08)
        isolated_end=min(duration,float(first['end'])+.08,float(second['start'])-.01)
        if isolated_end>isolated_start:
            specials.append({'start':isolated_start,'end':isolated_end,'kind':'isolated_first_activity',
                             'reason':'isolate the first short activity before the next measured activity; speech identity unresolved'})
        second_start=max(float(first['end'])+.01,float(second['start'])-.20)
        second_end=min(duration,float(second['end'])+.5,second_start+window_seconds)
        if second_end>second_start:
            specials.append({'start':second_start,'end':second_end,'kind':'second_activity_context',
                             'reason':'context around the later activity, excluding the isolated first activity'})
        combined_start=max(0,float(first['start'])-.15)
        combined_end=min(duration,float(second['end'])+.25,combined_start+4.0)
        specials.append({'start':combined_start,'end':combined_end,'kind':'two_activity_context',
                         'reason':'joint context for the two early activities; four-second maximum, no inferred phoneme cut'})
    context=[]; cursor=start
    while cursor<end-1e-8:
        finish=min(duration,cursor+window_seconds)
        context.append({'start':cursor,'end':finish,'kind':'overlapping_context',
                        'reason':'overlapping independent opening decode'})
        if finish>=end:break
        cursor+=hop_seconds
    if len(context)==1 and end-start>hop_seconds and start+hop_seconds<duration:
        context.append({'start':start+hop_seconds,'end':min(duration,start+hop_seconds+window_seconds),
                        'kind':'shifted_context','reason':'second shifted opening decode'})
    available=max_windows-len(specials)
    if len(context)>available:
        # Bound decoding cost. Report any resulting gaps rather than claiming
        # complete review of an unusually long explicitly requested horizon.
        indices=sorted(set(round(i*(len(context)-1)/max(1,available-1)) for i in range(available)))
        context=[context[i] for i in indices]
    windows=[]
    for item in specials+context:
        if any(abs(item['start']-x['start'])<1e-8 and abs(item['end']-x['end'])<1e-8 for x in windows):continue
        windows.append(dict(item,id=f'opening_{len(windows):03d}',coordinate_system='source_seconds'))
    gaps=[{'before_end':a['end'],'after_start':b['start'],'gap_seconds':float(b['start'])-float(a['end'])}
          for a,b in zip(selected['intervals'],selected['intervals'][1:])]
    return {'status':'planned','reason':reason,'effective_start':effective,'review_start':review_start,
            'media_duration':duration,'windows':windows,
            'coverage':coverage((review_start,end),windows),'asr_word_support':support,
            'earlier_asr_anchor_used':bool(nearby_asr_anchor and review_start<effective),
            'first_asr_word':valid_words[0] if valid_words else None,'max_windows':max_windows,
            'multiscale_review':bool(specials),
            'opening_activity':selected['intervals'],'activity_gaps':gaps,
            'speech_verified':False,'deletion_authorized':False,
            'uncertainty':'Acoustic onset is an activity candidate, not proof of a particular word or a safe cut.'}


def analyze_opening(wav_path, words=None, *, media_duration=None, **options):
    path=Path(wav_path)
    with wave.open(str(path),'rb') as handle:
        if (handle.getnchannels(),handle.getframerate(),handle.getsampwidth(),handle.getcomptype())!=(1,16000,2,'NONE'):
            raise ValueError('opening review requires mono 16 kHz PCM16 WAV')
        pcm=handle.readframes(handle.getnframes())
    samples=array.array('h');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    acoustic=acoustic_activity(samples)
    duration=acoustic['duration']
    activities=acoustic['activity_intervals']
    if media_duration is not None:
        if not _finite(media_duration) or float(media_duration)<=0:raise ValueError('invalid media duration')
        duration=min(duration,float(media_duration))
        activities=[dict(x,end=min(x['end'],duration),duration=min(x['end'],duration)-x['start'])
                    for x in activities if x['start']<duration]
    plan=plan_opening_windows(duration,activities,words,**options)
    # Full frame evidence stays available from the pure analyzer; compact report
    # records opening-related frames and summaries rather than the whole file.
    onset=plan['effective_start']
    acoustic['frames']=[x for x in acoustic['frames'] if onset is not None and onset-.3<=x['start']<=onset+2]
    return dict(plan,wav_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),acoustic_evidence=acoustic)


def source_relative_word_evidence(local_words, window_start, *, window_end=None, window_id=None):
    """Keep all ASR evidence without inventing timestamps for malformed words.

    Only ``words`` have usable positive-length measured coordinates. Raw output
    and ``timing_unverified`` are evidence for review, never cut/subtitle input.
    A bad word makes this window incomplete, even when the other words survive.
    """
    if not _finite(window_start) or float(window_start)<0:
        raise ValueError('invalid window start')
    start=float(window_start)
    if window_end is not None and (not _finite(window_end) or float(window_end)<=start):
        raise ValueError('invalid window end')
    if not isinstance(local_words,list):
        raise ValueError('local words must be a list')
    raw=copy.deepcopy(local_words)
    valid=[];invalid=[]
    for index,word in enumerate(local_words):
        entry=word if isinstance(word,dict) else {}
        a,b=entry.get('start'),entry.get('end')
        reason=None
        try:
            finite=a is not None and b is not None and _finite(a) and _finite(b)
        except (TypeError,ValueError,OverflowError):
            finite=False
        if not isinstance(word,dict):reason='word record is not an object'
        elif entry.get('timing_status')=='timing_unverified':reason='word was explicitly marked timing_unverified'
        elif not finite:reason='word timestamps are missing, nonnumeric, or nonfinite'
        elif float(a)<0:reason='word starts before the decoded window'
        elif float(b)==float(a):reason='zero-duration word'
        elif float(b)<float(a):reason='word end precedes its start'
        elif window_end is not None and start+float(b)>float(window_end)+1e-8:
            reason='word extends beyond the decoded window'
        if reason:
            invalid.append({'index':index,'window_id':window_id,'word':entry.get('word'),
                'local_start':a,'local_end':b,
                'source_start':start+float(a) if finite else None,
                'source_end':start+float(b) if finite else None,
                'raw_word':copy.deepcopy(word),'timing_status':'timing_unverified',
                'reason':reason,'usable_for_cut':False,'usable_for_subtitle_timing':False})
            continue
        adjusted=copy.deepcopy(word)
        adjusted.update(local_start=float(a),local_end=float(b),start=start+float(a),end=start+float(b),
                        source_word_index=index)
        valid.append(adjusted)
    return {'words':valid,'raw_words':raw,'timing_unverified':invalid,
            'status':'unavailable' if invalid else 'executed',
            'quality_status':'review_required' if invalid else 'unverified'}


def source_relative_words(local_words, window_start):
    """Strict legacy API; use source_relative_word_evidence to retain partial data."""
    evidence=source_relative_word_evidence(local_words,window_start)
    if evidence['timing_unverified']:
        first=evidence['timing_unverified'][0]
        raise ValueError(f"invalid local word timestamps at index {first['index']} "
                         f"({first['word']!r}): {first['reason']}; "
                         f"start={first['local_start']!r}, end={first['local_end']!r}")
    return evidence['words']


def _decode_opening_window(window, asr_callback):
    """Retain decoder return before validation, including on parsing failure."""
    decoded=None
    try:
        decoded=asr_callback(dict(window))
        if isinstance(decoded,dict):
            if not isinstance(decoded.get('segments'),list):
                raise ValueError('callback transcript must contain a segments list')
            local=[];indices=[]
            for segment_index,segment in enumerate(decoded['segments']):
                if not isinstance(segment,dict) or not isinstance(segment.get('words',[]),list):
                    raise ValueError(f'invalid words collection in segment {segment_index}')
                for word_index,word in enumerate(segment.get('words',[])):
                    indices.append((segment_index,word_index));local.append(word)
        else:
            local=decoded;indices=[]
        evidence=source_relative_word_evidence(local,float(window['start']),
                    window_end=float(window['end']),window_id=window.get('id'))
        for issue in evidence['timing_unverified']:
            if indices:
                issue['segment_index'],issue['segment_word_index']=indices[issue['index']]
        reasons=[f"word {issue['index']} ({issue['word']!r}): {issue['reason']}"
                 for issue in evidence['timing_unverified']]
        return dict(window,**evidence,raw_output=copy.deepcopy(decoded),
            reason='; '.join(reasons) if reasons else 'actual callback completed; words are review evidence only')
    except Exception as error:
        return dict(window,status='unavailable',words=[],raw_words=[],timing_unverified=[],
                    raw_output=copy.deepcopy(decoded),quality_status='review_required',
                    error_type=type(error).__name__,reason=f'{type(error).__name__}: {error}')


def _retry_window(window, duration):
    # One expanded decode uses a new source interval/cache key. Expansion is
    # bounded and never changes the original failure record or marks it fixed.
    a,b=float(window['start']),float(window['end'])
    start=max(0,a-.15);end=min(duration,b+.20)
    if start==a and end==b:return None
    return dict(window,id=str(window.get('id','opening'))+'_retry_1',
        start=start,end=end,kind='retry_expanded_context',retry_of=window.get('id'),
        attempt=1,cache_window=[start,end],
        reason='one bounded expansion after incomplete decode; original evidence still requires review')


def execute_opening_review(plan, asr_callback=None, *, max_retries=0):
    """Decode planned windows, retain partial evidence, never imply audio passed.

    ``max_retries`` is a total review budget of zero or one additional decode.
    Retries are supplemental evidence in ``retry_windows``; original scheduled,
    completed and failed counts are never rewritten by a successful retry.
    ``temporal_coverage_complete`` concerns the time union of fully decoded
    original windows; ``multiscale_complete`` requires every original window.
    Neither status verifies speech quality or authorizes a cut.
    """
    if type(max_retries) is not int or max_retries not in (0,1):
        raise ValueError('max_retries must be zero or one total additional decode')
    windows=plan.get('windows',[]);target=plan.get('coverage',{}).get('target',[0,0])
    reports=[];completed=[];retries=[]
    if asr_callback is not None:
        for window in windows:
            report=_decode_opening_window(window,asr_callback)
            reports.append(report)
            if report['status']=='executed':completed.append(window)
            elif len(retries)<max_retries:
                duration=float(plan.get('media_duration',plan.get('acoustic_evidence',{}).get('duration',
                    max(float(w['end']) for w in windows))))
                retry=_retry_window(window,duration)
                if retry is not None:retries.append(_decode_opening_window(retry,asr_callback))
    else:
        reports=[dict(window,status='unavailable',words=[],raw_words=[],timing_unverified=[],
            raw_output=None,quality_status='review_required',
            reason='no local ASR callback; acoustic planning only') for window in windows]
    covered=coverage(target,completed)
    failed=len(windows)-len(completed)
    multiscale_complete=bool(windows) and failed==0
    all_completed=multiscale_complete and covered['complete']
    status='executed' if all_completed else ('unavailable' if windows else 'skipped')
    if not windows:reason=plan.get('reason','no planned windows')
    elif asr_callback is None:reason='no local ASR callback; acoustic planning only'
    elif all_completed:reason='independent overlapping local decodes completed; listening still required'
    else:reason='one or more scheduled windows or opening regions lack complete local decoding; retained evidence requires review'
    return {'status':status,'reason':reason,'windows':reports,'coverage':covered,
            'planned_coverage':plan.get('coverage',coverage(target,windows)),
            'scheduled_windows':len(windows),'completed_windows':len(completed),'failed_windows':failed,
            'temporal_coverage_complete':covered['complete'],'multiscale_complete':multiscale_complete,
            'quality_status':'review_required' if failed else 'unverified',
            'retry_limit':max_retries,'retry_windows':retries,'retried_windows':len(retries),
            'successful_retries':sum(x['status']=='executed' for x in retries),
            'retry_resolution':'supplemental evidence only; original failures remain unresolved',
            'human_listening':'not performed','speech_completeness':'not verified','deletion_authorized':False}
