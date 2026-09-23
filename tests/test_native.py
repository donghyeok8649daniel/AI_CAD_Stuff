from copy import deepcopy
import json
import math
import httpx
import pytest
from cadstudio.native import geometry as G
from cadstudio.native.document import Document,read_project
from cadstudio.native.local_ai import ollama_draft
from cadstudio.catalog import preset
from cadstudio.models import Extrusion,DraftRequest,Design,Part
from cadstudio.kernel import construct
from cadstudio.sketch_engine import sketch_status

@pytest.mark.parametrize('tool,points,options',[
 ('rectangle',[(-20,-10),(20,10)],{}),('center-rectangle',[(0,0),(20,10)],{}),('rectangle-3',[(0,0),(20,0),(20,10)],{}),('circle',[(0,0),(10,0)],{}),('circle-2',[(-10,0),(10,0)],{}),('circle-3',[(-10,0),(0,10),(10,0)],{}),('ellipse',[(0,0),(20,0),(0,10)],{}),('polygon',[(0,0),(20,0)],{'count':6}),('polygon-inscribed',[(0,0),(20,0)],{'count':5}),('slot',[(-10,0),(10,0),(10,5)],{}),('center-slot',[(0,0),(10,0),(10,5)],{}),('spline-fit',[(0,0),(20,0),(10,20)],{'closed':True}),('spline-control',[(0,0),(20,0),(20,20),(0,20)],{'closed':True})])
def test_native_tools_produce_exact_valid_solids(tool,points,options):
    entities=G.create(tool,[G.pt(*p) for p in points],options);g=Extrusion(sketch_mode='entities',entities=entities);s=construct(g);assert s.isValid() and s.Volume()>0

def test_native_intersection_trim_and_arc_orientation():
    c=G.circle(G.pt(0,0),10);l=G.line(G.pt(0,-20),G.pt(0,20));hits=G.intersections(c,l);assert len(hits)==2
    out=G.trim(c,[l],G.pt(10,0));assert len(out)==1 and abs(out[0]['sweep'])==pytest.approx(180)
    mirrored=G.transform(out[0],axis=G.line(G.pt(0,0),G.pt(1,0)));assert mirrored['sweep']==-out[0]['sweep']
    assert G.dist(G.at(mirrored,.5),G.pt(G.at(out[0],.5)['x'],-G.at(out[0],.5)['y']))<1e-8

def test_native_offset_and_fillet_keep_closed_boundary():
    rect=G.create('rectangle',[G.pt(-20,-10),G.pt(20,10)]);off=G.offset(rect,-2);g=Extrusion(sketch_mode='entities',entities=off);assert construct(g).Volume()==pytest.approx(44*24*8)
    corner=G.corner(rect[0],rect[1],3,True);g=Extrusion(sketch_mode='entities',entities=corner+rect[2:]);assert construct(g).isValid()

def test_native_origin_and_diameter_are_fully_constrained():
    g=Extrusion(sketch_mode='entities',entities=[G.circle(G.pt(2,3),10)],entity_constraints=[]);id=g.entities[0].id;raw=g.model_dump();raw['entity_constraints']=[dict(id='origin',kind='fixed',a=id,a_point='center',x=0,y=0),dict(id='size',kind='diameter',a=id,value=24)];solved=Extrusion.model_validate(raw);assert sketch_status(solved)['dof']==0;assert solved.entities[0].radius==pytest.approx(12);assert solved.entities[0].center.x==pytest.approx(0,abs=1e-6)

def test_native_history_branches_survive_disk(tmp_path):
    d=Document();base=preset('cylinder');d.commit(base,'start');root=d.journal.data['cursor'];raw=base.model_dump();raw['parts'][0]['geometry']['height']=35;d.commit(Design.model_validate(raw),'height');abandoned=d.journal.data['cursor'];d.commit(d.journal.at(root),'undo',cursor=root);raw=base.model_dump();raw['parts'][0]['geometry']['diameter']=22;d.commit(Design.model_validate(raw),'branch');path=tmp_path/'native.cad.json';d.write(path);p=read_project(path);assert len(p.history.entries)==3;assert d.journal.at(abandoned)['parts'][0]['geometry']['height']==35;other=Document();other.load(p,path);assert other.design==d.design

def test_ollama_fixed_loopback_and_structured_response():
    response={'design':preset('cylinder').model_dump(),'summary':'Cylinder','assumptions':[]};requests=[]
    def handle(request):
        requests.append(request);return httpx.Response(200,json={'done':True,'message':{'content':json.dumps(response)}})
    result=ollama_draft(DraftRequest(prompt='원통 직경 30'), 'test-local',httpx.MockTransport(handle));assert result['provider']=='ollama';assert str(requests[0].url)=='http://127.0.0.1:11434/api/chat';payload=json.loads(requests[0].content);assert payload['format']['type']=='object' and payload['stream'] is True;assert 'authorization' not in requests[0].headers

def test_ollama_invalid_design_has_one_repair_limit():
    requests=[]
    def handle(request):requests.append(request);return httpx.Response(200,json={'done':True,'message':{'content':'{"exec":"not allowed"}'}})
    with pytest.raises(ValueError,match='두 차례'):ollama_draft(DraftRequest(prompt='test'),'test-local',httpx.MockTransport(handle))
    assert len(requests)==2

def test_ollama_does_not_follow_remote_redirect():
    requests=[]
    def handle(request):requests.append(request);return httpx.Response(307,headers={'location':'https://example.com'})
    with pytest.raises(ValueError,match='요청에 실패'):ollama_draft(DraftRequest(prompt='test'),'test-local',httpx.MockTransport(handle))
    assert len(requests)==1


def test_qwen3_skips_thinking_for_cad_output():
    def handle(request):
        body=json.loads(request.content);assert body['think'] is False
        return httpx.Response(200,json={'done':True,'message':{'content':json.dumps({'design':preset('cylinder').model_dump(),'summary':'OK','assumptions':[]})}})
    ollama_draft(DraftRequest(prompt='Cylinder'),'qwen3:8b',httpx.MockTransport(handle))
