#!/usr/bin/env python3
"""Reusable staged entrypoint for the talking-head cleanup skill."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path
from fractions import Fraction
from stage_gate import validate_report
from connect_captions import connect
from opening_review import analyze_opening, execute_opening_review
from review_state import make_report, full_coverage, stable_alert_id


def run(cmd: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    cmd=list(cmd)
    if cmd and cmd[0] in ("ffmpeg","ffprobe"):
        key="XX3ZDJJ_"+cmd[0].upper()
        if key in os.environ and not os.environ[key]:
            raise SystemExit(f"runtime has no verified {cmd[0]}; run dependency check/ensure first")
        cmd[0]=os.environ.get(key,cmd[0])
    return subprocess.run(
        cmd, check=True, capture_output=capture, text=True,
        encoding="utf-8", errors="replace",
    )


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path) -> dict:
    return json.loads(run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,start_time,duration,nb_frames",
        "-of", "json", str(path),
    ]).stdout)


def ascii_output(path: Path) -> Path:
    """Only newly generated names are restricted; an existing user root may be Chinese."""
    if not path.name.isascii():
        raise SystemExit("generated file/directory name must be ASCII")
    return path


def extract_audio(source: Path, target: Path) -> None:
    binding=target.with_suffix(".binding.json"); source_hash=sha256(source)
    if target.is_file() and binding.is_file():
        cached=json.loads(binding.read_text())
        if cached.get("source_sha256")==source_hash and cached.get("audio_sha256")==sha256(target): return
    run(["ffmpeg","-v","error","-y","-i",str(source),"-vn","-ar","16000","-ac","1",str(target)],capture=False)
    binding.write_text(json.dumps({"source_sha256":source_hash,"audio_sha256":sha256(target)}),encoding="utf-8")


def model_identity(model: str) -> dict:
    path = Path(model).expanduser()
    if not path.is_dir():
        return {"identifier": model, "local_files_only": True}
    return {"identifier": str(path.resolve()), "files": {
        name: sha256(path / name) for name in
        ("model.bin", "config.json", "tokenizer.json", "vocabulary.json", "vocabulary.txt")
        if (path / name).is_file()}}


def recognition_key(source: Path, args, *, vad=False, condition=False, prompt=None) -> dict:
    import importlib.metadata
    versions = {}
    for name in ("faster-whisper", "ctranslate2"):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = "not_installed"
    return {"source_sha256": sha256(source), "model": model_identity(args.model),
            "settings": {"language": "zh", "beam_size": 5, "word_timestamps": True,
                         "vad": vad, "condition": condition, "prompt": prompt,
                         "device": "cpu", "compute_type": "int8", "cpu_threads": args.cpu_threads},
            "engine_versions": versions}


def cached_recognition(source: Path, audio: Path, target: Path, args, *, vad=False,
                       condition=False, prompt=None, model=None) -> dict:
    key = recognition_key(source, args, vad=vad, condition=condition, prompt=prompt)
    if target.is_file():
        stored = json.loads(target.read_text(encoding="utf-8-sig"))
        if stored.get("cache_key") == key:
            return stored
        raise SystemExit("recognition cache source/model/settings mismatch; choose a new output directory")
    if model is None:
        from faster_whisper import WhisperModel
        model = WhisperModel(args.model, device="cpu", compute_type="int8",
                             local_files_only=True, cpu_threads=args.cpu_threads)
    result = transcribe(model, audio, vad, condition, prompt)
    result.update({"source_sha256": key["source_sha256"], "cache_key": key})
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def media_validation(media: Path, source_meta: dict, fps: str, *, dimensions=None,
                     expected_duration=None) -> dict:
    run(["ffmpeg", "-v", "error", "-i", str(media), "-f", "null", "-"], capture=False)
    result = probe(media)
    video = next((s for s in result["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in result["streams"] if s["codec_type"] == "audio"), {})
    source_video = next(s for s in source_meta["streams"] if s["codec_type"] == "video")
    size = dimensions or (source_video["width"], source_video["height"])
    checks = {"dimensions": (video.get("width"), video.get("height")) == tuple(size),
              "fps": Fraction(video.get("r_frame_rate", "0/1")) == Fraction(fps),
              "audio_present": bool(audio),
              "video_start": abs(float(video.get("start_time", 0))) <= 1 / float(Fraction(fps)),
              "audio_start": abs(float(audio.get("start_time", 0))) <= .05}
    if expected_duration is not None:
        checks["duration"] = abs(float(result["format"]["duration"]) - expected_duration) <= max(.06, 2 / float(Fraction(fps)))
        if video.get("nb_frames") not in (None,"N/A"):
            checks["frame_count"]=int(video["nb_frames"])==round(expected_duration*float(Fraction(fps)))
    return {"full_decode": "passed", "spec_checks": checks, "spec_status": "passed" if all(checks.values()) else "failed",
            "probe": result, "media_sha256": sha256(media), "human_listening": "not performed"}


def audio_packet_identity(source: Path, output: Path) -> dict:
    def packets(path):
        result=json.loads(run(["ffprobe","-v","error","-select_streams","a:0","-show_packets","-show_data_hash","sha256","-of","json",str(path)]).stdout)
        fields=("pts","dts","duration","size","data_hash")
        return [{k:x.get(k) for k in fields} for x in result.get("packets",[])]
    before=packets(source); after=packets(output)
    differences=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
    return {"status":"passed" if before and before==after else "failed",
            "source_packets":len(before),"output_packets":len(after),"different_packet_indices":differences[:20],
            "fields":["pts","dts","duration","size","data_hash"],"method":"all encoded audio packets compared, no listening claim"}


def parse_silence(stderr: str, duration: float) -> list[dict]:
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", stderr)]
    ends = [(float(a), float(b)) for a, b in re.findall(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", stderr)]
    rows=[]
    for i,start in enumerate(starts):
        if i < len(ends): end,dur=ends[i]
        else: end,dur=duration,duration-start
        rows.append({"start":start,"end":end,"duration":dur})
    return rows


def clean_token(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:\"'“”‘’（）()]+", "", text)


def flatten_words(transcript: dict) -> list[dict]:
    return [w for s in transcript["segments"] for w in s.get("words", []) if w.get("start") is not None and w.get("end") is not None]


def nearby_text(words: list[dict], t: float, *, before: bool) -> str:
    candidates = [w for w in words if (float(w["end"]) <= t if before else float(w["start"]) >= t)]
    chosen = candidates[-6:] if before else candidates[:6]
    return "".join(w["word"] for w in chosen).strip()


def repeated_phrases(words: list[dict]) -> list[dict]:
    tokens=[clean_token(w["word"]) for w in words]
    found=[]; seen=set()
    for n in range(8, 3, -1):
        index={}
        for i in range(len(tokens)-n+1):
            phrase="".join(tokens[i:i+n])
            if len(phrase) < 5 or not phrase: continue
            for j in index.get(phrase, []):
                if -0.05 <= float(words[i]["start"])-float(words[j+n-1]["end"]) <= 20:
                    key=(j,i,phrase)
                    if key not in seen:
                        found.append({
                            "phrase":phrase,
                            "first_start":words[j]["start"],"first_end":words[j+n-1]["end"],
                            "repeat_start":words[i]["start"],"repeat_end":words[i+n-1]["end"],
                            "status":"review only; do not delete without user approval",
                        }); seen.add(key)
            index.setdefault(phrase,[]).append(i)
    found.sort(key=lambda x:(x["repeat_start"],-len(x["phrase"])))
    filtered=[]
    for item in found:
        if any(item["first_start"]>=x["first_start"] and item["repeat_end"]<=x["repeat_end"] for x in filtered):
            continue
        filtered.append(item)
    return filtered


def fragment_restart_candidates(words: list[dict]) -> list[dict]:
    """Find a short abandoned phrase start that immediately restarts.

    This complements segment-level matching: a continuous half-sentence retake
    may have no silence and Whisper may either expose only a few repeated Han
    characters or swallow the restart into one abnormally long token.
    """
    tokens=[clean_token(w["word"]) for w in words]
    rows=[]
    # Explicit prefix restart, e.g. 而/是/你/的/提 + 而/是/你/的/提示词里.
    for first in range(len(tokens)):
        for size in range(5,0,-1):
            second=first+size
            if second+size>len(tokens): continue
            left="".join(tokens[first:second]); right="".join(tokens[second:second+size])
            if not left or left!=right: continue
            gap=float(words[second]["start"])-float(words[second-1]["end"])
            if gap>0.8: continue
            rows.append({
                "start":float(words[first]["start"]),"end":float(words[second]["start"]),
                "content":left,"evidence":f"short phrase start repeats after {gap:.3f}s",
                "status":"review as possible half-sentence retake; keep last complete attempt only after confirmation",
            })
            break
    # ASR can merge a hidden restart into one long Han token. Flag it so a
    # focused overlapping re-decode is required instead of silently missing it.
    for w in words:
        token=clean_token(w["word"]); duration=float(w["end"])-float(w["start"])
        if token and len(token)<=2 and duration>=0.90:
            rows.append({
                "start":float(w["start"]),"end":float(w["end"]),"content":token,
                "evidence":f"short token spans {duration:.3f}s; possible swallowed restart",
                "status":"focused overlapping ASR review required; do not auto-delete",
            })
    rows.sort(key=lambda x:(x["start"],x["end"]))
    # A single ASR token can itself contain 我我/场场. Its phoneme boundary
    # cannot be inferred from character count: require local audio review.
    for w in words:
        token=clean_token(w["word"])
        if re.search(r"([\u4e00-\u9fff])\1", token):
            rows.append({"start":float(w["start"]),"end":float(w["end"]),"content":token,
                         "evidence":"adjacent identical Han characters inside one ASR token; emphasis/lexical repeat possible",
                         "status":"local audio review required; no inferred intra-token cut"})
    rows.sort(key=lambda x:(x["start"],x["end"]))
    return rows


def frame_safe_retake_cut_start(previous_word_end: float, failed_audio_onset: float, fps: float) -> float:
    """Place a cut before the failed take's acoustic onset on a video frame.

    Callers must supply an onset measured from audio, rather than a possibly
    late ASR word timestamp. The prior word is protected; impossible overlaps
    remain a review item instead of being hidden by a fixed millisecond shift.
    """
    if fps <= 0: raise ValueError("fps must be positive")
    frame_start=int(failed_audio_onset*fps)/fps
    if frame_start <= previous_word_end:
        raise ValueError("no safe gap between previous word and failed take onset")
    return frame_start


def detect_retake_groups(segments: list[dict], policy: str) -> list[dict]:
    candidates=[]
    for size in (3,2,1):
        for i in range(len(segments)-size):
            a=segments[i:i+size]; ta=clean_token("".join(x["text"] for x in a))
            if len(ta)<12: continue
            for j in range(i+size,len(segments)-size+1):
                b=segments[j:j+size]; tb=clean_token("".join(x["text"] for x in b))
                if len(tb)<12: continue
                gap=float(b[0]["start"])-float(a[-1]["end"])
                if not 0.8<=gap<=20: continue
                ratio=SequenceMatcher(None,ta,tb).ratio()
                if ratio<0.78: continue
                candidates.append({"first_start":float(a[0]["start"]),"first_end":float(a[-1]["end"]),"first_text":"".join(x["text"] for x in a).strip(),"last_start":float(b[0]["start"]),"last_end":float(b[-1]["end"]),"last_text":"".join(x["text"] for x in b).strip(),"similarity":ratio,"gap":gap,"size":size})
    candidates.sort(key=lambda x:(-x["size"],-x["similarity"],x["first_start"]))
    selected=[]
    for x in candidates:
        if any(not (x["last_end"]<y["first_start"] or x["first_start"]>y["last_end"]) for y in selected): continue
        selected.append(x)
    rows=[]
    for i,x in enumerate(sorted(selected,key=lambda x:x["first_start"]),1):
        high=policy == "last_complete" and x["similarity"]>=0.82 and x["size"]>=2
        rows.append({"id":f"RT{i:03d}","first_attempt_start":f"{x['first_start']:.3f}","first_attempt_end":f"{x['first_end']:.3f}","first_attempt_text":x["first_text"],"last_attempt_start":f"{x['last_start']:.3f}","last_attempt_end":f"{x['last_end']:.3f}","last_attempt_text":x["last_text"],"similarity":f"{x['similarity']:.3f}","gap_seconds":f"{x['gap']:.3f}","policy":policy,"decision":"proposed_delete_first_attempt_keep_last_pending_confirmation" if high else "review_range_unclear","proposed_delete_start":f"{x['first_start']:.3f}" if high else "","proposed_delete_end":f"{max(x['first_start'],x['last_start']-0.12):.3f}" if high else "","kept_range":f"{x['last_start']:.3f}-{x['last_end']:.3f}","status":"machine candidate; last attempt completeness requires listening"})
    return rows


def detect_opening_swallowed_restarts(check_segments: list[dict] | None, silences: list[dict],
                                      fine_silences: list[dict], policy: str, fps: float) -> list[dict]:
    """Legacy anomaly detector: flag long short tokens, never infer a cut.

    Independent acoustic windows now cover short restarts this heuristic misses.
    The deletion policy must not disable detection.
    """
    if not check_segments: return []
    words=flatten_words({"segments":check_segments})
    if not words: return []
    first=float(words[0]["start"])
    rows=[]
    for w in words:
        start=float(w["start"]); end=float(w["end"]); token=clean_token(w["word"])
        if start>first+6 or not token or len(token)>2 or end-start<.90: continue
        rows.append({"id":f"OR{len(rows)+1:03d}","failed_attempt_start":f"{start:.3f}",
            "anomalous_token_end":f"{end:.3f}","anomalous_token":token,
            "last_attempt_audio_onset":"","next_reliable_word_start":"",
            "decision":"local_audio_review_required","proposed_delete_start":"","proposed_delete_end":"",
            "evidence":f"short opening token spans {end-start:.3f}s; overlapping acoustic review required",
            "status":"review_required; duration is a warning, not proof of a restart or safe cut"})
    return rows


def merge_ranges(ranges: list[tuple[float,float]]) -> list[tuple[float,float]]:
    merged=[]
    for start,end in sorted((a,b) for a,b in ranges if b>a):
        if not merged or start>merged[-1][1]: merged.append([start,end])
        else: merged[-1][1]=max(merged[-1][1],end)
    return [(a,b) for a,b in merged]


def transcribe(model, audio: Path, vad: bool, condition: bool, prompt: str | None) -> dict:
    segments, info = model.transcribe(
        str(audio), language="zh", word_timestamps=True, beam_size=5,
        vad_filter=vad, condition_on_previous_text=condition, initial_prompt=prompt,
    )
    rows=[]
    for s in segments:
        rows.append({"start":s.start,"end":s.end,"text":s.text,"words":[
            {"start":w.start,"end":w.end,"word":w.word,"probability":w.probability}
            for w in s.words or []
        ]})
    return {"language":info.language,"language_probability":info.language_probability,"segments":rows}


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fieldnames); w.writeheader(); w.writerows(rows)


class OpeningDecoder:
    """One local model/cache per stage; callback timestamps remain window-local."""
    def __init__(self, source, out, args):
        self.source, self.out, self.args = source, out, args
        self.model = None
        self.key = None
        out.mkdir(parents=True, exist_ok=True)

    def __call__(self, window):
        a, b = float(window['start']), float(window['end'])
        if self.key is None:
            self.key = recognition_key(self.source, self.args)
        key = self.key | {'window': [a, b], 'coordinate_system': 'window_local_seconds', 'schema': 2}
        name = 'window-' + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:20]
        target, audio = self.out / (name + '.json'), self.out / (name + '.wav')
        if target.exists():
            data = json.loads(target.read_text(encoding='utf-8'))
            if data.get('cache_key') != key:
                raise ValueError('window cache mismatch')
            return data
        run(['ffmpeg','-v','error','-y','-ss',str(a),'-i',str(self.source),'-t',str(b-a),
             '-vn','-ar','16000','-ac','1',str(audio)], capture=False)
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.args.model, device='cpu', compute_type='int8',
                                      local_files_only=True, cpu_threads=self.args.cpu_threads)
        data = transcribe(self.model, audio, False, False, None)
        data.update(cache_key=key, source_sha256=key['source_sha256'], coordinate_system='window_local_seconds')
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return data


def candidate_alerts(candidates, duration, origin):
    alerts = []
    for x in candidates:
        a = float(x.get('start', x.get('first_start', 0)))
        b = float(x.get('end', x.get('repeat_end', a)))
        # ASR may put a restart boundary at the first onset. Preserve its warning
        # with a review context, not a zero-width pseudo-cut.
        a = max(0, min(a, duration))
        b = min(duration, max(b, a + .08))
        if b <= a: continue
        alerts.append({'check_id':'repeated_speech', 'start':a, 'end':b,
                       'kind':origin, 'text':x.get('content', x.get('phrase','')),
                       'evidence':x, 'review_required':True})
    return alerts


def opening_audit(source, audio, out, args, words, decoder=None):
    """Mandatory detection independent of deletion policy or whole-file pass count."""
    try:
        plan = analyze_opening(audio, words)
        result = execute_opening_review(plan, decoder or OpeningDecoder(source, out/'opening-windows', args))
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        plan = {'status':'unavailable','windows':[],'reason':str(error)}
        result = {'status':'unavailable','windows':[],'coverage':{},'reason':str(error)}
    duration = float(plan.get('acoustic_evidence',{}).get('duration',0))
    alerts = []
    for window in result['windows']:
        local = window.get('words',[])
        items = fragment_restart_candidates(local) + repeated_phrases(local)
        alerts.extend(candidate_alerts(items, duration, 'opening_overlap'))
    activity = plan.get('opening_activity',[])
    # Two close acoustic bursts can hide a short attempted word even when every
    # decode returns a single word. This is uncertainty, never evidence to cut.
    if len(activity) >= 2:
        first, second = activity[:2]
        if first['end']-first['start'] <= .65 and 0 <= second['start']-first['end'] <= 1:
            alerts.append({'check_id':'repeated_speech','start':first['start'],'end':second['end'],
                'kind':'opening_short_activity','text':'', 'review_required':True,
                'evidence':{'activities':[first,second],'reason':'short initial activity before another onset; could be a syllable, breath, or attempted word; listen and compare overlapping windows; never auto-delete'}})
    result.update(plan=plan, alerts=alerts)
    (out/'opening-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def review_checks(duration, alerts, opening, full=True):
    coverage = full_coverage(duration) if full else {'scope':'local_windows','start':0,'end':duration}
    return {
        'repeated_speech':{'status':'executed' if opening.get('status')=='executed' else 'unavailable',
            'result':'review_required' if any(x['check_id']=='repeated_speech' for x in alerts) else 'unverified',
            'coverage':coverage,'method':'text restart detectors plus independent acoustic opening windows',
            'reason':'ASR cannot prove absence of repetition; opening: '+opening.get('reason',''),
            'opening_status':opening.get('status','unavailable'), 'opening_coverage':opening.get('coverage',{})},
        'breath_gaps':{'status':'executed','result':'review_required' if any(x['check_id']=='breath_gaps' for x in alerts) else 'unverified',
            'coverage':coverage,'method':'silencedetect; silence is not breath classification',
            'reason':'audio listening still required for breathing and intended pacing'},
        'word_integrity':{'status':'unavailable','result':'unverified','coverage':coverage,
            'method':'actual listening required; not inferred from ASR agreement or successful decoding',
            'reason':'this script cannot verify complete phonemes or intended semantic repetition by listening'}
    }


def unique_alerts(source, alerts):
    digest = sha256(source)
    unique = {}
    for x in alerts:
        x = dict(x)
        x.setdefault('id', stable_alert_id(digest,x['check_id'],x['start'],x['end'],x.get('kind',''),x.get('text','')))
        if x['id'] in unique and unique[x['id']] != x:
            raise ValueError('conflicting records share an alert ID; cannot silently discard a warning')
        unique[x['id']] = x
    return list(unique.values())


def propagate_analysis_alerts(source, duration):
    """Carry source warnings through the edit map, including removed-cut audits."""
    path = source.parent/'edit-map.json'
    if not path.is_file(): return [], {'status':'unavailable','reason':'no adjacent edit map; source warning lineage not available'}
    mapping = json.loads(path.read_text(encoding='utf-8'))
    if mapping.get('output_sha256') != sha256(source):
        raise SystemExit('edit map belongs to another output media version')
    ref = mapping.get('analysis_review')
    if not ref: return [], {'status':'unavailable','reason':'legacy edit map has no source review reference'}
    report_path = Path(ref['path'])
    if not report_path.is_file() or sha256(report_path) != ref['sha256']:
        raise SystemExit('source analysis review missing or changed; cannot discard unresolved alerts')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report.get('source_sha256') != mapping.get('source_sha256'):
        raise SystemExit('source analysis review hash mismatch')
    alerts=[]
    for old in report.get('alerts',[]):
        if not old.get('review_required'): continue
        portions=[]
        for segment in mapping['kept_segments']:
            a=max(old['start'],segment['source_start']); b=min(old['end'],segment['source_end'])
            if b>a:
                portions.append((segment['output_start']+a-segment['source_start'],segment['output_start']+b-segment['source_start']))
        if not portions:
            after=next((s for s in mapping['kept_segments'] if s['source_start']>=old['end']),None)
            point=after['output_start'] if after else duration
            portions=[(max(0,point-.3),min(duration,point+.5))]
        for portion_index,(a,b) in enumerate(portions):
            if b<=a: continue
            alerts.append({'check_id':old['check_id'],'start':max(0,a),'end':min(duration,b),
                'kind':'upstream_review','text':old.get('text',''),'review_required':True,
                'id':stable_alert_id(sha256(source),old['check_id'],a,b,'upstream:'+old['id']+':'+str(portion_index),old.get('text','')),
                'upstream_alert_id':old['id'],'upstream_report_sha256':ref['sha256'],
                'reason':'source warning mapped to retained audio or deletion boundary; requires current-output recheck'})
    return alerts, {'status':'executed','report':ref,'edit_map':{'path':str(path),'sha256':sha256(path)}}


def analyze(args: argparse.Namespace) -> int:
    source=args.source.expanduser().resolve(); out=args.output_dir.expanduser().resolve()
    if not source.is_file(): raise SystemExit(f"source not found: {source}")
    if out.exists() and any(out.iterdir()) and not args.resume:
        raise SystemExit("output directory is not empty; use a new directory or --resume")
    ascii_output(out).mkdir(parents=True,exist_ok=True)
    if not (os.environ.get("XX3ZDJJ_FFMPEG") or shutil.which("ffmpeg")) or not (os.environ.get("XX3ZDJJ_FFPROBE") or shutil.which("ffprobe")):
        raise SystemExit("ffmpeg and ffprobe are required")

    meta=probe(source); duration=float(meta["format"]["duration"]); source_hash=sha256(source)
    if (out/"analysis-manifest.json").is_file() and json.loads((out/"analysis-manifest.json").read_text())["source_sha256"] != source_hash:
        raise SystemExit("analysis output is bound to a different source")
    audio=out/"source-16k-mono.wav"
    extract_audio(source,audio)
    run(["ffmpeg","-v","error","-y","-i",str(audio),"-filter_complex","showwavespic=s=1800x360:colors=0x4F6BED","-frames:v","1",str(out/"waveform-overview.png")],capture=False)
    sil=run(["ffmpeg","-hide_banner","-i",str(audio),"-af",f"silencedetect=noise={args.silence_noise}:d={args.silence_min}","-f","null","-"])
    silences=parse_silence(sil.stderr,duration)
    fine=run(["ffmpeg","-hide_banner","-i",str(audio),"-af","silencedetect=noise=-38dB:d=0.04","-f","null","-"])
    fine_silences=parse_silence(fine.stderr,duration)

    transcript_path=out/"transcript.json"; check_path=out/"transcript-check.json"
    main=cached_recognition(source,audio,transcript_path,args)
    check=cached_recognition(source,audio,check_path,args,vad=True,condition=True) if not args.single_pass else None

    words=flatten_words(main); first=float(words[0]["start"]) if words else 0; last=float(words[-1]["end"]) if words else duration
    opening=opening_audit(source,audio,out,args,words)
    candidates=[]; cid=1
    for s in silences:
        start,end,dur=s["start"],s["end"],s["duration"]
        decision="retain_or_review"; proposed_start=""; proposed_end=""; reason="normal breath/emphasis possible; do not delete by duration alone"
        if start <= 0.10 and first-start > 0.60:
            proposed_start=0.0; proposed_end=max(0,min(first,end)-0.12); decision="proposed_delete_pending_confirmation"; reason="leading measured silence only; ASR cannot extend this range across acoustic activity"
        elif end <= first:
            decision="covered_by_leading_trim"; reason="pre-speech region already covered by leading trim candidate"
        elif end >= duration-0.10 and end-last > 0.60:
            proposed_start=min(duration,max(last,start)+0.12); proposed_end=duration; decision="proposed_delete_pending_confirmation"; reason="trailing measured silence only; ASR cannot extend this range across acoustic activity"
        elif start >= last:
            decision="covered_by_trailing_trim"; reason="post-speech region covered by trailing trim candidate when present"
        elif dur >= args.propose_internal:
            keep_each=0.14
            proposed_start=min(end,start+keep_each); proposed_end=max(start,end-keep_each)
            decision="proposed_shorten_pending_confirmation"; reason="long internal pause; retains 140 ms on each side pending listening"
        candidates.append({
            "id":f"S{cid:03d}","silence_start":f"{start:.3f}","silence_end":f"{end:.3f}","silence_duration":f"{dur:.3f}",
            "context_before":nearby_text(words,start,before=True),"context_after":nearby_text(words,end,before=False),
            "decision":decision,"proposed_delete_start":f"{proposed_start:.3f}" if proposed_start!="" else "",
            "proposed_delete_end":f"{proposed_end:.3f}" if proposed_end!="" else "","reason":reason,"listening_status":"not human-auditioned",
        }); cid+=1
    write_csv(out/"silence-candidates.csv",candidates,list(candidates[0].keys()) if candidates else ["id"])

    proposed=[(float(x["proposed_delete_start"]),float(x["proposed_delete_end"])) for x in candidates if x["proposed_delete_start"] and float(x["proposed_delete_end"])>float(x["proposed_delete_start"])]
    retakes=detect_retake_groups(main["segments"],args.retake_policy)
    write_csv(out/"retake-candidates.csv",retakes,list(retakes[0].keys()) if retakes else ["id","decision","status"])
    retake_ranges=[(float(x["proposed_delete_start"]),float(x["proposed_delete_end"])) for x in retakes if x.get("proposed_delete_start")]
    video_stream=next((s for s in meta.get("streams",[]) if s.get("codec_type")=="video"),{})
    rate=video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate") or "30/1"
    num,den=(rate.split("/",1)+["1"])[:2] if "/" in rate else (rate,"1")
    source_fps=float(num)/max(float(den),1.0)
    opening_restarts=detect_opening_swallowed_restarts(check["segments"] if check else None,silences,fine_silences,args.retake_policy,source_fps)
    write_csv(out/"opening-retake-candidates.csv",opening_restarts,list(opening_restarts[0].keys()) if opening_restarts else ["id","decision","status"])
    opening_ranges=[(float(x["proposed_delete_start"]),float(x["proposed_delete_end"])) for x in opening_restarts if x.get("proposed_delete_start")]
    fragment_restarts=fragment_restart_candidates(words)
    decision_rows=[]
    for x in retakes:
        decision_rows.append({"candidate_id":x["id"],"candidate_type":"long_sentence_retake",
            "delete_start":x.get("proposed_delete_start",""),"delete_end":x.get("proposed_delete_end",""),
            "keep_start":x.get("last_attempt_start",""),"keep_end":x.get("last_attempt_end",""),
            "content":x.get("first_attempt_text",""),"evidence":f"similarity={x.get('similarity','')}; gap={x.get('gap_seconds','')}s",
            "program_decision":"local_audio_review_required",
            "actual_execution":"not_executed_in_analysis"})
    for x in opening_restarts:
        decision_rows.append({"candidate_id":x["id"],"candidate_type":"opening_swallowed_restart",
            "delete_start":x.get("proposed_delete_start",""),"delete_end":x.get("proposed_delete_end",""),
            "keep_start":x.get("last_attempt_audio_onset",""),"keep_end":"",
            "content":x.get("anomalous_token",""),"evidence":x.get("evidence",""),
            "program_decision":"local_audio_review_required","actual_execution":"not_executed_in_analysis"})
    for i,x in enumerate(fragment_restarts,1):
        decision_rows.append({"candidate_id":f"FR{i:03d}","candidate_type":"short_fragment_or_swallowed_restart",
            "delete_start":"","delete_end":"","keep_start":"","keep_end":"","content":x.get("content",""),
            "evidence":x.get("evidence",""),"program_decision":"local_audio_review_required",
            "actual_execution":"not_executed_in_analysis"})
    write_csv(out/"deletion-decisions.csv",decision_rows,
              ["candidate_id","candidate_type","delete_start","delete_end","keep_start","keep_end","content","evidence","program_decision","actual_execution"])
    merged_proposed=merge_ranges(proposed+retake_ranges+opening_ranges)
    proposed_total=sum(b-a for a,b in merged_proposed); estimated=max(0,duration-proposed_total)
    low=[{"start":f"{float(w['start']):.3f}","end":f"{float(w['end']):.3f}","word":w["word"],"probability":f"{float(w['probability']):.3f}","status":"text review; not corrected by guess"} for w in words if float(w.get("probability",1))<args.low_confidence]
    repeats=repeated_phrases(words)
    fragment_restarts=fragment_restart_candidates(words)
    review=[]
    for i,x in enumerate(low[:80],1): review.append({"id":f"L{i:03d}","type":"low_confidence_word","start":x["start"],"end":x["end"],"content":x["word"],"evidence":f"ASR probability {x['probability']}","status":x["status"]})
    for i,x in enumerate(repeats,1): review.append({"id":f"R{i:03d}","type":"possible_retake_or_semantic_repeat","start":f"{float(x['first_start']):.3f}","end":f"{float(x['repeat_end']):.3f}","content":x["phrase"],"evidence":f"nearby exact phrase repeated at {float(x['repeat_start']):.3f}s","status":x["status"]})
    for i,x in enumerate(fragment_restarts,1): review.append({"id":f"F{i:03d}","type":"possible_half_sentence_restart","start":f"{x['start']:.3f}","end":f"{x['end']:.3f}","content":x["content"],"evidence":x["evidence"],"status":x["status"]})
    write_csv(out/"review-items.csv",review,["id","type","start","end","content","evidence","status"])

    alerts=candidate_alerts(fragment_restarts+repeats,duration,'full_media_asr')+opening['alerts']
    for x in retakes:
        alerts.append({'check_id':'repeated_speech','start':float(x['first_attempt_start']),
            'end':float(x['last_attempt_end']),'kind':'long_sentence_retake','text':x['first_attempt_text'],
            'review_required':True,'evidence':x})
    for x in opening_restarts:
        alerts.append({'check_id':'repeated_speech','start':float(x['failed_attempt_start']),
            'end':float(x['anomalous_token_end']),'kind':'long_opening_token','text':x['anomalous_token'],
            'review_required':True,'evidence':x})
    for x in candidates:
        if x['decision'].startswith('proposed'):
            alerts.append({'check_id':'breath_gaps','start':float(x['silence_start']),
                'end':float(x['silence_end']),'kind':'pause_candidate','text':'',
                'review_required':True,'evidence':x})
    for x in low:
        if float(x['end'])>float(x['start']):
            alerts.append({'check_id':'word_integrity','start':float(x['start']),'end':float(x['end']),
                'kind':'low_confidence_word','text':x['word'],'review_required':True,'evidence':x})
    machine=make_report(source,duration,review_checks(duration,alerts,opening),unique_alerts(source,alerts))
    machine['stage']='analyze'
    machine['detection_checks']={
        'long_retake':{'status':'executed','count':len(retakes),'coverage':full_coverage(duration)},
        'fragment_restart':{'status':'executed','count':len(fragment_restarts),'coverage':full_coverage(duration)},
        'opening_overlap':{'status':opening['status'],'candidate_count':len(opening['alerts']),'coverage':opening.get('coverage',{}),'reason':opening.get('reason','')},
        'second_full_asr':{'status':'skipped' if args.single_pass else 'executed',
            'reason':'--single-pass; opening windows still required' if args.single_pass else 'same model cross-pass is not independent proof of clean speech'}}
    (out/'review-report.json').write_text(json.dumps(machine,ensure_ascii=False,indent=2),encoding='utf-8')

    manifest={"source":str(source),"source_sha256":source_hash,"probe":meta,"stage":"analyze","source_modified":False,"model":args.model,"passes":1 if args.single_pass else 2,"parameters":{"silence_noise":args.silence_noise,"silence_min":args.silence_min,"propose_internal":args.propose_internal,"low_confidence":args.low_confidence,"retake_policy":args.retake_policy}}
    (out/"analysis-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    summary={"source_duration_seconds":duration,"detected_word_count":len(words),"silence_candidate_count":len(candidates),"silence_proposed_range_count":len(proposed),"retake_group_count":len(retakes),"retake_proposed_range_count":len(retake_ranges),"opening_swallowed_restart_count":len(opening_restarts),"effective_opening_candidate_count":len(opening["alerts"]),"merged_proposed_range_count":len(merged_proposed),"proposed_delete_seconds":round(proposed_total,3),"estimated_original_speed_duration_seconds":round(estimated,3),"low_confidence_word_count":len(low),"repeat_candidate_count":len(repeats),"half_sentence_restart_candidate_count":len(fragment_restarts),"retake_policy":args.retake_policy,"human_listening":"not performed","editing_performed":False,"command_status":"completed","quality_status":machine["quality_status"],"detection_checks":machine["detection_checks"],"unresolved_alert_count":len(machine["alerts"])}
    (out/"analysis-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    transcript_text="\n".join(f"- {s['start']:.2f}–{s['end']:.2f}：{s['text'].strip()}" for s in main["segments"])
    report=f"""# 口播原片分析报告\n\n## 范围\n\n本轮仅分析，没有剪切、变速、渲染或生成剪映工程。全部拟删区间等待用户确认；未进行真人耳听。\n\n## 输入\n\n- 文件：`{source}`\n- SHA256：`{source_hash}`\n- 时长：{duration:.3f}秒\n- 本地ASR：faster-whisper {args.model} int8，{1 if args.single_pass else 2}路\n- 重录策略：`{args.retake_policy}`\n\n## 自动候选\n\n- 静音候选：{len(candidates)}处，其中{len(proposed)}处提出缩短\n- 连续重录组：{len(retakes)}组，其中{len(retake_ranges)}组达到机器高置信拟删条件\n- 开场异常长词候选：{len(opening_restarts)}组；有效发声开场多尺度候选：{len(opening["alerts"])}项（执行状态：{opening["status"]}）\n- 合并去重后的拟删区间：{len(merged_proposed)}处，共{proposed_total:.3f}秒\n- 原速预计时长：{estimated:.3f}秒\n- 低置信词：{len(low)}项\n- 近距离重复表达候选：{len(repeats)}项\n\n详细静音区间见 `silence-candidates.csv`，长句重录组见 `retake-candidates.csv`，开场吞并候选见`opening-retake-candidates.csv`，其他文字疑点见 `review-items.csv`。`last_complete`只提出候选，最后一次完整性仍需试听或用户确认。\n\n## 主转写\n\n{transcript_text}\n\n## 状态\n\n- 哈希、媒体参数、波形、逐词时间、静音候选、重录候选：已生成\n- 真人听校、吞字判断、最后一句完整性：未验证\n- 实际剪辑：未执行\n"""
    report += f"\n- 命令执行：completed；质量状态：{machine['quality_status']}；未解决警报：{len(machine['alerts'])}\n- 有效开场分窗：{opening['status']}；策略 none 不关闭检测。\n- 每项执行范围及原因见 review-report.json；零候选不能代替原音复核。\n"
    (out/"analysis-report.md").write_text(report,encoding="utf-8")
    print(json.dumps({"output_dir":str(out),"summary":summary},ensure_ascii=False,indent=2))
    return 0


def review_stage(args: argparse.Namespace) -> int:
    """Run detection, preserving uncertainty and source-to-output alert lineage."""
    source=args.source.expanduser().resolve(); out=ascii_output(args.output_dir.expanduser().resolve())
    if not source.is_file(): raise SystemExit('source not found')
    out.mkdir(parents=True,exist_ok=True)
    duration=float(probe(source)['format']['duration'])
    audio=out/'source-16k-mono.wav'; extract_audio(source,audio)
    full=args.stage=='residual-check'
    windows=[]
    if full:
        windows=[(0.0,duration)]
    else:
        requested=[]
        if args.window:
            requested=[tuple(map(float,t.split(':',1))) for t in args.window]
        elif args.candidates:
            path=args.candidates.expanduser().resolve()
            items=json.loads(path.read_text(encoding='utf-8-sig')) if path.suffix=='.json' else list(csv.DictReader(path.open(encoding='utf-8-sig')))
            if isinstance(items,dict): items=items.get('alerts',items.get('candidates',[]))
            requested=[(float(x['start']),float(x['end'])) for x in items]
        else: raise SystemExit('local-review needs --window START:END or --candidates JSON/CSV')
        for a,b in requested:
            if not 0<=a<b<=duration+.01: raise SystemExit('invalid review window')
            # Preserve the precise requested fragment and add overlapping context.
            windows.append((a,min(duration,b)))
            cursor=max(0,a-.4); end=min(duration,b+.6)
            while cursor<end:
                finish=min(end,cursor+2.5); windows.append((cursor,finish))
                if finish>=end: break
                cursor+=1.0
    windows=list(dict.fromkeys(windows))
    decoder=OpeningDecoder(source,out/'windows',args)
    reports=[]; alerts=[]; first_words=[]
    from opening_review import source_relative_words
    for a,b in windows:
        try:
            transcript=decoder({'start':a,'end':b})
            local=flatten_words(transcript)
            # Zero-duration tokens carry no reliable acoustic span; the other
            # decoded words remain usable. Explicitly record these anomalies.
            invalid=[w for w in local if float(w['end'])<=float(w['start'])]
            words=source_relative_words([w for w in local if float(w['end'])>float(w['start'])],a)
            if a==0: first_words=words
            candidates=fragment_restart_candidates(words)+repeated_phrases(words)
            alerts.extend(candidate_alerts(candidates,duration,'residual_asr' if full else 'feedback_overlap'))
            for w in invalid:
                at=max(0,min(duration-.08,a+float(w['start'])))
                alerts.append({'check_id':'word_integrity','start':at,'end':min(duration,at+.08),
                    'kind':'invalid_word_timing','text':w['word'],'review_required':True,
                    'reason':'zero-duration ASR word; timing cannot certify an intact syllable'})
            reports.append({'window':[a,b],'status':'executed','words':words,'candidates':candidates})
        except (OSError,ValueError,RuntimeError,ImportError) as error:
            reports.append({'window':[a,b],'status':'unavailable','reason':str(error),'candidates':[]})
    opening=opening_audit(source,audio,out,args,first_words,decoder=decoder)
    alerts.extend(opening['alerts'])
    silence=run(['ffmpeg','-hide_banner','-i',str(audio),'-af','silencedetect=noise=-42dB:d=0.35','-f','null','-'])
    for item in parse_silence(silence.stderr,duration):
        if item['end']>item['start']:
            alerts.append({'check_id':'breath_gaps','start':item['start'],'end':item['end'],
                'kind':'pause_review','text':'','review_required':True,
                'reason':'measured quiet interval; listen to distinguish breath, pacing, or dead air'})
    inherited,lineage=propagate_analysis_alerts(source,duration)
    alerts.extend(inherited)
    feedback=getattr(args,'feedback',None)
    comparison=None
    if feedback:
        reference=getattr(args,'reference_source',None)
        reference_windows=getattr(args,'reference_window',None)
        if not reference or not reference_windows:
            raise SystemExit('user feedback review requires --reference-source and --reference-window for original/current comparison')
        other=argparse.Namespace(**vars(args))
        other.source=reference; other.output_dir=out/'reference_review'; other.stage='local-review'
        other.window=reference_windows; other.candidates=None; other.feedback=None
        other.reference_source=None; other.reference_window=[]
        review_stage(other)
        ref=other.output_dir/'review-report.json'
        comparison={'path':str(ref),'sha256':sha256(ref),'source_sha256':sha256(reference.expanduser().resolve())}
        a,b=windows[0]
        alerts.append({'check_id':'word_integrity','start':a,'end':b,'kind':'user_feedback',
            'text':feedback,'review_required':True,'reason':'compare original and current audio; prior transcript cannot dismiss feedback',
            'reference_report':comparison})
    checks=review_checks(duration,alerts,opening,full=full)
    if any(x['status']!='executed' for x in reports):
        checks['repeated_speech'].update(status='unavailable',reason='one or more requested ASR windows failed; incomplete detection')
    if full and lineage['status']!='executed':
        checks['word_integrity']['reason']+='; '+lineage['reason']
    report=make_report(source,duration,checks,unique_alerts(source,alerts))
    report.update(stage=args.stage,windows=reports,opening_review={'path':str(out/'opening-review.json'),
        'sha256':sha256(out/'opening-review.json'),'status':opening['status']},source_review_lineage=lineage,
        reference_review=comparison,semantic_completeness='not verified',
        note='Command completion and ASR agreement do not establish speech quality. Resolve every alert against this exact media/report.')
    (out/'review-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(out/'review-report.json'),'command_status':'completed',
        'quality_status':report['quality_status'],'unresolved_alerts':len(report['alerts']),
        'checks':checks},ensure_ascii=False,indent=2))
    return 0


def rough_cut(args: argparse.Namespace) -> int:
    """Render an original-speed rough cut from explicit confirmed ranges."""
    source=args.source.expanduser().resolve(); analysis=args.analysis_dir.expanduser().resolve(); out=args.output_dir.expanduser().resolve()
    if not source.is_file(): raise SystemExit(f"source not found: {source}")
    manifest_path=analysis/"analysis-manifest.json"
    if not manifest_path.is_file(): raise SystemExit(f"analysis manifest not found: {manifest_path}")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    source_hash=sha256(source)
    if manifest.get("source_sha256")!=source_hash: raise SystemExit("analysis cache source hash mismatch")
    if out.exists() and any(out.iterdir()) and not args.overwrite:
        raise SystemExit("output directory is not empty; use a new directory or --overwrite")
    meta=probe(source); duration=float(meta["format"]["duration"])
    video_stream=next((s for s in meta.get("streams",[]) if s.get("codec_type")=="video"),None)
    if video_stream is None or not any(s.get("codec_type")=="audio" for s in meta.get("streams",[])):
        raise SystemExit("rough-cut requires both video and audio streams")
    output_fps=args.fps or video_stream.get("r_frame_rate")
    if not output_fps or output_fps == "0/0":
        raise SystemExit("source frame rate unavailable; explicitly select a verified frame rate")
    if Path(args.output_name).name != args.output_name or args.output_name in ("", ".", ".."):
        raise SystemExit("output-name must be a file name, not a path")
    ascii_output(out)
    if not args.output_name.isascii(): raise SystemExit("output-name must be ASCII")
    if (out/args.output_name).resolve()==source: raise SystemExit("output must never replace the source")
    deletes=[]; boundary_evidence=[]
    approved_ids=set(args.approve_candidate)
    if approved_ids and not args.decision_file:
        raise SystemExit("approved candidate ids require a decision file")
    if args.decision_file:
        decision_path=args.decision_file.expanduser().resolve()
        if not decision_path.is_file(): raise SystemExit(f"decision file not found: {decision_path}")
        with decision_path.open("r",encoding="utf-8-sig",newline="") as f:
            decision_rows=list(csv.DictReader(f))
        known={x.get("candidate_id") for x in decision_rows}
        missing=approved_ids-known
        if missing: raise SystemExit(f"approved candidate ids not found: {sorted(missing)}")
        for row in decision_rows:
            if row.get("candidate_id") not in approved_ids: continue
            if not row.get("delete_start") or not row.get("delete_end"):
                raise SystemExit(f"approved candidate has no executable range: {row.get('candidate_id')}")
            cut_start=float(row["delete_start"]); cut_end=float(row["delete_end"])
            if row.get("acoustic_evidence"):
                evidence_path=Path(row["acoustic_evidence"]).expanduser()
                if not evidence_path.is_absolute(): evidence_path=decision_path.parent/evidence_path
                evidence=json.loads(evidence_path.read_text(encoding="utf-8-sig"))
                if evidence.get("source_sha256")!=source_hash or evidence.get("status")!="verified_acoustic_bounds":
                    raise SystemExit("acoustic evidence must be source-bound and explicitly verified")
                cut_start=frame_safe_retake_cut_start(float(evidence["previous_word_end"]),float(evidence["failed_audio_onset"]),float(Fraction(output_fps)))
                if math.ceil(cut_end*float(Fraction(output_fps))-1e-8)/float(Fraction(output_fps))>float(evidence["last_complete_audio_onset"]):
                    raise SystemExit("frame-quantized delete end overlaps the last complete take's measured onset")
                boundary_evidence.append({"candidate_id":row["candidate_id"],"evidence":str(evidence_path),
                                          "evidence_sha256":sha256(evidence_path),"resolved_start":cut_start})
            elif row.get("candidate_type") in ("short_fragment_or_swallowed_restart","opening_swallowed_restart","long_sentence_retake"):
                raise SystemExit("retake execution requires source-bound acoustic_evidence; ASR similarity is not a cut boundary")
            deletes.append((cut_start,cut_end,
                            f"approved candidate {row['candidate_id']}: {row.get('candidate_type','retake')}"))
    for i,value in enumerate(args.confirmed_delete,1):
        parts=value.split(":",2)
        if len(parts)<2: raise SystemExit("--confirmed-delete must be START:END[:REASON]")
        start,end=float(parts[0]),float(parts[1]); reason=parts[2] if len(parts)>2 else "user-confirmed deletion"
        if not 0<=start<end<=duration+0.05: raise SystemExit(f"invalid delete range: {value}")
        deletes.append((start,min(end,duration),reason))
    deletes=sorted(deletes)
    for start,end,reason in deletes:
        if not 0 <= start < end <= duration:
            raise SystemExit("decision contains an invalid source deletion range")
    for i in range(1,len(deletes)):
        if deletes[i][0] < deletes[i-1][1]: raise SystemExit("confirmed delete ranges overlap")
    kept=[]; cursor=0.0
    for start,end,reason in deletes:
        if start>cursor: kept.append((cursor,start))
        cursor=end
    if cursor<duration: kept.append((cursor,duration))
    if not kept: raise SystemExit("confirmed ranges delete the entire source")
    # Quantize shared audio/video trims to the same source frame grid.
    fps_value=float(Fraction(output_fps))
    kept=[(math.ceil(a*fps_value-1e-8)/fps_value,min(duration,math.ceil(b*fps_value-1e-8)/fps_value)) for a,b in kept]
    kept=[(a,b) for a,b in kept if b>a]
    if not kept: raise SystemExit("no source frame remains")
    out.mkdir(parents=True,exist_ok=True)
    graph=[]; concat=[]
    for i,(start,end) in enumerate(kept):
        graph += [f"[0:v]trim=start={start:.9f}:end={end:.9f},setpts=PTS-STARTPTS[v{i}]",
                  f"[0:a]atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS[a{i}]"]
        concat += [f"[v{i}][a{i}]"]
    graph=";".join(graph)+";"+"".join(concat)+f"concat=n={len(kept)}:v=1:a=1[v][a]"
    media=out/args.output_name
    run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",str(source),"-filter_complex",graph,
         "-map","[v]","-map","[a]","-r",output_fps,"-c:v","libx264","-crf",str(args.crf),"-preset",args.preset,
         "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",str(media)],capture=False)
    mapped=[]; out_cursor=0.0
    for start,end in kept:
        mapped.append({"source_start":round(start,6),"source_end":round(end,6),"output_start":round(out_cursor,6),"output_end":round(out_cursor+end-start,6)})
        out_cursor += end-start
    delete_rows=[{"id":f"D{i:03d}","source_start":f"{a:.6f}","source_end":f"{b:.6f}","duration":f"{b-a:.6f}","reason":reason,"authorization":"explicit current-stage rough-cut authorization"} for i,(a,b,reason) in enumerate(deletes,1)]
    write_csv(out/"deleted-ranges.csv",delete_rows,["id","source_start","source_end","duration","reason","authorization"])
    analysis_ref=analysis/'review-report.json'
    source_review=({'path':str(analysis_ref),'sha256':sha256(analysis_ref),'source_sha256':source_hash}
                   if analysis_ref.is_file() else None)
    edit_map={"output_sha256":sha256(media),"analysis_review":source_review,"source":str(source),"source_sha256":source_hash,"speed":1.0,"deleted_source_ranges":delete_rows,"kept_segments":mapped,"planned_output_duration":round(out_cursor,6),
              "frame_rate":output_fps,"boundary_evidence":boundary_evidence,"coordinate_precision":"frame-quantized source trims; audio follows same boundaries"}
    (out/"edit-map.json").write_text(json.dumps(edit_map,ensure_ascii=False,indent=2),encoding="utf-8")
    validation=media_validation(media,meta,output_fps,expected_duration=out_cursor)
    validation.update({"source_hash_match":True,"speed":1.0,"cuts":len(deletes),"command_status":"completed","quality_status":"unverified","residual_check":"not performed; run residual-check on this exact media"})
    listening=out/"cut-listening"; listening.mkdir(exist_ok=True)
    clips=[]
    cut_points=[row["output_end"] for row in mapped[:-1]]
    for i,point in enumerate(cut_points):
        start=max(0,point-1); end=min(out_cursor,point+1); clip=listening/f"cut-{i:04d}.wav"
        run(["ffmpeg","-v","error","-y","-ss",str(start),"-i",str(media),"-t",str(end-start),"-vn","-c:a","pcm_s16le",str(clip)],capture=False)
        clips.append({"id":f"CUT{i:04d}","output_cut":point,"clip_start":start,"clip_end":end,"path":str(clip),"human_listening":"not performed"})
    for name,start,end in (("opening",0,min(2,out_cursor)),("ending",max(0,out_cursor-2),out_cursor)):
        clip=listening/f"{name}.wav"
        run(["ffmpeg","-v","error","-y","-ss",str(start),"-i",str(media),"-t",str(end-start),"-vn","-c:a","pcm_s16le",str(clip)],capture=False)
        clips.append({"id":name,"clip_start":start,"clip_end":end,"path":str(clip),"human_listening":"not performed"})
    (listening/"manifest.json").write_text(json.dumps({"media_sha256":sha256(media),"clips":clips},indent=2),encoding="utf-8")
    validation["listening_manifest"]=str(listening/"manifest.json")
    (out/"validation.json").write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":"render_completed_quality_unverified" if validation["spec_status"]=="passed" else "blocked","media":str(media),"edit_map":str(out/"edit-map.json"),"deleted_ranges":str(out/"deleted-ranges.csv"),"validation":validation},ensure_ascii=False,indent=2))
    return 0 if validation["spec_status"]=="passed" else 2


def caption_chunks(lines: list[str], max_chars: int) -> list[str]:
    """Only explicit line/punctuation boundaries; never cut a word by length."""
    chunks=[]
    for line in lines:
        chunks.extend(part.strip(" ，,") for part in re.split(r"(?<=[，。！？；,!?;])",line.strip()) if clean_token(part))
    return chunks


def align_caption_words(chunks: list[str], words: list[dict]) -> tuple[list[dict], dict]:
    chars=[]
    for wi,w in enumerate(words):
        for ch in clean_token(w["word"]).lower(): chars.append((ch,wi))
    script_norm="".join(clean_token(x).lower() for x in chunks)
    asr_norm="".join(x[0] for x in chars)
    matcher=SequenceMatcher(None,script_norm,asr_norm,autojunk=False); mapping={}
    for block in matcher.get_matching_blocks():
        for k in range(block.size): mapping[block.a+k]=block.b+k
    unmatched_script=[{"index":i,"character":c} for i,c in enumerate(script_norm) if i not in mapping]
    matched_asr=set(mapping.values())
    unmatched_audio=[{"character":c,"word_index":wi,"word":words[wi]} for i,(c,wi) in enumerate(chars) if i not in matched_asr]
    rows=[]; cursor=0
    for text in chunks:
        n=len(clean_token(text)); idxs=[mapping[i] for i in range(cursor,cursor+n) if i in mapping]
        if len(idxs)!=n:
            cursor+=n; continue
        first=chars[min(idxs)][1]; last=chars[max(idxs)][1]
        rows.append({"text":text,"word_start":float(words[first]["start"]),"word_end":float(words[last]["end"]),
                     "first_word_index":first,"last_word_index":last,
                     "matched_first_last_word":[words[first]["word"],words[last]["word"]],
                     "timing_evidence":"original ASR word timestamps; intra-token timestamps are never interpolated"})
        cursor+=n
    overlaps=sum(b["word_start"]<a["word_end"]-1e-8 for a,b in zip(rows,rows[1:]))
    report={"alignment_character_coverage":len(mapping)/max(1,len(script_norm)),
            "audio_character_coverage":len(matched_asr)/max(1,len(asr_norm)),
            "unmatched_script":unmatched_script,"unmatched_audio":unmatched_audio,"word_overlaps":overlaps,
            "status":"blocked" if unmatched_script or unmatched_audio or overlaps or not rows else "machine_matched",
            "human_listening":"not performed"}
    return rows,report


def ass_escape(text: str) -> str:
    return text.replace("\\","\\\\").replace("{","\\{").replace("}","\\}").replace("\n","\\N")


def srt_time(value: float) -> str:
    ms=math.ceil(value*1000-1e-8); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); sec,ms=divmod(ms,1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def ass_time(value: float) -> str:
    # Ceil, never round a new caption into a time before its word evidence.
    cs=math.ceil(value*100-1e-8); h,cs=divmod(cs,360000); m,cs=divmod(cs,6000); sec,cs=divmod(cs,100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def captions_stage(args: argparse.Namespace) -> int:
    source=args.source.expanduser().resolve(); script_path=args.script.expanduser().resolve(); out=ascii_output(args.output_dir.expanduser().resolve())
    if not source.is_file() or not script_path.is_file(): raise SystemExit("source or script not found")
    if out.exists() and any(out.iterdir()) and not args.overwrite: raise SystemExit("output directory is not empty; use a new directory or --overwrite")
    out.mkdir(parents=True,exist_ok=True)
    script_text=script_path.read_text(encoding="utf-8-sig"); lines=[x.strip() for x in script_text.splitlines() if x.strip()]
    chunks=caption_chunks(lines,args.max_chars)
    if args.transcript:
        transcript=json.loads(args.transcript.expanduser().resolve().read_text(encoding="utf-8-sig"))
        if transcript.get("source_sha256")!=sha256(source): raise SystemExit("provided transcript is not bound to this source hash")
    else:
        audio=out/"caption-audio-16k.wav"
        extract_audio(source,audio)
        transcript=cached_recognition(source,audio,out/"caption-transcript.json",args)
    (out/"caption-transcript.json").write_text(json.dumps(transcript,ensure_ascii=False,indent=2),encoding="utf-8")
    words=flatten_words(transcript)
    rows,validation=align_caption_words(chunks,words)
    validation.update({"source_sha256":sha256(source),"script_sha256":sha256(script_path),
                       "transcript_sha256":sha256(out/"caption-transcript.json")})
    duration=float(probe(source)["format"]["duration"])
    validation["invalid_word_ranges"]=[i for i,w in enumerate(words) if not 0<=float(w["start"])<float(w["end"])<=duration+.025]
    try:
        from PIL import ImageFont
        font=ImageFont.truetype(str(args.font_file.expanduser().resolve()),args.font_size)
        widths=[{"text":text,"width":font.getlength(text),"visible_bbox":list(font.getbbox(text))} for text in chunks]
        validation["width_checks"]=widths
        validation["width_overflow"]=[x for x in widths if x["width"]>args.canvas_width-2*args.margin]
    except (ImportError,OSError) as error:
        validation["font_measurement_error"]=str(error); validation["status"]="blocked"
    validation["long_lines"]=[x for x in chunks if len(clean_token(x))>args.max_chars]
    validation["isolated_han_lines"]=[x for x in chunks if len(clean_token(x))==1 and re.search(r"[\u4e00-\u9fff]",x)]
    if validation["invalid_word_ranges"] or validation.get("width_overflow") or ((validation["long_lines"] or validation["isolated_han_lines"]) and not args.allow_long_lines):
        validation["status"]="blocked"
    validation["style_status"]=args.style_status
    report_path=out/"caption-validation.json"
    if validation["status"]=="blocked":
        report_path.write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"status":"blocked","reason":"text/timing/line-width review required; no captions exported","report":str(report_path)},ensure_ascii=False)); return 2
    connected=connect([dict(row,start=row["word_start"],end=row["word_end"]) for row in rows],args.max_gap)
    for row in connected:
        row["display_start"]=row.pop("start"); row["display_end"]=row.pop("end")
    # Count actual export-level intersections, including ASS centisecond precision.
    export_overlaps=sum(math.ceil(b["display_start"]*100-1e-8)<math.ceil(a["display_end"]*100-1e-8) for a,b in zip(connected,connected[1:]))
    zero_events=sum(math.ceil(x["display_start"]*100-1e-8)>=math.ceil(x["display_end"]*100-1e-8) for x in connected)
    validation.update({"events":len(connected),"overlaps":export_overlaps,"zero_length_export_events":zero_events,
                       "anticipation_seconds":max([max(0,x["word_start"]-math.ceil(x["display_start"]*100-1e-8)/100) for x in connected],default=0),
                       "onset_status":"machine word timestamps only; acoustic onsets not verified"})
    if export_overlaps or zero_events:
        validation["status"]="blocked"; report_path.write_text(json.dumps(validation,indent=2),encoding="utf-8"); return 2
    srt=[]
    for i,row in enumerate(connected,1):
        srt += [str(i),f"{srt_time(row['display_start'])} --> {srt_time(row['display_end'])}",html.escape(row["text"],quote=False),""]
    srt_path=out/"captions.srt"; srt_path.write_text("\n".join(srt),encoding="utf-8-sig")
    ass=(f"[Script Info]\nScriptType: v4.00+\nPlayResX: {args.canvas_width}\nPlayResY: {args.canvas_height}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
         "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
         f"Style: Main,{args.font_name},{args.font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,1,0,4,5,{args.margin},{args.margin},0,1\n\n"
         "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    for row in connected:
        ass+=f"Dialogue: 0,{ass_time(row['display_start'])},{ass_time(row['display_end'])},Main,,0,0,0,,{{\\pos({args.pos_x},{args.pos_y})}}{ass_escape(row['text'])}\n"
    ass_path=out/"captions.ass"; ass_path.write_text(ass,encoding="utf-8-sig")
    (out/"caption-alignment.json").write_text(json.dumps(connected,ensure_ascii=False,indent=2),encoding="utf-8")
    report_path.write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding="utf-8")
    result={"status":"completed","srt":str(srt_path),"ass":str(ass_path),"validation":validation}
    if args.render_preview:
        fontsdir=filter_path(args.font_file.expanduser().resolve().parent); ap=filter_path(ass_path); preview=out/"caption-preview.mp4"
        run(["ffmpeg","-y","-v","error","-i",str(source),"-vf",f"ass='{ap}':fontsdir='{fontsdir}'","-c:v","libx264","-crf","18","-preset","medium","-pix_fmt","yuv420p","-c:a","copy","-movflags","+faststart",str(preview)],capture=False)
        result["media_validation"]=media_validation(preview,probe(source),source_fps(source)); result["preview"]=str(preview)
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0


def filter_path(path: Path) -> str:
    return str(path).replace("\\","/").replace(":","\\:").replace("'","'\\\\''")


def source_fps(source: Path) -> str:
    stream=next(s for s in probe(source)["streams"] if s["codec_type"]=="video")
    rate=stream.get("r_frame_rate") or stream.get("avg_frame_rate")
    if not rate or rate=="0/0": raise SystemExit("source frame rate unavailable")
    return rate


def preview_stage(args: argparse.Namespace) -> int:
    source=args.source.expanduser().resolve(); background=args.background.expanduser().resolve()
    ass_path=args.ass.expanduser().resolve(); font_file=args.font_file.expanduser().resolve()
    out=ascii_output(args.output.expanduser().resolve())
    if out==source: raise SystemExit("preview output must never replace the source")
    if out.suffix.lower()!=".mp4": raise SystemExit("preview output must be an MP4")
    for label,path in (("source",source),("background",background),("ass",ass_path),("font-file",font_file)):
        if not path.is_file(): raise SystemExit(f"{label} not found: {path}")
    if out.exists() and not args.overwrite: raise SystemExit("output exists; use a new output path or --overwrite")
    if args.mask_shape == "rounded_square" and not (0 <= args.corner_radius <= args.mask_diameter/2):
        raise SystemExit("corner radius must be between 0 and half the window size")
    out.parent.mkdir(parents=True,exist_ok=True)
    if args.mask_diameter <= 0 or args.canvas_width <= 0 or args.canvas_height <= 0:
        raise SystemExit("canvas and mask dimensions must be positive")
    mask_x=round(args.mask_center_x-args.mask_diameter/2)
    mask_y=round(args.mask_center_y-args.mask_diameter/2)
    if mask_x < 0 or mask_y < 0 or mask_x+args.mask_diameter > args.canvas_width or mask_y+args.mask_diameter > args.canvas_height:
        raise SystemExit("circle mask falls outside the canvas")
    fontsdir=filter_path(font_file.parent); ass_filter=filter_path(ass_path)
    diameter=args.mask_diameter
    fps=args.fps or source_fps(source)
    source_meta=probe(source)
    audio_stream=next((s for s in source_meta["streams"] if s["codec_type"]=="audio"),{})
    if audio_stream.get("codec_name") not in ("aac","mp3","alac","ac3","eac3"):
        raise SystemExit("source audio is not approved MP4-compatible audio; explicitly convert and reapprove before preview, no implicit re-encoding")
    if args.background_speed<0: raise SystemExit("background speed must be nonnegative")
    if args.background_motion!="static" and args.background_speed<=0:
        raise SystemExit("moving background requires an explicitly selected positive background speed")
    # Scale proportionally by width, then take a square crop selected for the
    # current subject framing. The alpha expression creates a true circle.
    if args.mask_shape == "circle":
        alpha="if(lte((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2),(W/2)*(W/2)),255,0)"
    else:
        radius=args.corner_radius
        alpha=(f"if(gt(lte(abs(X-W/2),W/2-{radius})+lte(abs(Y-H/2),H/2-{radius}),0),255,"
               f"if(lte((abs(X-W/2)-(W/2-{radius}))*(abs(X-W/2)-(W/2-{radius}))+"
               f"(abs(Y-H/2)-(H/2-{radius}))*(abs(Y-H/2)-(H/2-{radius})),{radius}*{radius}),255,0))")
    bg=(
        f"[0:v]scale={args.canvas_width}:{args.canvas_height}:force_original_aspect_ratio=increase,"
        f"crop={args.canvas_width}:{args.canvas_height},setsar=1,setpts=PTS-STARTPTS")
    if args.background_motion == "static" or args.background_speed==0:
        bg+="[bg];"
    else:
        width=args.canvas_width
        x=(f"mod({width}-mod(t*{args.background_speed},{width}),{width})" if args.background_motion=="right"
           else f"mod(t*{args.background_speed},{width})")
        bg+=f",split=2[bga][bgb];[bga][bgb]hstack=inputs=2,crop={width}:{args.canvas_height}:x='{x}':y=0[bg];"
    graph=(bg+
        f"[1:v]scale={diameter}:-2,crop={diameter}:{diameter}:0:{args.subject_crop_y},"
        "setsar=1,setpts=PTS-STARTPTS,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='{alpha}'[person];"
        f"[bg][person]overlay={mask_x}:{mask_y}:shortest=1[masked];"
        f"[masked]ass='{ass_filter}':fontsdir='{fontsdir}',format=yuv420p[v]"
    )
    background_input=(["-loop","1","-framerate",fps] if background.suffix.lower() in (".jpg",".jpeg",".png",".webp",".bmp") else ["-stream_loop","-1"])
    render_target=out if not args.muxer_bin else out.with_name(out.stem+".render.mp4")
    if render_target != out and render_target.exists() and not args.overwrite:
        raise SystemExit("render intermediate exists; select a new output path")
    run(["ffmpeg","-y","-v","error",*background_input,"-i",str(background),"-i",str(source),
         "-filter_complex",graph,"-map","[v]","-map","1:a:0","-c:v","libx264","-crf",str(args.crf),
         "-preset",args.preset,"-r",fps,"-c:a","copy","-movflags","+faststart",str(render_target)],capture=False)
    if args.muxer_bin:
        muxer=args.muxer_bin.expanduser().resolve()
        if not muxer.is_file(): raise SystemExit("explicit muxer binary not found")
        run([str(muxer),"-y","-v","error","-i",str(render_target),"-i",str(source),"-map","0:v:0","-map","1:a:0",
             "-c","copy","-movie_timescale",str(audio_stream.get("sample_rate",48000)),"-movflags","+faststart",str(out)],capture=False)
    validation=media_validation(out,probe(source),fps,dimensions=(args.canvas_width,args.canvas_height),expected_duration=float(probe(source)["format"]["duration"]))
    validation["audio_packet_identity"]=audio_packet_identity(source,out)
    if validation["audio_packet_identity"]["status"]!="passed": validation["spec_status"]="failed"
    validation.update({"source":str(source),"background":str(background),"ass":str(ass_path),
                "mask_shape":args.mask_shape,"mask_center":[args.mask_center_x,args.mask_center_y],
                "mask_diameter":diameter,"mask_bounds":[mask_x,mask_y,mask_x+diameter,mask_y+diameter],
                "corner_radius":args.corner_radius if args.mask_shape == "rounded_square" else None,
                "subject_crop_y":args.subject_crop_y,"canvas":[args.canvas_width,args.canvas_height],
                "fps":fps,"audio_mode":"stream_copy","background_motion":args.background_motion,
                "background_speed_px_per_second":args.background_speed,
                "loop_method":"cyclic double-width crop; first frame is fully covered"})
    validation_path=out.with_suffix(".validation.json")
    validation_path.write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":"completed" if validation["spec_status"]=="passed" else "blocked","preview":str(out),"validation":str(validation_path)},ensure_ascii=False,indent=2))
    return 0 if validation["spec_status"]=="passed" else 2


def main() -> int:
    raw=sys.argv[1:]
    if "jianying-project" in raw:
        index=raw.index("jianying-project"); forwarded=raw[index+1:]
        if "--project-config" in raw[:index]:
            ci=raw.index("--project-config"); forwarded += raw[ci:ci+2]
        adapter=Path(__file__).with_name("jianying_adapter.py")
        if not adapter.is_file():
            print(json.dumps({"status":"blocked","reason":"native project adapter is unavailable"})); return 2
        return subprocess.run([sys.executable,str(adapter),*forwarded]).returncode
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-config",type=Path)
    sub=ap.add_subparsers(dest="stage",required=True)
    a=sub.add_parser("analyze",help="read-only local analysis")
    a.add_argument("--source",required=True,type=Path); a.add_argument("--output-dir",required=True,type=Path)
    a.add_argument("--model",default=os.environ.get("XX3ZDJJ_MODEL_PATH","medium")); a.add_argument("--cpu-threads",type=int,default=4)
    a.add_argument("--silence-noise",default="-42dB"); a.add_argument("--silence-min",type=float,default=0.35)
    a.add_argument("--propose-internal",type=float,default=1.20); a.add_argument("--low-confidence",type=float,default=0.55)
    a.add_argument("--retake-policy",choices=("none","last_complete"),default="none")
    a.add_argument("--single-pass",action="store_true"); a.add_argument("--resume",action="store_true")
    r=sub.add_parser("rough-cut",help="render an explicitly authorized original-speed rough cut")
    r.add_argument("--source",required=True,type=Path); r.add_argument("--analysis-dir",required=True,type=Path)
    r.add_argument("--output-dir",required=True,type=Path); r.add_argument("--output-name",default="rough_cut_no_captions.mp4")
    r.add_argument("--confirmed-delete",action="append",default=[],help="START:END[:REASON]; repeatable")
    r.add_argument("--decision-file",type=Path,help="structured deletion-decisions.csv from analyze")
    r.add_argument("--approve-candidate",action="append",default=[],help="candidate id explicitly authorized for execution; repeatable")
    r.add_argument("--fps",default=None,help="default: preserve source frame rate"); r.add_argument("--crf",type=int,default=18); r.add_argument("--preset",default="medium")
    r.add_argument("--overwrite",action="store_true")
    c=sub.add_parser("captions",help="align an approved script to the actual edited audio")
    c.add_argument("--source",required=True,type=Path); c.add_argument("--script",required=True,type=Path); c.add_argument("--output-dir",required=True,type=Path)
    c.add_argument("--approval-report",required=True,type=Path,help="passed rough-cut checks and user approval bound to this source")
    c.add_argument("--model",default=os.environ.get("XX3ZDJJ_MODEL_PATH","medium")); c.add_argument("--cpu-threads",type=int,default=4); c.add_argument("--max-chars",type=int,default=11)
    c.add_argument("--font-name",required=True); c.add_argument("--font-file",required=True,type=Path); c.add_argument("--font-size",type=int,default=86)
    c.add_argument("--pos-x",type=int,default=540); c.add_argument("--pos-y",type=int,default=1075); c.add_argument("--style-status",default="provisional")
    c.add_argument("--transcript",type=Path,help="existing corrected word transcript with matching source_sha256")
    c.add_argument("--canvas-width",type=int,default=1080); c.add_argument("--canvas-height",type=int,default=1920)
    c.add_argument("--margin",type=int,default=60); c.add_argument("--max-gap",type=float,default=.35)
    c.add_argument("--allow-long-lines",action="store_true",help="explicit approval of reviewed semantic long/single-character lines; width overflow still blocks")
    c.add_argument("--render-preview",action="store_true"); c.add_argument("--overwrite",action="store_true")
    p=sub.add_parser("preview",help="render an authorized caption and person-mask preview")
    p.add_argument("--source",required=True,type=Path); p.add_argument("--background",required=True,type=Path)
    p.add_argument("--ass",required=True,type=Path); p.add_argument("--font-file",required=True,type=Path)
    p.add_argument("--approval-report",required=True,type=Path,help="passed caption checks and user approval bound to source and ASS")
    p.add_argument("--output",required=True,type=Path); p.add_argument("--mask-shape",choices=("circle","rounded_square"),required=True)
    p.add_argument("--canvas-width",type=int,default=1080); p.add_argument("--canvas-height",type=int,default=1920)
    p.add_argument("--mask-center-x",type=int,default=540); p.add_argument("--mask-center-y",type=int,default=1470)
    p.add_argument("--mask-diameter",type=int,default=620); p.add_argument("--subject-crop-y",type=int,required=True,
                   help="subject-specific crop offset chosen after inspecting this source; no cross-video default")
    p.add_argument("--corner-radius",type=int,default=48)
    p.add_argument("--fps",default=None); p.add_argument("--crf",type=int,default=18); p.add_argument("--preset",default="medium")
    p.add_argument("--background-motion",choices=("static","right","left"),default="static")
    p.add_argument("--background-speed",type=float,default=0.0,help="explicit pixels per second; only affects background")
    p.add_argument("--muxer-bin",type=Path,help="explicit compatible stream-copy muxer, if renderer's MP4 demuxer rounds terminal audio durations")
    p.add_argument("--overwrite",action="store_true")
    sub.add_parser("jianying-project",help="forward to native-project adapter subcommands")
    for name in ("local-review","residual-check"):
        review=sub.add_parser(name,help="local ASR evidence only, no deletion or human-listening claim")
        review.add_argument("--source",type=Path,required=True); review.add_argument("--output-dir",type=Path,required=True)
        review.add_argument("--model",default=os.environ.get("XX3ZDJJ_MODEL_PATH","medium")); review.add_argument("--cpu-threads",type=int,default=4)
        review.add_argument("--window",action="append",default=[]); review.add_argument("--candidates",type=Path)
        review.add_argument("--feedback",help="user-reported issue; requires original/current comparison")
        review.add_argument("--reference-source",type=Path)
        review.add_argument("--reference-window",action="append",default=[])
    for parser in sub.choices.values():
        parser.add_argument("--project-config",type=Path,default=argparse.SUPPRESS)
    args=ap.parse_args()
    if args.project_config:
        config=json.loads(args.project_config.expanduser().resolve().read_text(encoding="utf-8-sig"))
        settings=config.get("pipeline",{}).get(args.stage,{})
        parser=sub.choices[args.stage]
        explicit={x.split("=",1)[0] for x in raw if x.startswith("--")}
        excluded={"project_config","approval_report","confirmed_delete","approve_candidate","overwrite","decision_file","allow_long_lines"}
        for action in parser._actions:
            if action.required or action.dest in excluded or action.dest not in settings: continue
            if any(flag in explicit for flag in action.option_strings): continue
            value=settings[action.dest]
            if action.choices and value not in action.choices: raise SystemExit(f"invalid project-config value: {action.dest}")
            if action.type is not None and value is not None: value=action.type(value)
            setattr(args,action.dest,value)
    if args.stage in ("captions", "preview"):
        inputs = {"source": args.source}
        if args.stage == "preview":
            inputs["ass"] = args.ass
        errors = validate_report(args.approval_report,
                                 "rough-cut" if args.stage == "captions" else "captions",
                                 inputs)
        if errors:
            print(json.dumps({"status": "blocked", "stage": args.stage,
                              "errors": errors}, ensure_ascii=False))
            return 2
    if args.stage=="rough-cut": return rough_cut(args)
    if args.stage=="captions": return captions_stage(args)
    if args.stage=="preview": return preview_stage(args)
    if args.stage in ("local-review","residual-check"): return review_stage(args)
    if args.stage!="analyze":
        print(json.dumps({"status":"blocked","stage":args.stage,"reason":"stage requires explicit user authorization and is not implemented by this entrypoint"},ensure_ascii=False))
        return 2
    return analyze(args)


if __name__=="__main__":
    raise SystemExit(main())
