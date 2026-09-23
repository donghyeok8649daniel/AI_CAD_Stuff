"""Shared profiles have one owner; feature depth and region choice stay local."""
from copy import deepcopy

PROFILE_KEYS=('sketch_mode','points','holes','constraints','entities','entity_constraints','groups')


def copy_profile(target,source):
    for key in PROFILE_KEYS:
        if key in source:target[key]=deepcopy(source[key])
        else:target.pop(key,None)


def resolve_profiles(raw):
    if not isinstance(raw,dict):return raw
    raw=deepcopy(raw)
    for key in ('parts','sketches'):
        if not isinstance(raw.get(key,[]),list):raise ValueError('부품과 스케치는 목록이어야 합니다.')
        raw[key]=[x.model_dump() if hasattr(x,'model_dump') else x for x in raw.get(key,[])]
        if any(not isinstance(x,dict) or 'id' not in x or 'geometry' not in x for x in raw[key]):return raw
    for part in raw['parts']:
        features=part.get('features',[])
        if not isinstance(features,list):return raw
        part['features']=[f.model_dump() if hasattr(f,'model_dump') else f for f in features]
        if any(not isinstance(f,dict) for f in part['features']):return raw
    sketches={s['id']:s for s in raw.get('sketches',[])}
    for part in raw.get('parts',[]):
        links=[(part.get('profile_sketch_id'),part['geometry'])]
        links.extend((f.get('sketch_id'),f.get('sketch')) for f in part.get('features',[]))
        for identifier,g in links:
            if not identifier:continue
            if identifier not in sketches:raise ValueError('연결된 원본 스케치를 찾을 수 없습니다: '+identifier)
            if not isinstance(g,dict) or g.get('kind')!='extrusion':raise ValueError('프로파일 연결은 스케치 돌출에만 적용할 수 있습니다.')
            copy_profile(g,sketches[identifier]['geometry'])
    parts={p['id']:p for p in raw.get('parts',[])};done=set();visiting=set()
    def instance(identifier):
        if identifier in done:return
        if identifier in visiting:raise ValueError('연결 복제 부품에 순환 참조가 있습니다.')
        visiting.add(identifier);part=parts[identifier];source=part.get('source_part_id')
        if source:
            if source not in parts:raise ValueError('연결 복제의 원본 부품이 없습니다: '+source)
            instance(source)
            for key in ('geometry','features','profile_sketch_id'):
                if key in parts[source]:part[key]=deepcopy(parts[source][key])
                else:part.pop(key,None)
        visiting.remove(identifier);done.add(identifier)
    for identifier in parts:instance(identifier)
    return raw


def edit_source(raw,identifier,geometry):
    if not identifier:return
    saved=next((s for s in raw.get('sketches',[]) if s['id']==identifier),None)
    if saved is None:raise ValueError('편집할 연결 스케치를 찾을 수 없습니다.')
    copy_profile(saved['geometry'],geometry)
