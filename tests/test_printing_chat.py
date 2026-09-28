import asyncio
import json
import struct
from copy import deepcopy
import httpx
import pytest
from cadstudio.models import Design, DraftRequest
from cadstudio.printing import prepare_print,export_print_stl
from cadstudio.kernel import build,exact_bounds
from cadstudio.native.ai_chat import answer
from cadstudio.native.local_ai import DraftControl,DraftCancelled
from test_interference import blocks
from test_codex_planner import Session
from test_cloud_planner import answer as cloud_answer


def test_print_plate_separates_parts_and_stl_matches_preview(tmp_path):
    original=blocks(0);before=original.model_dump()
    prepared,result,warnings=prepare_print(original,['a','b'],rotation=(90,0,0),bed=(80,70,100),gap=5)
    assert not warnings and not result['stats']['collisions']
    assert original.model_dump()==before and len(prepared.parts)==2 and not prepared.mates
    shapes=build(prepared);a,b=map(exact_bounds,shapes)
    assert a.zmin==pytest.approx(0) and b.zmin==pytest.approx(0)
    assert b.xmin-a.xmax==pytest.approx(5)
    assert result['stats']['volume']==pytest.approx(1000)
    path=tmp_path/'print.stl';export_print_stl(prepared,path)
    data=path.read_bytes();n=struct.unpack('<I',data[80:84])[0]
    assert n>0 and len(data)==84+50*n
    from vtkmodules.vtkIOGeometry import vtkSTLReader
    reader=vtkSTLReader();reader.SetFileName(str(path));reader.Update();bounds=reader.GetOutput().GetBounds()
    assert bounds[4]==pytest.approx(0,abs=1e-5)
    assert bounds[1]-bounds[0]==pytest.approx(result['stats']['bounds'][0],abs=1e-4)


def test_print_plate_outside_bed_report_and_bad_selection():
    assert prepare_print(blocks(),['a'],bed=(5,5,2))[2]
    with pytest.raises(ValueError,match='선택'):prepare_print(blocks(),[])
    with pytest.raises(ValueError):prepare_print(blocks(),['a'],bed=(float('nan'),20,30))


@pytest.mark.parametrize('provider',['ollama','openai','codex'])
def test_chat_provider_is_read_only_and_preserves_conversation(provider):
    current=blocks();before=current.model_dump();request=DraftRequest(prompt='현재 부품 간격은?',current=current)
    calls=[]
    def handle(r):
        calls.append(json.loads(r.content))
        if provider=='ollama':return httpx.Response(200,json=dict(done=True,message=dict(content=json.dumps({'answer':'답변 · 설계 변경 없음'}))))
        return cloud_answer({'answer':'답변 · 설계 변경 없음'})
    session=Session([{'answer':'답변 · 설계 변경 없음'}])
    text=answer(request,provider,'gpt-6-astra',api_key='test-key',transport=httpx.MockTransport(handle),session_factory=lambda _:session,history=[{'role':'user','content':'앞선 질문'},{'role':'assistant','content':'앞선 답변'}])
    assert '답변' in text and current.model_dump()==before
    messages=session.calls[0] if provider=='codex' else calls[0].get('messages',calls[0].get('input'))
    assert messages[-3]['content']=='앞선 질문' and messages[-1]['content']==request.prompt
    assert 'read-only' in messages[0]['content']


def test_chat_rejects_design_payload_and_cancels():
    session=Session([{'answer':'ok','design':blocks().model_dump()}])
    with pytest.raises(ValueError,match='답변 형식'):answer(DraftRequest(prompt='hello'),'codex','gpt-6-astra',session_factory=lambda _:session)
    control=DraftControl();control.cancel()
    with pytest.raises(DraftCancelled):answer(DraftRequest(prompt='hello'),'codex','gpt-6-astra',control=control,session_factory=lambda _:Session([]))
    with pytest.raises(ValueError,match='대화 모델'):answer(DraftRequest(prompt='hello'),'local','')


def test_chat_deadline_closes_session():
    session=Session([])
    async def stuck(*args):await asyncio.sleep(60)
    session.content=stuck
    with pytest.raises(ValueError,match='시간'):answer(DraftRequest(prompt='hello'),'codex','gpt-6-astra',deadline=.01,session_factory=lambda _:session)
    assert session.closed
