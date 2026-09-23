"""Stable entity membership; profile indices are resolved after every solve."""
def group_regions(regions,entity_ids):
    ids=set(entity_ids)
    candidates=[r for r in regions if r.get('entity_ids') and set(r['entity_ids'])<=ids]
    # Keep voids in nested loops. Disconnected islands remain separate profiles.
    return [r['index'] for r in candidates if not any(set(r['entity_ids'])<set(other['entity_ids']) for other in candidates)]


def prune_groups(geometry):
    ids={e['id'] for e in geometry['entities']}
    groups=[]
    for group in geometry.get('groups',[]):
        members=[i for i in group['entity_ids'] if i in ids]
        if members:groups.append({**group,'entity_ids':members})
    if groups:geometry['groups']=groups
    else:geometry.pop('groups',None)
