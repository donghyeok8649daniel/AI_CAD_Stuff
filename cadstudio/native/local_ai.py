"""Optional native providers. The local endpoint is fixed to this PC."""
import json
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

def ollama_draft(request,model,transport=None):
    if not model or len(model)>120:raise ValueError('Ollama에 설치된 모델 이름을 입력하세요.')
    payload={'prompt':request.prompt,'mode':request.mode,'selected_part':request.selected_part,'current_design':request.current.model_dump() if request.current else None}
    messages=[{'role':'system','content':SYSTEM_PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]
    with httpx.Client(base_url='http://127.0.0.1:11434',timeout=httpx.Timeout(600,connect=4),trust_env=False,follow_redirects=False,transport=transport) as client:
        for attempt in range(2):
            try:
                body={'model':model,'messages':messages,'stream':False,'format':AIReply.model_json_schema(),'options':{'temperature':0,'num_predict':7000,'num_ctx':16384}}
                if model.split(':')[0].split('/')[-1]=='qwen3':body['think']=False
                with client.stream('POST','/api/chat',json=body) as response:
                    if response.status_code==404:raise ValueError('Ollama에서 모델을 찾지 못했습니다. 설치한 모델 이름을 확인하세요.')
                    if response.status_code!=200:raise ValueError('Ollama 요청에 실패했습니다. 실행 상태와 모델을 확인하세요.')
                    chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>2_000_000:raise ValueError('로컬 AI 응답이 너무 큽니다. 설계를 작게 나누세요.')
                        chunks.append(chunk)
                raw=json.loads(b''.join(chunks));content=raw.get('message',{}).get('content','')
                if raw.get('done') is not True or raw.get('done_reason')=='length':raise ValueError('로컬 AI 응답이 끝나지 않았습니다. 요청을 작게 나누세요.')
            except httpx.ConnectError:raise ValueError('Ollama에 연결할 수 없습니다. 이 PC에서 Ollama를 실행하고 모델을 설치하세요.') from None
            except httpx.TimeoutException:raise ValueError('로컬 AI 응답 시간이 초과되었습니다. 더 작은 모델이나 요청으로 시도하세요.') from None
            except httpx.HTTPError:raise ValueError('로컬 AI 연결에 실패했습니다.') from None
            try:
                with KERNEL_LOCK:result=AIReply.model_validate_json(content);verified=preview(result.design)
                if verified['stats']['collisions']:result.assumptions.append('부품 사이의 체적 간섭이 있습니다. 배치를 확인하세요.')
                return {**result.model_dump(),'changes':[],'provider':'ollama','attempts':attempt+1}
            except (ValueError,RuntimeError):
                if attempt:raise ValueError('로컬 AI 설계가 두 차례의 치수·형상 검증을 통과하지 못했습니다. 요청을 단순화하세요.') from None
                messages.extend([{'role':'assistant','content':content[:30000]},{'role':'user','content':'치수 또는 CAD 형상이 유효하지 않습니다. 허용된 형상으로 단순화하고 JSON 스키마에 맞게 다시 생성하세요.'}])
