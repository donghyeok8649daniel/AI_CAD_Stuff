"""Real SDK/mock transport: never use credentials or paid endpoints in tests."""
import asyncio
import ssl
import threading

import httpx
import pytest

from cadstudio.native.cloud_connection import check_access, api_error_message
from cadstudio.native.local_ai import DraftControl, DraftCancelled
from test_cloud_planner import invoke, events


@pytest.mark.parametrize('status,code,param,match', [
    (401,'invalid_api_key',None,'인증'),
    (403,None,None,'권한'),
    (404,'model_not_found','model','모델 접근 권한'),
    (429,'insufficient_quota',None,'잔액'),
    (429,'rate_limit_exceeded',None,'잠시 기다린'),
    (400,'invalid_json_schema','text.format.schema','키 재발급으로 해결되는 문제가 아닙니다'),
    (400,'unsupported_parameter','reasoning.effort','요청 옵션'),
    (400,None,None,'요청 형식'),
    (500,None,None,'서버'),
])
def test_draft_error_distinguishes_failure_without_leaking_response(status,code,param,match):
    calls=[]
    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={'x-request-id':'req_example'}, json={'error':{
            'type':'invalid_request_error','code':code,'param':param,'message':'private prompt and sk-secret-test-placeholder'}})
    with pytest.raises(ValueError,match=match) as caught:invoke(handle)
    text=str(caught.value)
    assert f'HTTP 상태: {status}' in text and 'gpt-6-astra' in text and 'req_example' in text
    if code:assert code in text
    if param:assert param in text
    assert len(calls)==1 and all(secret not in text for secret in ('private','sk-secret','test-placeholder'))


def test_probe_only_retrieves_chosen_model_and_never_sends_design():
    calls=[]
    def handle(request):
        calls.append(request)
        assert request.method=='GET' and str(request.url)=='https://api.openai.com/v1/models/gpt-6-astra'
        assert request.headers['authorization']=='Bearer fake-key' and not request.content
        return httpx.Response(200,json=dict(id='gpt-6-astra',object='model',created=1,owned_by='openai'))
    result=check_access('  fake-key  ',' gpt-6-astra ',transport=httpx.MockTransport(handle))
    assert len(calls)==1 and '조회에 성공' in result and '확인한 결과는 아닙니다' in result


@pytest.mark.parametrize('key,model',[('','gpt-6-astra'),('a\nb','gpt-6-astra'),('비밀','gpt-6-astra'),('fake-key','../../responses')])
def test_malformed_credentials_never_make_a_network_request(key,model):
    def fail(request):raise AssertionError('Unexpected network call')
    with pytest.raises(ValueError):check_access(key,model,transport=httpx.MockTransport(fail))


def test_probe_missing_models_permission_does_not_claim_responses_is_denied():
    with pytest.raises(ValueError,match='Models 읽기') as caught:
        check_access('fake-key','gpt-6-astra',transport=httpx.MockTransport(lambda request:httpx.Response(403,json={'error':{'message':'private'}})))
    assert '단정할 수 없습니다' in str(caught.value)


@pytest.mark.parametrize('tls',[False,True])
def test_network_failure_distinguishes_tls_without_echoing_errors(tls):
    def handle(request):
        try:
            if tls:raise ssl.SSLCertVerificationError('CERTIFICATE_VERIFY_FAILED private sk-secret')
            raise OSError('private network details')
        except Exception as exc:raise httpx.ConnectError('private',request=request) from exc
    with pytest.raises(ValueError,match='TLS' if tls else '방화벽') as caught:
        check_access('fake-key','gpt-6-astra',transport=httpx.MockTransport(handle))
    assert 'private' not in str(caught.value) and 'sk-secret' not in str(caught.value)


def test_probe_cancel_interrupts_blocked_network_and_closes_transport():
    entered=threading.Event();closed=threading.Event();errors=[];control=DraftControl()
    async def handle(request):
        entered.set()
        try:await asyncio.sleep(60)
        finally:closed.set()
    def run():
        try:check_access('fake-key','gpt-6-astra',control=control,transport=httpx.MockTransport(handle))
        except Exception as exc:errors.append(exc)
    thread=threading.Thread(target=run,daemon=True);thread.start();assert entered.wait(5)
    control.cancel();thread.join(2)
    assert not thread.is_alive() and closed.is_set() and isinstance(errors[0],DraftCancelled)


def test_probe_timeout_is_bounded():
    async def handle(request):await asyncio.sleep(60)
    with pytest.raises(ValueError,match='확인 시간이 초과'):
        check_access('fake-key','gpt-6-astra',transport=httpx.MockTransport(handle),deadline=.03)


def test_stream_failure_keeps_safe_error_code():
    def handle(request):return httpx.Response(200,headers={'content-type':'text/event-stream'},content=events(
        {'type':'response.failed','response':{'status':'failed','error':{'code':'server_error','message':'private sk-secret'}}}))
    with pytest.raises(ValueError,match='server_error') as caught:invoke(handle)
    assert 'private' not in str(caught.value) and 'sk-secret' not in str(caught.value)


def test_secret_in_diagnostic_identifier_is_not_shown():
    result=api_error_message(None,'sk-secret',api_key='sensitive',status=400,
                             body={'code':'sk-secret','param':'sensitive'},request_id='sk-secret')
    assert 'sk-secret' not in result and 'sensitive' not in result


@pytest.mark.parametrize('variable',['OPENAI_ORG_ID','OPENAI_PROJECT_ID'])
def test_non_ascii_auth_settings_explain_ascii_failure_without_echoing_value(monkeypatch,variable):
    monkeypatch.setenv(variable,'개인 프로젝트')
    def fail(request):raise AssertionError('Unexpected network call')
    with pytest.raises(ValueError,match=variable) as caught:
        check_access('fake-key','gpt-6-astra',transport=httpx.MockTransport(fail))
    assert '개인 프로젝트' not in str(caught.value)


def test_pasted_key_name_explains_ascii_error_before_sdk_construction():
    def fail(request):raise AssertionError('Unexpected network call')
    with pytest.raises(ValueError,match='키 이름이나 프로젝트 이름'):
        check_access('sk-proj-내키이름','gpt-6-astra',transport=httpx.MockTransport(fail))
