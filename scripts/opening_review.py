"""Plan overlapping opening reviews from real audio activity, never auto-delete.

PCM16 mono 16 kHz is the input contract. Energy activity is not a speech
classifier: breaths/noise and weak consonants remain explicit uncertainty.
An ASR callback performs actual recognition; this module never loads a model.
"""
from __future__ import annotations

import array
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
                'effective_start':None,'windows':[],'coverage':coverage((0,0),[]),
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
    return {'status':'planned','reason':reason,'effective_start':effective,'review_start':review_start,'windows':windows,
            'coverage':coverage((review_start,end),windows),'asr_word_support':support,
            'earlier_asr_anchor_used':bool(nearby_asr_anchor and review_start<effective),
            'first_asr_word':valid_words[0] if valid_words else None,'max_windows':max_windows,
            'multiscale_review':bool(specials),
            'opening_activity':selected['intervals'],'activity_gaps':gaps,
            'speech_verified':False,'deletion_authorized':False,
            'uncertainty':'Acoustic onset is an activity candidate, not proof of a particular word or a safe cut.'}


def analyze_opening(wav_path, words=None, **options):
    path=Path(wav_path)
    with wave.open(str(path),'rb') as handle:
        if (handle.getnchannels(),handle.getframerate(),handle.getsampwidth(),handle.getcomptype())!=(1,16000,2,'NONE'):
            raise ValueError('opening review requires mono 16 kHz PCM16 WAV')
        pcm=handle.readframes(handle.getnframes())
    samples=array.array('h');samples.frombytes(pcm)
    if sys.byteorder!='little':samples.byteswap()
    acoustic=acoustic_activity(samples)
    plan=plan_opening_windows(acoustic['duration'],acoustic['activity_intervals'],words,**options)
    # Full frame evidence stays available from the pure analyzer; compact report
    # records opening-related frames and summaries rather than the whole file.
    onset=plan['effective_start']
    acoustic['frames']=[x for x in acoustic['frames'] if onset is not None and onset-.3<=x['start']<=onset+2]
    return dict(plan,wav_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),acoustic_evidence=acoustic)


def source_relative_words(local_words, window_start):
    """Do not mutate local timestamps or interpolate phonemes."""
    if not _finite(window_start) or window_start<0:raise ValueError('invalid window start')
    result=[]
    for word in local_words:
        copy=dict(word)
        if not _finite(copy['start']) or not _finite(copy['end']) or not 0<=float(copy['start'])<float(copy['end']):
            raise ValueError('invalid local word timestamps')
        copy['local_start']=float(copy['start']);copy['local_end']=float(copy['end'])
        copy['start']=float(copy['start'])+window_start;copy['end']=float(copy['end'])+window_start
        result.append(copy)
    return result


def execute_opening_review(plan, asr_callback=None):
    """Call a host decoder(window_dict), returning word list or segments dict.

    The host owns media extraction/model/cache. No callback means unavailable,
    not executed. Exceptions/empty results are recorded; no candidate auto-cuts.
    """
    windows=plan.get('windows',[]);target=plan.get('coverage',{}).get('target',[0,0])
    reports=[];completed=[]
    if not windows:
        return {'status':'skipped','reason':plan.get('reason','no planned windows'),'windows':[],
                'coverage':coverage(target,[]),'human_listening':'not performed','deletion_authorized':False}
    if asr_callback is None:
        return {'status':'unavailable','reason':'no local ASR callback; acoustic planning only','windows':[],
                'coverage':coverage(target,[]),'planned_coverage':plan['coverage'],'human_listening':'not performed','deletion_authorized':False}
    for window in windows:
        try:
            decoded=asr_callback(dict(window))
            local=[w for s in decoded.get('segments',[]) for w in s.get('words',[])] if isinstance(decoded,dict) else decoded
            if not isinstance(local,list):raise ValueError('callback must return local word list or transcript segments')
            words=source_relative_words(local,float(window['start']))
            if any(w['end']>float(window['end'])+.025 for w in words):raise ValueError('local word extends beyond window')
            reports.append(dict(window,status='executed',words=words,reason='actual callback completed; words are review evidence only'))
            completed.append(window)
        except Exception as error:
            reports.append(dict(window,status='unavailable',words=[],reason=f'{type(error).__name__}: {error}'))
    covered=coverage(target,completed)
    all_completed=len(completed)==len(windows) and covered['complete']
    return {'status':'executed' if all_completed else 'unavailable',
            'reason':'independent overlapping local decodes completed' if all_completed else 'one or more scheduled windows or opening regions lack completed local decoding',
            'windows':reports,'coverage':covered,'planned_coverage':plan['coverage'],
            'human_listening':'not performed','speech_completeness':'not verified','deletion_authorized':False}
