"""Sketch clipboard with internal geometric constraints and independent anchors."""
import json
from copy import deepcopy
from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QApplication
from ..models import Extrusion
from . import geometry as G

MIME='application/x-promptcad-sketch-v1'


class SketchClipboard:
    def copy_selection(self,cut=False):
        entities=self.chosen();ids={e['id'] for e in entities}
        if not ids:self.error('복사할 스케치 요소를 선택하세요.');return
        constraints=[c for c in self.g['entity_constraints'] if c['a'] in ids and all(not c.get(k) or c[k] in ids for k in ('b','c')) and c['kind']!='fixed' and not (c['kind'] in ('dx','dy','distance','coincident','point_on') and not c.get('b'))]
        groups=[dict(g,entity_ids=[i for i in g['entity_ids'] if i in ids]) for g in self.g.get('groups',[]) if ids.intersection(g['entity_ids'])]
        payload=dict(kind='extrusion',sketch_mode='entities',entities=entities,entity_constraints=constraints,groups=groups)
        payload=deepcopy(payload)
        for c in payload['entity_constraints']:c.pop('expression',None)
        mime=QMimeData();mime.setData(MIME,json.dumps(payload).encode());mime.setText(f'Prompt CAD Studio · 스케치 요소 {len(ids)}개');QApplication.clipboard().setMimeData(mime);self.clipboard_pastes=0
        if cut:self.delete_selected()
        else:self.status.setText(f'{len(ids)}개 요소 복사 · 고정/외부 구속은 제외하고 내부 구속 유지')

    def paste_selection(self):
        mime=QApplication.clipboard().mimeData()
        if not mime or not mime.hasFormat(MIME):self.error('복사한 스케치 요소가 없습니다.');return
        try:
            encoded=bytes(mime.data(MIME))
            if len(encoded)>2_000_000:raise ValueError('복사 데이터가 너무 큽니다.')
            g=Extrusion.model_validate(json.loads(encoded)).model_dump();ids={e['id']:G.uid() for e in g['entities']};count=getattr(self,'clipboard_pastes',0)+1
            entities=[]
            for e in g['entities']:
                e=G.transform(e,dx=count*10,dy=count*10);e['id']=ids[e['id']];entities.append(e)
            for c in g['entity_constraints']:
                c['id']=G.uid()
                for key in ('a','b','c'):
                    if c.get(key):c[key]=ids[c[key]]
            for group in g.get('groups',[]):group['id']='group-'+G.uid();group['entity_ids']=[ids[i] for i in group['entity_ids']]
            def apply():
                self.g['entities'].extend(entities);self.g['entity_constraints'].extend(g['entity_constraints']);self.g.setdefault('groups',[]).extend(g.get('groups',[]));self.selected=set(ids.values());self.selection_refs=[]
            self.mutate('스케치 붙여넣기',apply);self.clipboard_pastes=count
        except Exception as exc:self.error(str(exc))
