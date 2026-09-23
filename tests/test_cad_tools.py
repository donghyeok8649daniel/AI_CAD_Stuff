from ai_transport import cad_transport
import asyncio,json,math,threading
import httpx
import pytest
from cadstudio.models import DraftRequest,Design,Part
from cadstudio.kernel import build,exact_bounds
from cadstudio.native.cad_tools import execute_plan,CADPlan
from cadstudio.native.local_ai import ollama_draft,DraftControl,DraftCancelled


def action(tool,target='part',**args):return dict(tool=tool,target=target,args=args)
def create(kind='plate',target='part',**geometry):
    values=dict(length=80,width=50,thickness=25) if kind=='plate' else dict(diameter=60,height=20,bore_diameter=5)
    return action('create',target,name=target,geometry=dict(kind=kind,**{**values,**geometry}))
def plan(*actions):return dict(name='Test',summary='CAD plan',assumptions=[],actions=list(actions))
def execute(*actions,current=None):return execute_plan(json.dumps(plan(*actions)),DraftRequest(prompt='설계',current=current))
def response(data):return httpx.Response(200,json={'done':True,'message':{'content':json.dumps(data)}})


def test_same_small_plan_schema_for_arbitrary_objects_and_actual_exact_solids():
    def handle(request):
        data=json.loads(request.content)
        assert len(json.dumps(data['format']))<22000 and data['options']['num_ctx']==8192
        alternatives=data['format']['properties']['actions']['items']['anyOf']
        pad=next(s for s in alternatives if s['properties']['tool']['const']=='pad')
        assert {'face','profile','depth'}<=set(pad['properties']['args']['required'])
        return response(plan(create('cylinder',diameter=80,height=12,bore_diameter=8)))
    result=ollama_draft(DraftRequest(prompt='바퀴'),'test',cad_transport(handle),deadline=None)
    shape=build(Design.model_validate(result['design']))[0]
    assert shape.Volume()==pytest.approx(math.pi*(40**2-4**2)*12)
    assert result['tool_actions'][0]['validated'] and '부품 생성' in result['changes'][0]


def test_open_box_shell_matches_analytical_volume_and_preserves_feature_reference():
    reply=execute(create(),action('shell',thickness=2,open_faces=['+Z']))
    shape=build(reply.design)[0]
    assert shape.Volume()==pytest.approx(80*50*25-76*46*23)
    feature=reply.design.parts[0].features[0]
    assert feature.faces[0].normal==[0,0,1] and feature.support_feature=='base'


def test_single_part_plan_compiles_one_base_and_features_with_individual_history():
    data=dict(summary='hollow part',base=create(),actions=[action('shell',thickness=2,open_faces=['+Z'])])
    reply=execute_plan(json.dumps(data),DraftRequest(prompt='single hollow part'),single_part=True)
    assert len(reply.design.parts)==1 and build(reply.design)[0].Volume()==pytest.approx(19592)
    assert [a['tool'] for a in reply.tool_actions]==['create','shell'] and len(reply.journal_steps)==2
    with pytest.raises(ValueError,match='SAME base'):
        execute_plan(json.dumps({**data,'actions':[create(target='wall')]}),DraftRequest(prompt='one part'),single_part=True)
    with pytest.raises(ValueError,match='ONE base'):
        execute_plan(json.dumps(plan(create(),create(target='wall'))),DraftRequest(prompt='one part'),single_part=True)
    with pytest.raises(ValueError,match='disconnected solids'):
        execute_plan(json.dumps({**data,'actions':[action('solid',operation='linear_pattern',count=2,spacing=[100,0,0])]}),DraftRequest(prompt='one part'),single_part=True)


def test_hole_pattern_and_counterbore_remove_correct_volumes():
    reply=execute(create(thickness=5),action('hole',face='+Z',diameter=5,centers=[[-30,-15],[30,-15],[-30,15],[30,15]]))
    assert build(reply.design)[0].Volume()==pytest.approx(80*50*5-4*math.pi*2.5**2*5)
    reply=execute(create(),action('hole',face='+Z',diameter=6,finish='counterbore',head_diameter=12,head_depth=3))
    assert build(reply.design)[0].Volume()==pytest.approx(80*50*25-math.pi*3**2*25-math.pi*(6**2-3**2)*3)


def test_dimensioned_hole_patterns_compute_exact_positions_and_volumes():
    from cadstudio.native.cad_tools import hole_centers
    pattern=dict(kind='rectangular',count_x=2,count_y=2,spacing_x=60,spacing_y=40)
    assert hole_centers(dict(pattern=pattern))==[[-30,-20],[30,-20],[-30,20],[30,20]]
    reply=execute(create(width=60,thickness=5),action('hole',face='+Z',diameter=5,pattern=pattern))
    assert build(reply.design)[0].Volume()==pytest.approx(24000-4*math.pi*2.5**2*5)
    circular=dict(kind='circular',count=6,diameter=40,start_angle=30)
    reply=execute(create('cylinder',diameter=60,height=5,bore_diameter=0),action('hole',face='+Z',diameter=4,pattern=circular))
    assert build(reply.design)[0].Volume()==pytest.approx(math.pi*30**2*5-6*math.pi*2**2*5)
    for bad in (dict(pattern=pattern,centers=[[0,0]]),dict(pattern={**pattern,'count_x':32}),dict(pattern={**circular,'diameter':float('nan')})):
        with pytest.raises(ValueError):hole_centers(bad)


def test_current_context_keeps_default_dimensions_for_editing():
    from cadstudio.native.cad_tools import context
    current=Design(parts=[Part(id='part',name='default',geometry={'kind':'cylinder'})])
    geometry=context(current)['parts'][0]['geometry']
    assert geometry['diameter']==current.parts[0].geometry.diameter
    assert geometry['height']==current.parts[0].geometry.height and geometry['kind']=='cylinder'


def test_expected_measurements_reject_valid_but_wrong_solid_transactionally():
    data=plan(create('cylinder',diameter=20,height=30,bore_diameter=0))
    data['checks']=[dict(target='part',x=20,y=20,z=50,solids=1)]
    with pytest.raises(ValueError,match='required 50, actual 30'):
        execute_plan(json.dumps(data),DraftRequest(prompt='overall height 50'))
    data['checks'][0]['z']=30
    result=execute_plan(json.dumps(data),DraftRequest(prompt='height 30'))
    assert result.measurements[0]['actual']['volume']==pytest.approx(math.pi*100*30)
    data['checks'][0]['solids']=2
    with pytest.raises(ValueError,match='solids'):
        execute_plan(json.dumps(data),DraftRequest(prompt='two solids'))


def test_compact_profiles_and_section_stations_are_exact_editable_geometry():
    circle=dict(circle=dict(diameter=12))
    reply=execute(create('cylinder',diameter=20,height=30,bore_diameter=0),action('pad',face='+Z',profile=circle,depth=20))
    assert build(reply.design)[0].Volume()==pytest.approx(math.pi*(100*30+36*20))
    reply=execute(action('create',name='turned',geometry=dict(kind='revolve',stations=[[0,20],[30,20],[30,12],[50,12]])))
    shape=build(reply.design)[0];bounds=exact_bounds(shape)
    assert reply.design.parts[0].geometry.kind=='revolve' and len(shape.Solids())==1
    assert shape.Volume()==pytest.approx(math.pi*(100*30+36*20)) and bounds.zlen==pytest.approx(50)
    reply=execute(action('create',name='segments',geometry=dict(kind='revolve',segments=[dict(length=30,diameter=20),dict(length=20,diameter=12)],bore_diameter=4)))
    shape=build(reply.design)[0]
    assert shape.Volume()==pytest.approx(math.pi*(100*30+36*20-4*50)) and exact_bounds(shape).zlen==pytest.approx(50)
    reply=execute(action('create',name='taper',geometry=dict(kind='revolve',segments=[dict(length=50,diameter=40,end_diameter=20)])))
    assert build(reply.design)[0].Volume()==pytest.approx(math.pi*50/3*(400+200+100))
    reply=execute(action('create',name='transition',geometry=dict(kind='loft',sections=[dict(z=0,profile=dict(circle=dict(diameter=40))),dict(z=50,profile=dict(circle=dict(diameter=20)))])))
    assert build(reply.design)[0].Volume()==pytest.approx(math.pi*50/3*(400+200+100))
    reply=execute(action('create',name='rectangle',geometry=dict(kind='extrusion',thickness=3,profile=dict(rectangle=dict(width=20,height=10,center=[2,4])))))
    assert build(reply.design)[0].Volume()==pytest.approx(600)


def test_invalid_radial_stations_and_ambiguous_profiles_are_rejected():
    for geometry in [dict(kind='revolve',stations=[[0,20],[20,12]],bore_diameter=13),
                     dict(kind='revolve',stations=[[10,20],[0,12]]),
                     dict(kind='extrusion',thickness=4,profile=dict(circle=dict(diameter=10),points=[[0,0],[1,0],[1,1]]))]:
        with pytest.raises(ValueError):execute(action('create',name='invalid',geometry=geometry))


def test_existing_hole_is_recognized_by_exact_cylindrical_face_not_assumed():
    reply=execute(create('cylinder'),action('hole',face='+Z',diameter=5))
    assert len(reply.design.parts[0].features)==0 and reply.tool_actions[-1]['outcome']=='already_satisfied'
    with pytest.raises(ValueError,match='이미 있는 구멍보다 작은'):
        execute(create('cylinder'),action('hole',face='+Z',diameter=3))
    reply=execute(create('cylinder'),action('hole',face='+Z',diameter=5,finish='counterbore',head_diameter=10,head_depth=3))
    assert len(reply.design.parts[0].features)==1
    assert build(reply.design)[0].Volume()==pytest.approx(math.pi*(30**2-2.5**2)*20-math.pi*(5**2-2.5**2)*3)


def test_pad_and_pocket_follow_previous_feature_and_have_expected_volume():
    circle=dict(sketch_mode='entities',entities=[dict(id='c',kind='circle',center=dict(x=0,y=0),radius=6)])
    reply=execute(create('cylinder',diameter=20,height=30,bore_diameter=0),action('pad',face='+Z',profile=circle,depth=20))
    assert build(reply.design)[0].Volume()==pytest.approx(math.pi*(100*30+36*20))
    reply=execute(create(),action('pocket',face='+Z',profile=circle,depth=5),action('hole',face='-Z',diameter=3))
    features=reply.design.parts[0].features
    assert features[1].support_feature==features[0].id
    assert build(reply.design)[0].Volume()==pytest.approx(100000-math.pi*36*5-math.pi*1.5**2*20)


def test_arbitrary_profile_is_editable_geometry_and_not_named_template():
    points=[dict(x=x,y=y) for x,y in [(0,0),(40,0),(40,10),(15,10),(15,35),(0,35)]]
    reply=execute(action('create',name='임의 윤곽',geometry=dict(kind='extrusion',points=points,thickness=6)))
    assert build(reply.design)[0].Volume()==pytest.approx((40*10+15*25)*6)
    assert len(reply.design.parts[0].geometry.points)==6


def test_profile_wrapper_and_repeated_closing_vertex_normalize_without_changing_shape():
    points=[[0,0],[40,0],[40,10],[15,10],[15,35],[0,35],[0,0]]
    reply=execute(action('create',name='임의 윤곽',geometry=dict(kind='extrusion',profile=dict(kind='profile',points=points),thickness=6)))
    assert build(reply.design)[0].Volume()==pytest.approx(4650)
    with pytest.raises(ValueError,match='단면'):execute(action('create',name='missing',geometry=dict(kind='extrusion',thickness=6)))
    with pytest.raises(ValueError,match='중복'):execute(action('create',name='duplicate',geometry=dict(kind='extrusion',points=points,profile=dict(points=points),thickness=6)))


@pytest.mark.parametrize('tool',['fillet','chamfer'])
def test_selected_face_edges_are_real_kernel_references(tool):
    reply=execute(create(length=20,width=20,thickness=20),action(tool,size=1,edges='+Z'))
    f=reply.design.parts[0].features[0]
    assert len(f.edges)==4 and all(e.center[2]==pytest.approx(20) for e in f.edges)
    assert 0<build(reply.design)[0].Volume()<8000


def test_general_dimensions_edit_preserves_other_parts_and_appearance():
    original=execute(create(),create('cylinder',target='axle')).design
    before=original.model_dump()
    reply=execute(action('dimensions','axle',values=dict(diameter=32)),action('appearance','axle',color='#abcdef'),current=original)
    assert original.model_dump()==before
    assert reply.design.parts[0].model_dump()==before['parts'][0]
    assert reply.design.parts[1].geometry.diameter==32 and reply.design.parts[1].color=='#abcdef'


def test_failed_later_action_does_not_mutate_input_and_reports_step():
    current=execute(create()).design;before=current.model_dump()
    with pytest.raises(ValueError,match=r'작업 2/2 \[hole.*부피 변화'):
        execute(action('appearance',color='#abcdef'),action('hole',face='+Z',diameter=3,centers=[[100,100]]),current=current)
    assert current.model_dump()==before


def test_real_kernel_failure_is_repaired_transactionally_with_precise_feedback():
    calls=[]
    def handle(request):
        body=json.loads(request.content);calls.append(body)
        if len(calls)==1:return response(plan(create('cylinder',bore_diameter=80)))
        assert '작업 1/1' in body['messages'][-1]['content'] and '내경' in body['messages'][-1]['content']
        return response(plan(create('cylinder')))
    reply=ollama_draft(DraftRequest(prompt='링'),'test',cad_transport(handle))
    assert reply['attempts']==2 and len(reply['design']['parts'])==1


def test_invalid_plan_stops_after_three_attempts_with_specific_reason():
    calls=[]
    def handle(request):calls.append(request);return response(plan(create('cylinder',bore_diameter=80)))
    with pytest.raises(ValueError,match=r'검증 원인:[\s\S]*내경'):
        ollama_draft(DraftRequest(prompt='링'),'test',cad_transport(handle))
    assert len(calls)==3


@pytest.mark.parametrize('args',[dict(geometry={'kind':'cylinder','diameter':float('inf')}),dict(geometry={'kind':'run_python','code':'os.system(...)'})])
def test_untrusted_geometry_cannot_execute_code_or_bypass_bounds(args):
    with pytest.raises(ValueError):execute(action('create',name='bad',**args))


def test_joint_and_pattern_build_exact_geometry():
    reply=execute(create('cylinder',target='base',bore_diameter=0),create('cylinder',target='shaft',diameter=10,height=50,bore_diameter=0),
                  action('joint','joint',kind='revolute',parent='base',child='shaft',z=20))
    assert reply.design.parts[0].fixed and reply.design.parts[1].transform.z==20
    reply=execute(create(length=10,width=10,thickness=5),action('solid',operation='linear_pattern',count=3,spacing=[20,0,0]))
    assert len(build(reply.design)[0].Solids())==3 and build(reply.design)[0].Volume()==pytest.approx(1500)


def test_parameter_bound_dimensions_require_explicit_parameter_edit():
    from cadstudio.parameters import set_binding
    current=execute(create()).design.model_dump();current['parameters']={'w':'80'}
    set_binding(current,['parts','part','geometry','length'],'w');current=Design.model_validate(current)
    with pytest.raises(ValueError,match='변수와 연결'):execute(action('dimensions',values=dict(length=70)),current=current)
    reply=execute(action('parameter','w',value='70'),current=current)
    assert reply.design.parts[0].geometry.length==70


@pytest.mark.parametrize('stage',['headers','stream'])
def test_unlimited_mode_has_no_read_deadline_and_still_cancels(stage):
    entered=threading.Event();closed=threading.Event();control=DraftControl();errors=[]
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            try:await asyncio.sleep(60)
            finally:closed.set()
            yield b''
    async def handle(request):
        assert request.extensions['timeout']['read'] is None and request.extensions['timeout']['connect']==4
        if stage=='stream':return httpx.Response(200,stream=Stream())
        entered.set()
        try:await asyncio.sleep(60)
        finally:closed.set()
    def run():
        try:ollama_draft(DraftRequest(prompt='임의 물건'),'test',cad_transport(handle),deadline=None,control=control)
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=run,daemon=True);thread.start();assert entered.wait(3);control.cancel();thread.join(2)
    assert not thread.is_alive() and closed.is_set() and isinstance(errors[0],DraftCancelled)


def test_cancel_stops_between_geometry_operations_without_partial_output():
    count=[0]
    def check():
        count[0]+=1
        if count[0]>1:raise DraftCancelled()
    with pytest.raises(DraftCancelled):execute_plan(json.dumps(plan(create(),action('shell',thickness=2))),DraftRequest(prompt='box'),check=check)


def test_ai_steps_restore_independently_and_preserve_branches_on_disk(tmp_path):
    from cadstudio.native.document import Document,read_project
    reply=execute(create(),action('shell',thickness=2));doc=Document()
    def commit(reply):doc.commit(reply.design,'AI',dict(source='local',provider='ollama',tool='prompt',tool_actions=reply.tool_actions,journal_base=reply.journal_base,journal_steps=reply.journal_steps))
    commit(reply);entries=doc.journal.path();assert len(entries)==3
    full=entries[-1]['id'];solid=entries[-2]['id']
    assert build(Design.model_validate(doc.journal.at(solid)))[0].Volume()==pytest.approx(100000)
    assert build(Design.model_validate(doc.journal.at(full)))[0].Volume()==pytest.approx(19592)
    doc.commit(doc.journal.at(solid),'undo',cursor=solid)
    second=execute(action('hole',face='+Z',diameter=6),current=Design.model_validate(doc.design));commit(second)
    assert doc.journal.at(full)['parts'][0]['features'][0]['operation']=='shell'
    file=tmp_path/'AI.cad.json';doc.write(file);reopened=read_project(file)
    assert len(reopened.history.entries)==4 and reopened.design.parts[0].features[0].operation=='cut'
    assert reopened.history.entries[-1].context['tool_actions'][0]['args']['diameter']==6


def test_mismatching_ai_history_does_not_mutate_document():
    from copy import deepcopy
    from cadstudio.native.document import Document
    doc=Document();doc.commit(execute(create()).design,'manual');before=deepcopy(doc.design);history=deepcopy(doc.journal.data)
    reply=execute(action('hole',face='+Z',diameter=6),current=Design.model_validate(before))
    invalid=deepcopy(reply.design.model_dump());invalid['parts'][0]['color']='#abcdef'
    with pytest.raises(ValueError,match='최종 설계가 다릅니다'):
        doc.commit(invalid,'AI',dict(journal_steps=reply.journal_steps,journal_base=None))
    assert doc.design==before and doc.journal.data==history
