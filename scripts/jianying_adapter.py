"""Offline native candidates; static validity never proves native UI compatibility.

stdlib + discovered FFprobe. Upstream JSON templates are data, not imported code.
Never rewrites existing projects or global indices. Original-ranges deliberately
unsupported until approved audio/render equivalence can be demonstrated.
"""
import argparse
import copy
import configparser
from fractions import Fraction
import hashlib
import html
import json
import sys
import math
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from stage_gate import file_hash, validate_report

ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'jianying'
FONT_SUFFIXES = {'.otf', '.ttf', '.ttc', '.woff', '.woff2'}
DEFAULT_SHADOW = {'enabled': True, 'diffuse': .025, 'alpha': 1., 'distance': 5.,
                  'angle': -45., 'color': [0., 0., 0.]}
DRAFT_CONFIG_FIELDS = {'draft_root_path', 'draft_path', 'draft_save_path',
                       'draft_save_dir', 'draft_directory', 'draft_dir', 'draft_root'}
MAX_CONFIG_BYTES = 128 * 1024
MAX_KNOWN_CONFIG_FILES = 64


def normalized_shadow(value=None):
    if value is None:
        return copy.deepcopy(DEFAULT_SHADOW)
    need(isinstance(value, dict), 'caption shadow must be an explicit object')
    need(not (set(value)-set(DEFAULT_SHADOW)), 'Unknown caption shadow parameter')
    result = dict(copy.deepcopy(DEFAULT_SHADOW), **value)
    need(type(result['enabled']) is bool, 'Shadow enabled must be boolean')
    for key in ('diffuse','alpha','distance','angle'):
        need(type(result[key]) in (int,float) and math.isfinite(result[key]), 'Non-finite shadow parameter: '+key)
        result[key] = float(result[key])
    need(0 <= result['diffuse'] <= 1 and 0 <= result['alpha'] <= 1 and result['distance'] >= 0,
         'Invalid shadow blur, opacity or distance')
    color = result['color']
    need(isinstance(color,(list,tuple)) and len(color)==3 and
         all(type(v) in (int,float) and math.isfinite(v) and 0 <= v <= 1 for v in color), 'Invalid shadow RGB color')
    result['color'] = [float(v) for v in color]
    return result


def native_shadows(shadow):
    if not shadow['enabled']:
        return []
    return [dict(diffuse=shadow['diffuse'],alpha=shadow['alpha'],distance=shadow['distance'],
        content=dict(solid=dict(color=shadow['color'])),angle=shadow['angle'])]


def caption_style_record(caption, target_platform, base, check_evidence=True):
    """Resolve explicit/native-unit shadow plus honest reusable calibration metadata.

    style_profile is an inline object in the version-bound timeline. A calibrated
    profile needs platform/app/font versions and hashed non-font evidence. Its
    history never attests current pixel equivalence or current App/font matching.
    """
    profile = caption.get('style_profile', {})
    need(isinstance(profile,dict), 'caption style_profile must be an inline object')
    profile_shadow = normalized_shadow(profile.get('shadow'))
    if 'shadow' in caption:
        shadow = normalized_shadow(caption['shadow']); source = 'caption.shadow'
    elif 'shadow' in profile:
        shadow = profile_shadow; source = 'style_profile.shadow'
    else:
        shadow = normalized_shadow(); source = 'legacy_default'
    calibration = profile.get('calibration', {})
    need(isinstance(calibration,dict), 'style calibration must be an object')
    declared = calibration.get('status', 'unverified')
    need(declared in ('unverified','calibrated'), 'Unknown style calibration status')
    evidence = calibration.get('evidence', [])
    need(isinstance(evidence,list), 'Style calibration evidence must be a list')
    if declared == 'calibrated':
        for key in ('platform','app_version','font_name','font_version'):
            need(isinstance(calibration.get(key),str) and calibration[key].strip(), 'Calibrated style missing '+key)
        need(calibration['platform'] in ('mac','windows'), 'Calibrated style platform must be mac or windows')
        need(bool(evidence), 'Calibrated style needs actual hashed evidence')
    for item in evidence:
        need(isinstance(item,dict) and isinstance(item.get('path'),str) and item['path'] and
             isinstance(item.get('sha256'),str) and re.fullmatch('[0-9a-f]{64}',item['sha256']),
             'Invalid style calibration evidence reference')
        origin = resolved(base,item['path'])
        need(origin.suffix.lower() not in FONT_SUFFIXES, 'Font binaries cannot be calibration evidence copies')
        if check_evidence:
            need(origin.is_file() and file_hash(origin)==item['sha256'], 'Style calibration evidence missing or changed')
    matching_parameters = shadow == profile_shadow
    recorded = declared=='calibrated' and calibration.get('platform')==target_platform and matching_parameters
    reasons = []
    if declared=='calibrated' and calibration.get('platform') != target_platform:
        reasons.append('historical platform differs from target')
    if declared=='calibrated' and not matching_parameters:
        reasons.append('explicit shadow differs from calibrated profile')
    return dict(shadow=shadow, shadow_source=source,
        calibration=dict(status='historical_evidence_recorded' if recorded else 'unverified',
            declared_status=declared, platform=calibration.get('platform'), app_version=calibration.get('app_version'),
            font_name=calibration.get('font_name'), font_version=calibration.get('font_version'),
            evidence=copy.deepcopy(evidence), reasons=reasons),
        current_app_font_match='unverified', pixel_equivalence='unverified')



def uid():
    return str(uuid.uuid4()).upper()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def need(condition, message):
    if not condition:
        raise ValueError(message)


def resolved(base, value):
    p = Path(value).expanduser()
    return (base / p).resolve() if not p.is_absolute() else p.resolve()


def external_output(output):
    output = Path(output).resolve()
    need(not output.is_relative_to(Path(__file__).resolve().parents[1]),
         'Runtime output must be outside the Skill directory')
    need(not output.exists(), 'Refusing to overwrite existing output')
    return output


def safe_name(name):
    need(isinstance(name, str) and name.strip() and name not in {'.', '..'}, 'Invalid project name')
    need(not re.search(r'[\\/\x00-\x1f<>:"|?*]', name) and not name.endswith(('.', ' ')), 'Unsafe project name')
    need(name.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}, 'Reserved Windows name')
    return name


def probe(path, executable=None):
    ffprobe = executable or os.environ.get('XX3ZDJJ_FFPROBE') or shutil.which('ffprobe')
    need(ffprobe, 'FFprobe not found; discover/install approved compatible tools first')
    return json.loads(subprocess.check_output([str(ffprobe), '-v', 'error', '-count_frames',
        '-show_streams', '-show_format', '-of', 'json', str(path)], text=True, encoding="utf-8", errors="strict"))


def audio_signature(path, executable=None):
    ffprobe=executable or os.environ.get('XX3ZDJJ_FFPROBE') or shutil.which('ffprobe')
    need(ffprobe, 'FFprobe missing')
    data=json.loads(subprocess.check_output([str(ffprobe), '-v','error','-select_streams','a',
        '-show_streams','-show_packets','-show_data_hash','sha256','-show_entries',
        'stream=codec_name,sample_rate,channels,channel_layout:packet=pts_time,dts_time,duration_time,size,data_hash',
        '-of','json',str(path)],text=True,encoding='utf-8',errors='strict'))
    need(len(data.get('streams',[]))==1 and data.get('packets'), 'Exactly one approved audio stream required')
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def frame_us(frame, fps):
    return round(Fraction(frame * 1_000_000, 1) / fps)


def time_us(stamp):
    stamp = stamp.strip().replace(',', '.')
    h, m, s = stamp.split(':')
    return round((Fraction(int(h)*3600+int(m)*60) + Fraction(s))*1_000_000)


def caption_rows(path, fmt):
    text = Path(path).read_text(encoding='utf-8-sig')
    rows = []
    if fmt == 'ass':
        fields = ['Layer','Start','End','Style','Name','MarginL','MarginR','MarginV','Effect','Text']
        in_events = False
        for line in text.splitlines():
            if line.startswith('['):
                in_events = line.strip().lower() == '[events]'
            elif in_events and line.startswith('Format:'):
                fields = [x.strip() for x in line.split(':',1)[1].split(',')]
                need(fields[-1] == 'Text', 'ASS requires final Text field')
            elif in_events and line.startswith('Dialogue:'):
                values = line.split(':',1)[1].lstrip().split(',',len(fields)-1)
                need(len(values) == len(fields), 'Malformed ASS dialogue')
                event = dict(zip(fields,values))
                value = re.sub(r'\{[^}]*\}', '', event['Text']).replace(r'\N','\n').replace(r'\n','\n').replace(r'\h',' ')
                rows.append({'start':time_us(event['Start']), 'end':time_us(event['End']), 'text':value})
    elif fmt == 'srt':
        for block in re.split(r'\n\s*\n', text.replace('\r\n','\n').strip()):
            lines = block.splitlines()
            if not lines:
                continue
            index = next((i for i,line in enumerate(lines) if '-->' in line), None)
            need(index is not None, 'Malformed SRT block')
            stamps = lines[index].split('-->')
            need(len(stamps) == 2, 'Malformed SRT timing')
            rows.append({'start':time_us(stamps[0]),'end':time_us(stamps[1]),'text':html.unescape('\n'.join(lines[index+1:]))})
    else:
        raise ValueError('Captions format must be ass or srt')
    need(bool(rows), 'No captions found')
    return rows


def validate_media(record, base, ffprobe=None, require_audio=False):
    path = resolved(base, record['path'])
    need(path.is_file() and file_hash(path) == record['sha256'], 'Media missing or hash changed: '+str(path))
    fps = Fraction(str(record['fps']))
    count = record['frame_count']
    need(type(count) is int and count > 0 and fps > 0, 'Invalid frame count/fps')
    info = probe(path, ffprobe)
    v = next((x for x in info['streams'] if x['codec_type'] == 'video'), None)
    need(v is not None, 'No video stream')
    need(v['width'] == record['width'] and v['height'] == record['height'], 'Dimensions differ from timeline')
    need(Fraction(v['r_frame_rate']) == fps and Fraction(v['avg_frame_rate']) == fps, 'CFR/fps mismatch; normalize explicitly before approval')
    need(int(v.get('nb_read_frames', v.get('nb_frames', -1))) == count, 'Video frame count mismatch')
    need(abs(float(v.get('start_time','0'))) < 1e-6, 'Video start PTS must be zero')
    if require_audio:
        need(any(s['codec_type'] == 'audio' for s in info['streams']), 'Approved clean source needs embedded approved audio')
    return path, fps, count


def load_timeline(path, approval, ffprobe=None, project_config=None):
    path = Path(path).resolve(); base = path.parent; spec = read(path)
    need(spec.get('schema_version') == 1, 'Unknown timeline schema_version')
    need(spec.get('project_kind') in {'full','pilot'}, 'Record project_kind full or pilot')
    need(spec.get('mode','approved-clean') == 'approved-clean', 'original-ranges is not supported: approved audio equivalence not established')
    bindings = {'source':resolved(base,spec['source']['path']), 'ass':resolved(base,spec['captions']['path']),
                'preview':resolved(base,spec['preview']['path']), 'background':resolved(base,spec['background']['path']), 'timeline':path}
    for key, record in [('source',spec['source']),('ass',spec['captions']),('preview',spec['preview']),('background',spec['background'])]:
        need(bindings[key].is_file() and file_hash(bindings[key]) == record['sha256'], 'Input hash mismatch: '+key)
    errors = validate_report(approval, 'preview', bindings, project_config=project_config)
    need(not errors, 'Preview approval gate blocked: '+'; '.join(errors))
    source,fps,count = validate_media(spec['source'],base,ffprobe,True)
    background,bfps,bcount = validate_media(spec['background'],base,ffprobe)
    need((bfps,bcount) == (fps,count), 'Independent background must cover the full approved video at its fps')
    duration = frame_us(count,fps)
    preview_info=probe(bindings['preview'],ffprobe)
    pv=next((s for s in preview_info['streams'] if s['codec_type']=='video'),None)
    need(pv is not None and Fraction(pv['r_frame_rate'])==fps and Fraction(pv['avg_frame_rate'])==fps
         and int(pv.get('nb_read_frames',pv.get('nb_frames',-1)))==count, 'Approved preview full length/fps differs from source')
    need((pv['width'],pv['height'])==(spec['layout']['width'],spec['layout']['height']), 'Approved preview canvas differs from layout')
    need(audio_signature(source,ffprobe)==audio_signature(bindings['preview'],ffprobe),
         'Approved source/preview audio packets differ; do not rebuild with unverified audio')
    rows = caption_rows(bindings['ass'],spec['captions']['format'])
    for i,row in enumerate(rows):
        need(0 <= row['start'] < row['end'] <= duration and row['text'].strip(), 'Caption bounds/text invalid')
        need(i == 0 or rows[i-1]['end'] <= row['start'], 'Caption overlap/ordering invalid')
    cursor = 0
    for kept in spec['keep_ranges']:
        need(type(kept['start_frame']) is int and type(kept['end_frame']) is int, 'Use integer frame ranges')
        need(kept['start_frame'] == cursor and cursor < kept['end_frame'] <= count, 'Cuts must contiguously cover approved-clean output frames')
        cursor = kept['end_frame']
    need(cursor == count, 'Incomplete full-video cut coverage')
    layout = spec['layout']; W,H = layout['width'],layout['height']
    need(type(W) is int and type(H) is int and W>0 and H>0, 'Invalid canvas')
    p,m,c = layout['person'],layout['mask'],layout['caption']
    for obj,keys in [(p,['scale','center_x','center_y']),(m,['center_x','center_y','diameter']),(c,['center_x','center_y','size'])]:
        need(all(isinstance(obj[k],(int,float)) and math.isfinite(obj[k]) for k in keys), 'Non-finite layout')
    need(p['scale'] > 0 and c['size'] > 0 and m['shape'] == 'circle' and m['diameter']>0, 'Invalid scale/font/circle')
    sw,sh = spec['source']['width'],spec['source']['height']; radius=m['diameter']/2
    need(radius <= m['center_x'] <= sw-radius and radius <= m['center_y'] <= sh-radius, 'Circle crop lies outside source')
    if c.get('font_path'):
        need(resolved(base,c['font_path']).is_file(), 'Local font path missing; select an installed font')
    for record in spec.get('originals',[]):
        validate_media(record,base,ffprobe)
    return spec, bindings, rows, fps, count, duration


def material(path, record, duration):
    mid = uid()
    return dict(audio_fade=None,category_id='',category_name='local',check_flag=63487,
        crop={'upper_left_x':0.,'upper_left_y':0.,'upper_right_x':1.,'upper_right_y':0.,'lower_left_x':0.,'lower_left_y':1.,'lower_right_x':1.,'lower_right_y':1.},
        crop_ratio='free',crop_scale=1.,duration=duration,height=record['height'],width=record['width'],id=mid,material_id=mid,
        local_material_id=uid(),material_name=Path(path).name,media_path='',path=str(path),type='video')


def segment(mid, start, duration, render, source_start=0, volume=1., scale=1., x=0., y=0., text=False):
    speed_id=uid()
    s=dict(enable_adjust=True,enable_color_correct_adjust=False,enable_color_curves=True,
        enable_color_match_adjust=False,enable_color_wheels=True,enable_lut=True,enable_smart_color_adjust=False,
        last_nonzero_volume=volume,reverse=False,track_attribute=0,track_render_index=0,visible=True,id=uid(),material_id=mid,
        target_timerange=dict(start=start,duration=duration),common_keyframes=[],keyframe_refs=[],
        source_timerange=None if text else dict(start=source_start,duration=duration),speed=1.,volume=volume,
        extra_material_refs=[] if text else [speed_id],is_tone_modify=False,
        clip=dict(alpha=1.,flip=dict(horizontal=False,vertical=False),rotation=0.,scale=dict(x=scale,y=scale),transform=dict(x=x,y=y)),
        uniform_scale=dict(on=True,value=1.),render_index=render)
    if not text:
        s['hdr_settings']=dict(intensity=1.,mode=1,nits=1000)
    return s,dict(curve_speed=None,id=speed_id,mode=0,speed=1.,type='speed')


def track(name, kind, segments, mute=False):
    return dict(attribute=int(mute),flag=0,id=uid(),is_default_name=False,name=name,segments=segments,type=kind)


def freeze_workflow_evidence(workflow, report_base, destination):
    """Freeze authorization bytes for offline project checks, never for new production."""
    def freeze(reference, prefix):
        source=resolved(report_base,reference['path'])
        digest=file_hash(source)
        if reference.get('sha256') is not None:
            need(reference['sha256']==digest,'Workflow evidence changed during build')
        name=prefix+'-'+digest+source.suffix
        shutil.copy2(source,destination/'Evidence'/name)
        return {'path':'Evidence/'+name,'sha256':digest}
    auth_path=resolved(report_base,workflow['authorization']['path'])
    authorization=read(auth_path)
    user=authorization['user_authorization']['evidence']
    # The authorization remains byte-identical. Only this envelope relocates refs.
    evidence=dict(user,path=str(resolved(auth_path.parent,user['path'])))
    return {'mode':'full_auto','frozen_snapshot':True,
            'settings':freeze(workflow['settings'],'workflow-settings'),
            'authorization':freeze(workflow['authorization'],'workflow-authorization'),
            'user_evidence':freeze(evidence,'workflow-user-evidence')}


def build(timeline, approval_report, output, name, target_platform, registered_root=None, ffprobe=None, project_config=None):
    output=external_output(output)
    need(output.name.isascii(), 'Candidate directory name must be ASCII; display name may be Chinese')
    safe_name(name)
    need(target_platform in {'mac','windows'}, 'Select mac or windows')
    spec,bindings,rows,fps,count,duration=load_timeline(timeline,approval_report,ffprobe,project_config)
    caption_style=caption_style_record(spec['layout']['caption'],target_platform,Path(timeline).resolve().parent)
    registered=(Path(registered_root).expanduser().resolve()/name) if registered_root else output
    content=read(ASSETS/'draft_content_template.json');meta=read(ASSETS/'draft_meta_info.json')
    did=uid();now=int(time.time()*1e6);layout=spec['layout'];W,H=layout['width'],layout['height']
    content.update(id=did,name=name,duration=duration,fps=float(fps),create_time=now,update_time=now,
                   canvas_config=dict(width=W,height=H,ratio='original'))
    content['config']['maintrack_adsorb']=False
    # Template version is a migration hint, not the discovered application's version.
    for k in ['platform','last_modified_platform']:
        content[k]['os']='mac' if target_platform=='mac' else 'windows'
    filename='draft_info.json' if target_platform=='mac' else 'draft_content.json'
    resources=[];materials=[]
    for role,record in [('source',spec['source']),('background',spec['background'])]+[(f'original-{i}',r) for i,r in enumerate(spec.get('originals',[]))]:
        src=resolved(Path(timeline).resolve().parent,record['path'])
        newname=role+src.suffix.lower(); dest=registered/'Resources'/newname
        dur=frame_us(record['frame_count'],Fraction(str(record['fps'])))
        m=material(dest,record,dur);materials.append(m)
        resources.append(dict(role=role,file='Resources/'+newname,sha256=record['sha256'],bytes=src.stat().st_size,source=str(src)))
    src,bg=materials[:2];speeds=[];masks=[];person=[];cuts=[]
    b,sp=segment(bg['id'],0,duration,0,volume=0.);speeds.append(sp)
    pp,mm,cc=layout['person'],layout['mask'],layout['caption']
    for kept in spec['keep_ranges']:
        begin,end=frame_us(kept['start_frame'],fps),frame_us(kept['end_frame'],fps)
        s,sp=segment(src['id'],begin,end-begin,1,source_start=begin,scale=pp['scale'],
                     x=(pp['center_x']-W/2)/(W/2),y=(H/2-pp['center_y'])/(H/2))
        mask=dict(id=uid(),type='mask',category='video',category_id='',category_name='',name='圆形',platform='all',
                  position_info='',resource_type='circle',resource_id='6791700663249146381',
                  config=dict(aspectRatio=1.,centerX=(mm['center_x']-src['width']/2)/(src['width']/2),
                    centerY=(src['height']/2-mm['center_y'])/(src['height']/2),width=mm['diameter']/src['width'],height=mm['diameter']/src['height'],
                    invert=False,rotation=0.,feather=0.,roundCorner=0.))
        masks.append(mask);s['extra_material_refs'].append(mask['id']);s['enable_video_mask']=True
        speeds.append(sp);person.append(s);cuts.append(dict(segment_id=s['id'],**kept))
    texts=[];textsegments=[]
    font_path=str(resolved(Path(timeline).resolve().parent,cc['font_path'])) if cc.get('font_path') else ''
    for row in rows:
        mid=uid();style=dict(fill=dict(alpha=1.,content=dict(render_type='solid',solid=dict(alpha=1.,color=[1.,1.,1.]))),
            range=[0,len(row['text'])],size=cc['size'],bold=bool(cc.get('bold',False)),italic=False,underline=False,strokes=[],
            font=dict(id='',path=font_path),shadows=native_shadows(caption_style['shadow']))
        texts.append(dict(id=mid,content=json.dumps(dict(styles=[style],text=row['text']),ensure_ascii=False),typesetting=0,alignment=1,
                         letter_spacing=0.,line_spacing=.02,line_feed=0,line_max_width=1.,force_apply_line_max_width=False,check_flag=39,type='subtitle',global_alpha=1.))
        s,_=segment(mid,row['start'],row['end']-row['start'],2,text=True,x=(cc['center_x']-W/2)/(W/2),y=(H/2-cc['center_y'])/(H/2))
        textsegments.append(s)
    content['materials'].update(videos=materials,speeds=speeds,texts=texts,common_mask=masks)
    content['tracks']=[track('独立背景','video',[b],True),track('精剪源人物与批准原声','video',person),track('原生字幕','text',textsegments)]
    meta.update(draft_id=did,draft_name=name,draft_fold_path=str(registered),draft_root_path=str(registered.parent),
        draft_json_file=str(registered/filename),tm_duration=duration,tm_draft_create=now,tm_draft_modified=now)
    group=next(x for x in meta['draft_materials'] if x['type']==0)
    group['value']=[dict(id=m['local_material_id'],type=0,metetype='video',file_Path=m['path'],extra_info=m['material_name'],width=m['width'],height=m['height'],
        duration=m['duration'],create_time=0,import_time=0,import_time_ms=0,item_source=1,md5='',roughcut_time_range=dict(start=-1,duration=-1),sub_time_range=dict(start=-1,duration=-1)) for m in materials]
    manifest=dict(schema_version=1,status='STATIC_CANDIDATE_NATIVE_UI_PENDING',project_kind=spec['project_kind'],mode='approved-clean',
        editability='Native cuts reference approved clean footage; deleted footage has no timeline handles. Originals, if present, are library-only.',
        platform=target_platform,windows_ui_verified=False,native_ui_verified=False,profile_written=False,name=name,draft_id=did,content_file=filename,
        registered_path=str(registered),fps=str(fps),frame_count=count,duration_us=duration,captions=len(rows),person_segments=len(person),resources=resources,
        approval_bindings={k:file_hash(v) for k,v in bindings.items()},approval_report_sha256=file_hash(approval_report),
        audio='Approved-clean embedded audio, speed1 volume1; background muted, no new effects/fades',font='Local reference only; no font copied. UI glyph/style validation pending.',
        caption_style=caption_style, native_export='unverified',save_reopen='unverified',cross_computer='unverified')
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.native-build-',dir=output.parent))
    try:
        (temp/'Resources').mkdir();(temp/'Evidence').mkdir()
        for r in resources:
            shutil.copy2(r['source'],temp/r['file'])
            need(file_hash(temp/r['file'])==r['sha256'],'Copy hash changed')
        shutil.copy2(bindings['ass'],temp/'Evidence'/('captions.'+spec['captions']['format']))
        shutil.copy2(timeline,temp/'timeline.json');write(temp/'native-cut-map.json',cuts)
        shutil.copy2(approval_report,temp/'Evidence'/'approval-original.json')
        snapshots=[]
        for item in caption_style['calibration']['evidence']:
            origin=resolved(Path(timeline).resolve().parent,item['path'])
            need(file_hash(origin)==item['sha256'],'Calibration evidence changed during build')
            evidence_name='caption-calibration-'+item['sha256']+origin.suffix
            shutil.copy2(origin,temp/'Evidence'/evidence_name)
            snapshots.append({'source_path':item['path'],'path':'Evidence/'+evidence_name,'sha256':item['sha256']})
        caption_style['evidence_snapshots']=snapshots
        write(temp/filename,content);write(temp/'draft_meta_info.json',meta)
        write(temp/'generation-manifest.json',manifest)
        # Freeze evidence bytes, retaining references without inventing approvals.
        report=read(approval_report)
        for check in report.get('checks',{}).values():
            values=[]
            for i,value in enumerate(check.get('evidence',[])):
                origin=resolved(Path(approval_report).resolve().parent,value)
                evidence_name='evidence-'+file_hash(origin)+origin.suffix
                shutil.copy2(origin,temp/'Evidence'/evidence_name);values.append('Evidence/'+evidence_name)
            check['evidence']=values
        report_base=Path(approval_report).resolve().parent
        if report.get('workflow',{}).get('mode')=='full_auto':
            report['workflow']=freeze_workflow_evidence(report['workflow'],report_base,temp)
            ref=report['source_provenance']['edit_map']
            origin=resolved(report_base,ref['path'])
            need(file_hash(origin)==ref['sha256'],'Source provenance changed during build')
            evidence_name='edit-map-'+ref['sha256']+origin.suffix
            shutil.copy2(origin,temp/'Evidence'/evidence_name)
            ref['path']='Evidence/'+evidence_name
            for item in report['ai_review']['evidence']:
                origin=resolved(report_base,item['path'])
                need(file_hash(origin)==item['sha256'],'AI review evidence changed during build')
                evidence_name='ai-review-'+item['sha256']+origin.suffix
                shutil.copy2(origin,temp/'Evidence'/evidence_name);item['path']='Evidence/'+evidence_name
        else:
            origin=resolved(report_base,report['user_approval']['evidence'])
            evidence_name='approval-'+file_hash(origin)+origin.suffix
            shutil.copy2(origin,temp/'Evidence'/evidence_name);report['user_approval']['evidence']='Evidence/'+evidence_name
        write(temp/'approval-report.json',report)
        errors=validate(temp)['errors'];need(not errors,'Generated candidate invalid: '+'; '.join(errors))
        need(not output.exists(),'Output appeared during build; refusing overwrite')
        temp.rename(output)
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True);raise
    return manifest


def validate(project, native_report=None):
    root=Path(project).resolve();errors=[]
    try:
        manifest=read(root/'generation-manifest.json');content=read(root/manifest['content_file']);meta=read(root/'draft_meta_info.json')
        spec=read(root/'timeline.json');fps=Fraction(manifest['fps']);duration=frame_us(manifest['frame_count'],fps)
        need(file_hash(root/'timeline.json')==manifest['approval_bindings']['timeline'],'Timeline specification changed')
        need(file_hash(root/'Evidence'/'approval-original.json')==manifest['approval_report_sha256'],'Original approval evidence changed')
        need(content['duration']==duration==meta['tm_duration']==manifest['duration_us'],'Duration mismatch')
        need(content['fps']==float(fps),'FPS mismatch')
        need(content['id']==meta['draft_id']==manifest['draft_id'],'Draft ID mismatch')
        ids=[content['id']];lookup={}
        for key in ['videos','texts','speeds','common_mask']:
            for m in content['materials'][key]:
                ids.append(m['id']);lookup[m['id']]=m
                if key=='videos':ids.append(m['local_material_id'])
        for t in content['tracks']:
            ids.append(t['id'])
            for s in t['segments']:
                ids.append(s['id']);need(s['material_id'] in lookup,'Missing material')
                need(all(r in lookup for r in s['extra_material_refs']),'Dangling extra material ref')
                r=s['target_timerange'];need(0<=r['start']<r['start']+r['duration']<=duration,'Segment out of bounds')
        need(len(ids)==len(set(ids)),'Duplicate IDs')
        need(len(content['tracks'])==3,'Expected background/person/caption tracks')
        bg,person,texts=content['tracks'];cursor=0
        expected_caption_style=caption_style_record(spec['layout']['caption'],manifest['platform'],root,check_evidence=False)
        recorded_style=manifest.get('caption_style')
        if recorded_style is not None:
            need(all(recorded_style.get(k)==v for k,v in expected_caption_style.items()),'Caption style/calibration record changed')
            snapshots=recorded_style.get('evidence_snapshots',[])
            refs=expected_caption_style['calibration']['evidence']
            need(len(snapshots)==len(refs),'Calibration evidence snapshot incomplete')
            for original,snapshot in zip(refs,snapshots):
                need(snapshot.get('source_path')==original['path'] and snapshot.get('sha256')==original['sha256'],
                     'Calibration snapshot belongs to another profile')
                artifact=(root/snapshot['path']).resolve()
                need(artifact.is_relative_to(root/'Evidence') and artifact.is_file() and file_hash(artifact)==snapshot['sha256'],
                     'Calibration evidence snapshot missing or changed')
        else:
            need('shadow' not in spec['layout']['caption'] and 'style_profile' not in spec['layout']['caption'],
                 'Explicit caption style record missing')
        expected=spec['keep_ranges'];need(len(person['segments'])==len(expected)==manifest['person_segments'],'Cut count mismatch')
        source_mid=content['materials']['videos'][0]['id']
        for s,kept in zip(person['segments'],expected):
            begin,end=frame_us(kept['start_frame'],fps),frame_us(kept['end_frame'],fps)
            need(s['target_timerange']==dict(start=begin,duration=end-begin),'Cut mapping changed')
            need(begin==cursor and s['source_timerange']==s['target_timerange'],'Cut coverage/source mapping mismatch')
            need(s['material_id']==source_mid and s['speed']==1. and s['volume']==1.,'Approved voice configuration changed')
            maskrefs=[r for r in s['extra_material_refs'] if lookup[r].get('type')=='mask']
            need(s.get('enable_video_mask') and len(maskrefs)==1,'Native mask missing')
            W,H=spec['layout']['width'],spec['layout']['height'];pp=spec['layout']['person'];mm=spec['layout']['mask']
            need(s['clip']['scale']==dict(x=pp['scale'],y=pp['scale']) and s['clip']['transform']==dict(x=(pp['center_x']-W/2)/(W/2),y=(H/2-pp['center_y'])/(H/2)),'Person geometry changed')
            cfg=lookup[maskrefs[0]]['config'];sw,sh=spec['source']['width'],spec['source']['height']
            need(lookup[maskrefs[0]]['resource_type']=='circle' and cfg['width']==mm['diameter']/sw and cfg['height']==mm['diameter']/sh and cfg['centerX']==(mm['center_x']-sw/2)/(sw/2) and cfg['centerY']==(sh/2-mm['center_y'])/(sh/2),'Mask geometry changed')
            cursor=end
        need(cursor==duration,'Incomplete timeline')
        need(len(bg['segments'])==1 and bg['segments'][0]['target_timerange']==dict(start=0,duration=duration) and bg['segments'][0]['volume']==0.,'Background coverage/mute mismatch')
        capfile=root/'Evidence'/('captions.'+spec['captions']['format'])
        need(file_hash(capfile)==manifest['approval_bindings']['ass']==spec['captions']['sha256'],'Caption hash changed')
        rows=caption_rows(capfile,spec['captions']['format']);need(len(rows)==len(texts['segments'])==manifest['captions'],'Caption count changed')
        for row,s in zip(rows,texts['segments']):
            need(s['target_timerange']==dict(start=row['start'],duration=row['end']-row['start']),'Caption time changed')
            body=json.loads(lookup[s['material_id']]['content']);need(body['text']==row['text'],'Caption text changed')
            cc=spec['layout']['caption'];W,H=spec['layout']['width'],spec['layout']['height']
            need(s['clip']['transform']==dict(x=(cc['center_x']-W/2)/(W/2),y=(H/2-cc['center_y'])/(H/2)),'Caption position changed')
            need(len(body['styles'])==1 and body['styles'][0]['size']==cc['size'] and body['styles'][0]['strokes']==[],'Caption style changed')
            need(body['styles'][0].get('shadows')==native_shadows(expected_caption_style['shadow']),'Caption shadow changed')
        for r in manifest['resources']:
            p=(root/r['file']).resolve();need(p.is_relative_to(root) and p.is_file(),'Missing/escaping resource')
            need(file_hash(p)==r['sha256'],'Resource hash changed')
        source_resources=manifest['resources'][:2]
        need([r['role'] for r in source_resources]==['source','background'],'Resource roles invalid')
        for k,r in zip(['source','background'],source_resources):
            need(r['sha256']==manifest['approval_bindings'][k]==spec[k]['sha256'],'Source approval binding changed')
        need(len(content['materials']['videos'])==len(manifest['resources']),'Media count mismatch')
        registered=Path(manifest['registered_path'])
        for m,r in zip(content['materials']['videos'],manifest['resources']):
            need(m['path']==str(registered/r['file']),'Media reference differs from registered Resources')
        need(len(meta['draft_materials'][0]['value'])==len(manifest['resources']),'Media registry incomplete')
        report=read(root/'approval-report.json')
        need(report['stage']=='preview','Preceding preview report changed')
        need(all(report['artifacts'].get(k,{}).get('sha256')==v for k,v in manifest['approval_bindings'].items()),'Stored approval bindings changed')
        frozen_inputs={'source':root/manifest['resources'][0]['file'],'background':root/manifest['resources'][1]['file'],'ass':capfile}
        need(not validate_report(root/'approval-report.json','preview',frozen_inputs,live_config_required=report.get('workflow',{}).get('mode')!='full_auto'),'Frozen preview gate evidence invalid')
        if native_report:
            native_record=read(native_report)
            export_value=native_record.get('artifacts',{}).get('native_export',{}).get('path')
            need(export_value,'Native report requires native_export artifact path')
            errors.extend(validate_report(native_report,'jianying-project',{'project':root/manifest['content_file'],'manifest':root/'generation-manifest.json','native_export':resolved(Path(native_report).resolve().parent,export_value)}))
    except (OSError,ValueError,KeyError,TypeError,StopIteration,IndexError) as e:
        errors.append(str(e))
    return {'status':'blocked' if errors else 'STATIC_VALIDATED_NATIVE_UI_PENDING' if not native_report else 'RECORDED_NATIVE_GATE_PASSED',
            'errors':errors,'native_ui_verified':False if not native_report else not errors,
            'note':'Static validation is not UI, native export, or cross-device proof.'}


def _draft_fields(value, prefix='', depth=0):
    if depth > 8:
        return
    if isinstance(value,dict):
        for key,item in value.items():
            field=re.sub(r'(?<=[a-z0-9])(?=[A-Z])','_',str(key)).lower().replace('-','_')
            name=prefix+'.'+str(key) if prefix else str(key)
            if field in DRAFT_CONFIG_FIELDS:
                path=item.get('path') if isinstance(item,dict) else item
                if isinstance(path,str) and path.strip():
                    yield name,path
            if isinstance(item,(dict,list)):
                yield from _draft_fields(item,name,depth+1)
    elif isinstance(value,list):
        for index,item in enumerate(value[:1000]):
            yield from _draft_fields(item,prefix+'['+str(index)+']',depth+1)


def _config_draft_roots(files):
    roots=[];diagnostics=[];seen=set()
    for path,kind in files:
        path=Path(path).expanduser().resolve()
        if path in seen:continue
        seen.add(path)
        try:
            need(path.is_file(),'config file missing')
            need(path.stat().st_size<=MAX_CONFIG_BYTES,'config file exceeds bounded discovery size')
            raw=path.read_bytes()
            if raw.startswith((b'\xff\xfe',b'\xfe\xff')):
                text=raw.decode('utf-16')
            else:
                try:text=raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    if path.suffix.lower()!='.ini':raise
                    text=raw.decode('gb18030')
            if path.suffix.lower()=='.ini':
                parser=configparser.ConfigParser(interpolation=None,strict=False)
                parser.optionxform=str
                parser.read_string(text)
                values={'DEFAULT':dict(parser.defaults()),**{name:dict(parser.items(name)) for name in parser.sections()}}
            else:
                values=json.loads(text)
            for field,value in _draft_fields(values):
                value=re.sub(r'%([^%]+)%',lambda match:os.environ.get(match.group(1),match.group(0)),value)
                value=os.path.expandvars(value.strip())
                if len(value)>=2 and value[0]==value[-1] and value[0] in ('\"',"'"):
                    value=value[1:-1]
                need(not re.search(r'[\x00-\x1f]',value),'configured path has control characters')
                root=resolved(path.parent,value)
                marker=root/'root_meta_info.json'
                if root.is_dir() and marker.is_file():
                    roots.append({'path':str(root),'source':kind+' configuration field',
                                  'config_file':str(path),'config_field':field,'marker':str(marker),
                                  'write_authorized':False})
                else:
                    diagnostics.append({'config_file':str(path),'field':field,
                                        'reason':'configured directory or draft marker missing'})
        except (OSError,ValueError,TypeError,configparser.Error) as error:
            diagnostics.append({'config_file':str(path),'reason':str(error)})
    return roots,diagnostics


def discover(target_platform=None, app_path=None, draft_root=None, config_file=None):
    host='mac' if platform.system()=='Darwin' else 'windows' if platform.system()=='Windows' else platform.system().lower()
    chosen=target_platform or host;apps=[];roots=[]
    app_candidates=[Path(app_path).expanduser()] if app_path else []
    if chosen=='mac' and not app_path:
        app_candidates=[Path('/Applications')/n for n in ['VideoFusion-macOS.app','JianyingPro.app','CapCut.app']]
    if chosen=='windows' and not app_path and os.environ.get('LOCALAPPDATA'):
        app_candidates=list((Path(os.environ['LOCALAPPDATA'])/'JianyingPro'/'Apps').glob('*/JianyingPro.exe'))
    for app in app_candidates:
        if not app.exists():continue
        item={'path':str(app.resolve()),'version':'unknown','build':'unknown'}
        if chosen=='mac':
            info=app/'Contents'/'Info.plist'
            if info.is_file():
                with info.open('rb') as f: data=plistlib.load(f)
                item.update(version=data.get('CFBundleShortVersionString','unknown'),build=data.get('CFBundleVersion','unknown'),bundle_id=data.get('CFBundleIdentifier'))
        elif chosen=='windows' and host=='windows':
            # Parameter passed as env, never interpolated into PowerShell code.
            env=os.environ.copy();env['JY_DISCOVERY_APP']=str(app.resolve())
            try:
                v=subprocess.check_output(['powershell','-NoProfile','-Command','(Get-Item -LiteralPath $env:JY_DISCOVERY_APP).VersionInfo.FileVersion'],env=env,text=True,encoding='utf-8',errors='replace').strip()
                item['version']=v or 'unknown'
            except (OSError,subprocess.SubprocessError):pass
        apps.append(item)
    diagnostics=[]
    if draft_root:
        root=Path(draft_root).expanduser().resolve();need(root.is_dir(),'Explicit draft root does not exist')
        roots.append({'path':str(root),'source':'explicit override','write_authorized':False})
    else:
        bases=[]
        if chosen=='mac':bases=[Path.home()/'Movies'/n/'User Data' for n in ['JianyingPro','CapCut']]
        elif chosen=='windows' and os.environ.get('LOCALAPPDATA'):
            bases=[Path(os.environ['LOCALAPPDATA'])/n/'User Data' for n in ['JianyingPro','CapCut']]
        explicit=[] if config_file is None else list(config_file) if isinstance(config_file,(list,tuple)) else [config_file]
        files=[(Path(value),'explicit') for value in explicit]
        for base in bases:
            directory=base/'Config'
            if not directory.is_dir():continue
            found=sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in ('.json','.ini')),key=lambda path:path.name.lower())
            files.extend((path,'known User Data/Config') for path in found[:MAX_KNOWN_CONFIG_FILES])
            if len(found)>MAX_KNOWN_CONFIG_FILES:
                diagnostics.append({'config_directory':str(directory),'reason':'bounded scan limit reached'})
        configured,diagnostics_extra=_config_draft_roots(files)
        roots.extend(configured);diagnostics.extend(diagnostics_extra)
        candidates=[base/'Projects'/'com.lveditor.draft' for base in bases]
        known={os.path.normcase(str(Path(item['path']).resolve())) for item in roots}
        for root in candidates:
            if root.is_dir() and (root/'root_meta_info.json').is_file() and os.path.normcase(str(root.resolve())) not in known:
                roots.append({'path':str(root.resolve()),'source':'existing default directory and root marker; configuration paths take priority','write_authorized':False})
                known.add(os.path.normcase(str(root.resolve())))
        unique=[];seen=set()
        for item in roots:
            key=os.path.normcase(item['path'])
            if key not in seen:unique.append(item);seen.add(key)
        roots=unique
    return {'host':host,'target':chosen,'apps':apps,'draft_roots':roots,'ffprobe':shutil.which('ffprobe'),
            'native_ui_compatibility':'unverified','windows_ui_verified':False,'writes_performed':False,
            'config_diagnostics':diagnostics,
            'note':'Read-only bounded config discovery; explicit/known config fields take priority over default roots. No registration or UI recognition is claimed.'}


def relocate_plain(candidate, destination):
    manifest=read(candidate/'generation-manifest.json');content=read(candidate/manifest['content_file']);meta=read(candidate/'draft_meta_info.json')
    for m,r in zip(content['materials']['videos'],manifest['resources']):m['path']=str(destination/r['file'])
    for entry,m in zip(meta['draft_materials'][0]['value'],content['materials']['videos']):entry['file_Path']=m['path']
    meta.update(draft_fold_path=str(destination),draft_root_path=str(destination.parent),draft_json_file=str(destination/manifest['content_file']))
    manifest.update(registered_path=str(destination),profile_written=True,status='INSTALLED_NATIVE_UI_PENDING')
    write(candidate/manifest['content_file'],content);write(candidate/'draft_meta_info.json',meta);write(candidate/'generation-manifest.json',manifest)


def install(project,draft_root):
    project=Path(project).resolve();root=Path(draft_root).expanduser().resolve()
    need(root.is_dir(),'Explicit existing draft root required; no guessed root creation')
    report=validate(project);need(not report['errors'],'Candidate validation failed: '+'; '.join(report['errors']))
    manifest=read(project/'generation-manifest.json')
    need(manifest['project_kind']=='full','Pilot cannot be installed as a formal deliverable')
    host={'Darwin':'mac','Windows':'windows'}.get(platform.system())
    need(host is not None,'Native install requires a supported mac or windows host')
    need(manifest.get('platform')==host,'Candidate platform differs from this host; rebuild for the target platform, do not rename files')
    expected_content='draft_info.json' if host=='mac' else 'draft_content.json'
    need(manifest.get('content_file')==expected_content and (project/expected_content).is_file(),
         'Candidate main file does not match target platform')
    destination=root/safe_name(manifest['name']);need(not destination.exists(),'Name collision: refusing overwrite')
    need(not project.is_relative_to(root) and not root.is_relative_to(project),'Candidate must be external to live draft root')
    stage=Path(tempfile.mkdtemp(prefix='.new-native-',dir=root))
    try:
        shutil.copytree(project,stage,dirs_exist_ok=True);relocate_plain(stage,destination)
        need(not validate(stage)['errors'],'Installed staging validation failed')
        need(not destination.exists(),'Destination appeared; refusing overwrite')
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True);raise
    return {'status':'INSTALLED_NATIVE_UI_PENDING','path':str(destination),'global_index_written':False,'existing_projects_changed':False,'windows_ui_verified':False}


def tree_hashes(root, exclude_fonts=False):
    records={}
    for p in sorted(root.rglob('*')):
        need(not p.is_symlink(),'Symlinks prohibited in project copy')
        if p.is_file() and not(exclude_fonts and p.suffix.lower() in FONT_SUFFIXES):records[str(p.relative_to(root))]=file_hash(p)
    return records


def snapshot(project,output,saved_and_closed=False):
    need(saved_and_closed,'Save and close project before snapshot; do not copy actively edited drafts')
    project=Path(project).resolve();output=external_output(output)
    need(project.is_dir() and not output.is_relative_to(project),'Invalid project snapshot source/destination')
    need((project/'draft_info.json').is_file() or (project/'draft_content.json').is_file(),'Not a native draft folder')
    # No JSON parsing/rewriting: saved drafts and Timelines may be opaque.
    before=tree_hashes(project,True);allfiles=tree_hashes(project)
    output.parent.mkdir(parents=True,exist_ok=True);temp=Path(tempfile.mkdtemp(prefix='.snapshot-',dir=output.parent))
    try:
        for name in before:
            dest=temp/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(project/name,dest)
        need(tree_hashes(project,True)==before,'Source changed during snapshot; save/close then retry')
        need(tree_hashes(temp)==before,'Snapshot bytes differ')
        report={'status':'BYTE_SNAPSHOT_NATIVE_COMPATIBILITY_UNVERIFIED','files':before,'excluded_fonts':sorted(set(allfiles)-set(before)),
                'opaque_files_rewritten':False,'system_fonts_distributed':False,'cross_device':'unverified',
                'path_limit':'Native opaque references unchanged; move/cross-device may require UI relink or regeneration from neutral timeline.'}
        report_file='snapshot-integrity-'+uid()+'.json'
        write(temp/report_file,report);need(not output.exists(),'Snapshot output collision');temp.rename(output)
        report['integrity_report']=str(output/report_file)
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True);raise
    return report


def main(argv=None):
    # Deterministic UTF-8 JSON when Windows redirects stdout using a legacy code page.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    d=sub.add_parser('discover');d.add_argument('--platform',choices=['mac','windows']);d.add_argument('--app-path');d.add_argument('--draft-root');d.add_argument('--config-file',action='append',help='explicit small JSON/INI containing actual draft path fields')
    b=sub.add_parser('build')
    for flag in ['timeline','approval-report','output','name']:b.add_argument('--'+flag)
    b.add_argument('--platform',choices=['mac','windows']);b.add_argument('--registered-root');b.add_argument('--ffprobe')
    v=sub.add_parser('validate');v.add_argument('--project',required=True);v.add_argument('--report');v.add_argument('--native-report')
    i=sub.add_parser('install');i.add_argument('--project',required=True);i.add_argument('--draft-root',required=True)
    s=sub.add_parser('snapshot');s.add_argument('--project',required=True);s.add_argument('--output',required=True);s.add_argument('--saved-and-closed',action='store_true')
    for p in [d,b,v,i,s]:p.add_argument('--project-config')
    args=parser.parse_args(argv)
    try:
        config=read(args.project_config) if args.project_config else {}
        if args.command=='build':
            # Optional config does not authorize any mutation; explicit command does.
            defaults=config.get('jianying',config)
            for field in ['timeline','approval_report','output','name','platform','registered_root','ffprobe']:
                if getattr(args,field,None) is None:setattr(args,field,defaults.get(field))
            need(all(getattr(args,x,None) for x in ['timeline','approval_report','output','name','platform']), 'Build requires timeline, approval_report, output, name, platform')
            result=build(args.timeline,args.approval_report,args.output,args.name,args.platform,args.registered_root,args.ffprobe,project_config=args.project_config)
        elif args.command=='discover':result=discover(args.platform,args.app_path,args.draft_root,args.config_file)
        elif args.command=='validate':
            result=validate(args.project,args.native_report)
            if args.report:
                out=external_output(args.report);out.parent.mkdir(parents=True,exist_ok=True);write(out,result)
        elif args.command=='install':result=install(args.project,args.draft_root)
        else:result=snapshot(args.project,args.output,args.saved_and_closed)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if result.get('errors') else 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        print(json.dumps({'status':'blocked','errors':[str(error)]},ensure_ascii=False));return 2


if __name__=='__main__':
    raise SystemExit(main())
