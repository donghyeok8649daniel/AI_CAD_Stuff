"""Optional native providers. The local endpoint is fixed to this PC."""
import json
import asyncio
import threading
import time
from copy import deepcopy
import httpx
from ..planner import AIReply,SYSTEM_PROMPT,openai_draft
from ..kernel import preview,KERNEL_LOCK

def cloud_draft(request,client,model):
    from openai import APIError,AuthenticationError,RateLimitError,APITimeoutError
    try:return openai_draft(request,client=client,model=model)
    except AuthenticationError:raise ValueError('OpenAI API 키 인증에 실패했습니다. 키를 확인하세요.') from None
    except RateLimitError:raise ValueError('OpenAI 요청 한도 또는 API 잔액을 확인하세요.') from None
    except APITimeoutError:raise ValueError('OpenAI 응답 시간이 초과되었습니다. 더 작은 요청으로 시도하세요.') from None
    except APIError:raise ValueError('OpenAI API 요청에 실패했습니다. 네트워크와 모델 이름을 확인하세요.') from None

class DraftCancelled(Exception):
    pass


class DraftControl:
    """Cancel blocked async network reads, including before the first token."""
    def __init__(self):
        self.cancelled=threading.Event();self.lock=threading.Lock();self.loop=None;self.task=None
    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.loop and not self.loop.is_closed():self.loop.call_soon_threadsafe(self.task.cancel)
    def check(self):
        if self.cancelled.is_set():raise DraftCancelled('설계 초안 생성을 취소했습니다.')
    async def execute(self,fn,deadline):
        self.check()
        with self.lock:self.loop=asyncio.get_running_loop();self.task=asyncio.current_task()
        try:
            self.check()
            return await asyncio.wait_for(fn(),timeout=deadline)
        except asyncio.CancelledError:raise DraftCancelled('설계 초안 생성을 취소했습니다.') from None
        except asyncio.TimeoutError:raise ValueError('로컬 AI가 제한 시간 안에 완료하지 못했습니다. 부품 하나와 치수부터 요청하거나 더 작은 모델을 선택하세요.') from None
        finally:
            with self.lock:self.loop=None;self.task=None


def ollama_context(design):
    """Rendering caches are not design instructions; keep the real dimensions."""
    def compact(value):
        if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if v is not None and v!=[] and v!={}}
        if isinstance(value,list):return [compact(v) for v in value]
        return value
    data=design.model_dump()
    for sketch in data.get('sketches',[]):
        face=sketch.get('context',{}).get('face')
        if face:
            for key in ('outline','projected_entities','projection_unsupported'):face.pop(key,None)
    return compact(data)


def restore_sketch_display(result,current):
    if not current:return
    by_id={s.id:s for s in current.sketches}
    for sketch in result.sketches:
        source=by_id.get(sketch.id)
        if source is None:continue
        old_part=next((p for p in current.parts if p.id==source.context.part_id),None)
        new_part=next((p for p in result.parts if p.id==sketch.context.part_id),None)
        # Display caches are reusable only while their supporting shape stays
        # unchanged. A width edit can leave the face frame unchanged too.
        if old_part and (new_part is None or old_part.geometry!=new_part.geometry or old_part.features!=new_part.features):continue
        old=source.context.face;face=sketch.context.face
        if old and face and sketch.context.part_id==source.context.part_id and sketch.context.support_feature==source.context.support_feature:
            keys=('index','normal','origin','x_direction','face_count')
            if all(getattr(old,k)==getattr(face,k) for k in keys):
                face.outline=deepcopy(old.outline);face.projected_entities=deepcopy(old.projected_entities);face.projection_unsupported=old.projection_unsupported


def ollama_draft(request,model,transport=None,*,control=None,progress=None,deadline=600):
    control=control or DraftControl();progress=progress or (lambda message:None)
    if not model or len(model)>120:raise ValueError('Ollama에 설치된 모델 이름을 입력하세요.')
    # Keep default-valued dimensions and discriminators: a cylinder's kind is
    # itself a Pydantic default, and must not disappear from an editing request.
    payload={'prompt':request.prompt,'mode':request.mode,'selected_part':request.selected_part,'current_design':ollama_context(request.current) if request.current else None}
    compact='\nReturn COMPACT JSON, without whitespace or optional fields at their default values. Preserve existing nondefault data. Start with design, finish with a short summary and assumptions. Example: {"design":{"name":"원통","parts":[{"id":"cylinder1","name":"원통","geometry":{"kind":"cylinder","diameter":20,"height":10}}]},"summary":"원통 초안","assumptions":[]}. Do not repeat instructions or explain the JSON.'
    messages=[{'role':'system','content':SYSTEM_PROMPT+compact},{'role':'user','content':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]
    result=asyncio.run(control.execute(lambda:_ollama_reply(model,messages,transport,control,progress,deadline),deadline))
    if request.current:
        from ..models import Design
        design=Design.model_validate(result['design']);restore_sketch_display(design,request.current);result['design']=design.model_dump()
    return result


async def _ollama_reply(model,messages,transport,control,progress,deadline):
    async with httpx.AsyncClient(base_url='http://127.0.0.1:11434',timeout=httpx.Timeout(deadline,connect=4),trust_env=False,follow_redirects=False,transport=transport) as client:
        for attempt in range(2):
            control.check();progress('모델 준비 / 명령 해석 중…' if not attempt else '형상 검증 실패 · 설계 수정 재시도 중…')
            try:
                body={'model':model,'messages':messages,'stream':True,'format':AIReply.model_json_schema(),'options':{'temperature':0,'num_predict':4096,'num_ctx':16384}}
                if model.split(':')[0].split('/')[-1]=='qwen3':body['think']=False
                async with client.stream('POST','/api/chat',json=body) as response:
                    if response.status_code==404:raise ValueError('Ollama에서 모델을 찾지 못했습니다. 설치한 모델 이름을 확인하세요.')
                    if response.status_code!=200:raise ValueError('Ollama 요청에 실패했습니다. 실행 상태와 모델을 확인하세요.')
                    chunks=[];size=0;done=False;last_notice=0;received=0
                    # NDJSON arrives while the model is generating. Keep the buffer bounded
                    # even when a faulty server never sends a newline.
                    pending=b''
                    async for chunk in response.aiter_bytes():
                        control.check();size+=len(chunk);pending+=chunk
                        if size>2_000_000:raise ValueError('로컬 AI 응답이 너무 큽니다. 설계를 작게 나누세요.')
                        lines=pending.split(b'\n');pending=lines.pop()
                        for line in lines:
                            if not line.strip():continue
                            raw=json.loads(line)
                            if raw.get('error'):raise ValueError('Ollama 생성 오류: '+str(raw['error'])[:300])
                            content=raw.get('message',{}).get('content','');chunks.append(content);received+=len(content)
                            if time.monotonic()-last_notice>.3:
                                progress(f'설계 생성 중 · {received:,}자 수신' if received else '모델이 명령을 해석 중…');last_notice=time.monotonic()
                            if raw.get('done'):
                                if raw.get('done_reason')=='length':raise ValueError('로컬 AI의 출력 길이를 초과했습니다. 부품을 나누어 요청하세요.')
                                done=True;break
                        if done:break
                    if not done and pending.strip():
                        raw=json.loads(pending)
                        if raw.get('error'):raise ValueError('Ollama 생성 오류: '+str(raw['error'])[:300])
                        chunks.append(raw.get('message',{}).get('content',''));done=raw.get('done') is True and raw.get('done_reason')!='length'
                if not done:raise ValueError('로컬 AI 연결이 설계 완료 전에 끊어졌습니다. 다시 시도하세요.')
                content=''.join(chunks)
            except httpx.ConnectError:raise ValueError('Ollama에 연결할 수 없습니다. 이 PC에서 Ollama를 실행하고 모델을 설치하세요.') from None
            except httpx.TimeoutException:raise ValueError('로컬 AI가 선택한 대기 시간 안에 응답하지 않았습니다. CPU에서 큰 모델은 준비 시간이 길 수 있습니다. AI 최대 대기를 늘리거나 부품 하나씩 요청하세요.') from None
            except httpx.HTTPError:raise ValueError('로컬 AI 연결에 실패했습니다.') from None
            except (json.JSONDecodeError,UnicodeDecodeError,AttributeError,TypeError):raise ValueError('Ollama에서 잘못된 응답을 받았습니다. 모델을 확인하고 다시 시도하세요.') from None
            try:
                control.check();progress('생성 완료 · 치수와 실제 CAD 형상 검증 중…')
                with KERNEL_LOCK:result=AIReply.model_validate_json(content);verified=preview(result.design)
                control.check()
                if verified['stats']['collisions']:result.assumptions.append('부품 사이의 체적 간섭이 있습니다. 배치를 확인하세요.')
                return {**result.model_dump(),'changes':[],'provider':'ollama','attempts':attempt+1}
            except (ValueError,RuntimeError):
                if attempt:raise ValueError('로컬 AI 설계가 두 차례의 치수·형상 검증을 통과하지 못했습니다. 요청을 단순화하세요.') from None
                messages.extend([{'role':'assistant','content':content[:30000]},{'role':'user','content':'치수 또는 CAD 형상이 유효하지 않습니다. 허용된 형상으로 단순화하고 JSON 스키마에 맞게 다시 생성하세요.'}])
