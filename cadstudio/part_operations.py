"""Transactional selection folders and portable part clipboard snapshots."""
from copy import deepcopy
from uuid import uuid4
from .models import Design
from .parameters import remove_bindings
from .assembly_motion import prune_joint_references


def uid(prefix):return prefix+'-'+uuid4().hex


def group_parts(raw,ids,name=None):
    data=deepcopy(raw);ids=[p['id'] for p in data['parts'] if p['id'] in set(ids)]
    if len(ids)<2:raise ValueError('그룹으로 묶을 부품을 두 개 이상 선택하세요. Shift+클릭 또는 범위 선택 B를 사용하세요.')
    groups=[]
    for group in data.get('part_groups',[]):
        group['part_ids']=[i for i in group['part_ids'] if i not in ids]
        if group['part_ids']:groups.append(group)
    group=dict(id=uid('group'),name=(name or f'부품 그룹 {len(groups)+1}').strip()[:80],part_ids=ids)
    data['part_groups']=[*groups,group]
    return data,group['id']


def ungroup_parts(raw,ids):
    data=deepcopy(raw);data['part_groups']=[g for g in data.get('part_groups',[]) if not set(ids).intersection(g['part_ids'])]
    return data


def walk(node):
    if isinstance(node,dict):
        yield node
        for value in node.values():yield from walk(value)
    elif isinstance(node,list):
        for value in node:yield from walk(value)


def part_clipboard(raw,ids):
    # Validation resolves parameters and linked copies before taking the snapshot.
    data=Design.model_validate(raw).model_dump();ids=set(ids)
    parts=[p for p in data['parts'] if p['id'] in ids]
    if not parts:raise ValueError('복사할 부품을 먼저 선택하세요.')
    ids={p['id'] for p in parts};sketch_ids=set();asset_ids=set()
    for p in parts:
        if p.get('source_part_id') not in ids:p.pop('source_part_id',None)
        for node in walk(p):
            if node.get('tool_part_id') and node['tool_part_id'] not in ids:
                raise ValueError('몸체 연산의 도구 부품도 함께 선택한 뒤 복사하세요: '+node['tool_part_id'])
            for key in ('sketch_id','profile_sketch_id'):
                if node.get(key):sketch_ids.add(node[key])
            if node.get('asset_id'):asset_ids.add(node['asset_id'])
    sketches=[s for s in data['sketches'] if s['id'] in sketch_ids]
    for s in sketches:
        support=s['context'].get('part_id')
        if support and support not in ids:
            # Freeze an external face support in world coordinates.
            freeze_support(data,s)
    mates=[m for m in data['mates'] if {m['parent'],m['child']}<=ids];mids={m['id'] for m in mates}
    payload=dict(name='복사한 부품',parts=parts,sketches=sketches,mates=mates,
        joint_frames=[f for f in data['joint_frames'] if f['mate_id'] in mids],
        loops=[c for c in data['loops'] if {c['parent'],c['child']}<=ids and set(c['passive_joints'])<=mids],
        motion_links=[m for m in data.get('motion_links',[]) if m['driver'] in mids and m['driven'] in mids],
        assets={i:data['assets'][i] for i in asset_ids},
        part_groups=[dict(g,part_ids=[i for i in g['part_ids'] if i in ids]) for g in data.get('part_groups',[]) if ids.intersection(g['part_ids'])])
    for node in walk(payload):
        node.pop('expression',None);node.pop('thickness_expression',None)
    return Design.model_validate(payload).model_dump()


def freeze_support(data,sketch):
    from .native.saved_sketches import sketch_frame
    import numpy as np
    model=Design.model_validate(data);saved=next(s for s in model.sketches if s.id==sketch['id'])
    origin,x,y=sketch_frame(model,saved)
    sketch['context']=dict(plane='XY',title=sketch['name'],face=dict(index=0,planar=True,origin=origin.tolist(),x_direction=x.tolist(),normal=np.cross(x,y).tolist(),face_count=1))


def paste_parts(raw,payload,offset=30):
    source=Design.model_validate(payload).model_dump();data=deepcopy(raw or Design().model_dump())
    ids={p['id']:uid('part') for p in source['parts']};sids={s['id']:uid('sketch') for s in source['sketches']}
    mids={m['id']:uid('mate') for m in source['mates']};aids={a:uid('asset') for a in source.get('assets',{})}
    children={m['child'] for m in source['mates']}
    for p in source['parts']:
        old=p['id'];p['id']=ids[old];p['name']=(p['name']+' 복사')[:80]
        if old not in children:p['transform']['x']+=offset
        for node in walk(p):
            for key,index in (('source_part_id',ids),('tool_part_id',ids),('sketch_id',sids),('profile_sketch_id',sids),('asset_id',aids)):
                if node.get(key):node[key]=index[node[key]]
    for s in source['sketches']:
        s['id']=sids[s['id']];ctx=s['context']
        if ctx.get('part_id'):ctx['part_id']=ids[ctx['part_id']]
        # Unattached sketches retain their profile coordinates. Advanced profile
        # frames are resolved relative to the copied body's new placement.
        else:
            if not ctx.get('face'):
                from .native.saved_sketches import sketch_frame
                import numpy as np
                model=Design.model_validate(payload);old=next(k for k,v in sids.items() if v==s['id']);saved=next(v for v in model.sketches if v.id==old)
                origin,x,y=sketch_frame(model,saved);ctx['face']=dict(index=0,planar=True,origin=origin.tolist(),normal=np.cross(x,y).tolist(),x_direction=x.tolist(),face_count=1)
            ctx['face']['origin'][0]+=offset
    for m in source['mates']:m['id']=mids[m['id']];m['parent']=ids[m['parent']];m['child']=ids[m['child']]
    for f in source['joint_frames']:f['mate_id']=mids[f['mate_id']]
    for c in source['loops']:c['id']=uid('loop');c['parent']=ids[c['parent']];c['child']=ids[c['child']];c['passive_joints']=[mids[i] for i in c['passive_joints']]
    for m in source.get('motion_links',[]):m['id']=uid('motion');m['driver']=mids[m['driver']];m['driven']=mids[m['driven']]
    for g in source.get('part_groups',[]):g['id']=uid('group');g['part_ids']=[ids[i] for i in g['part_ids']]
    for key in ('parts','sketches','mates','joint_frames','loops','motion_links','part_groups'):data.setdefault(key,[]).extend(source.get(key,[]))
    data.setdefault('assets',{}).update({aids[k]:v for k,v in source.get('assets',{}).items()})
    return data,list(ids.values())


def delete_parts(raw,ids):
    data=Design.model_validate(raw).model_dump();ids=set(ids)
    for p in data['parts']:
        if p['id'] in ids:continue
        if p.get('source_part_id') in ids:p.pop('source_part_id')
        if any(n.get('tool_part_id') in ids for n in walk(p)):
            raise ValueError('선택 부품을 참조하는 몸체 연산이 있습니다. 해당 피처를 먼저 제거하거나 종속 부품도 함께 선택하세요: '+p['name'])
    for s in data['sketches']:
        if s['context'].get('part_id') in ids:freeze_support(data,s)
    data['parts']=[p for p in data['parts'] if p['id'] not in ids]
    data['mates']=[m for m in data['mates'] if not ids.intersection((m['parent'],m['child']))];mids={m['id'] for m in data['mates']}
    data['joint_frames']=[f for f in data['joint_frames'] if f['mate_id'] in mids]
    data['loops']=[c for c in data['loops'] if not ids.intersection((c['parent'],c['child'])) and set(c['passive_joints'])<=mids]
    for g in data.get('part_groups',[]):g['part_ids']=[i for i in g['part_ids'] if i not in ids]
    data['part_groups']=[g for g in data.get('part_groups',[]) if g['part_ids']]
    for i in ids:remove_bindings(data,['parts',i])
    prune_joint_references(data)
    return data


def duplicate_parts(raw,ids):
    """In-document Ctrl+D retains parameter bindings, unlike portable clipboard."""
    payload=part_clipboard(raw,ids);data,new=paste_parts(raw,payload)
    maps={'parts':dict(zip([p['id'] for p in payload['parts']],new)),
          'sketches':dict(zip([s['id'] for s in payload['sketches']],[s['id'] for s in data['sketches'][len(raw.get('sketches',[])):]]))}
    def expressions(old,copy):
        if isinstance(old,dict) and isinstance(copy,dict):
            for key,value in old.items():
                if key in ('expression','thickness_expression'):copy[key]=value
                elif key in copy:expressions(value,copy[key])
        elif isinstance(old,list) and isinstance(copy,list):
            for a,b in zip(old,copy):expressions(a,b)
    for scope,mapping in maps.items():
        for old_id,new_id in mapping.items():
            old=next(p for p in raw[scope] if p['id']==old_id);copy=next(p for p in data[scope] if p['id']==new_id);expressions(old,copy)
    for binding in raw.get('dimension_bindings',[]):
        scope,identifier,*tail=binding['path'];mapping=maps.get(scope,{})
        if identifier in mapping:data.setdefault('dimension_bindings',[]).append(dict(binding,path=[scope,mapping[identifier],*tail]))
    return data,new
