"""Safe OpenAI diagnostics and a cancellable, inference-free model lookup."""
import asyncio
import logging
import os
import re
import ssl

import httpx

from .local_ai import DraftControl


def credentials(api_key, model):
    api_key = api_key.strip() if isinstance(api_key, str) else ''
    model = model.strip() if isinstance(model, str) else ''
    if not api_key:
        raise ValueError('OpenAI API 키를 입력하세요. 연결 안내에서 키를 발급할 수 있습니다.')
    if not api_key.isascii() or any(c.isspace() for c in api_key):
        raise ValueError('API 키 안에 한글·공백·줄바꿈이 있습니다. 키 이름이나 프로젝트 이름 대신 발급된 비밀 키 값을 붙여넣으세요.')
    if not model or len(model) > 120 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', model):
        raise ValueError('OpenAI 모델 이름을 확인하세요. 예: gpt-6-astra')
    return api_key, model


def api_error_message(error, model, *, api_key='', body=None, status=None, request_id=None):
    """Never echo error messages, request bodies, headers or credentials."""
    from openai import APIConnectionError, APITimeoutError
    raw = body if body is not None else getattr(error, 'body', None)
    raw = raw if isinstance(raw, dict) else {}
    raw = raw.get('error', raw) if isinstance(raw.get('error', raw), dict) else {}
    code = raw.get('code') or getattr(error, 'code', None)
    param = raw.get('param') or getattr(error, 'param', None)
    status = status or getattr(error, 'status_code', None)
    request_id = request_id or getattr(error, 'request_id', None)
    server_message = raw.get('message', '')
    server_message = server_message.lower() if isinstance(server_message, str) else ''
    if isinstance(error, APITimeoutError):
        message = 'OpenAI 연결 시간이 초과되었습니다. 네트워크와 최대 대기 시간을 확인하세요.'
    elif isinstance(error, APIConnectionError):
        cause = error; tls = False
        for _ in range(6):
            if cause is None: break
            tls = tls or isinstance(cause, ssl.SSLError) or 'certificate_verify_failed' in str(cause).lower()
            cause = cause.__cause__
        message = ('OpenAI 보안 연결 인증서(TLS)를 확인하지 못했습니다. PC 시간·보안 프로그램·회사망 인증서를 확인하세요.' if tls else
                   'OpenAI 서버에 연결하지 못했습니다. 인터넷·방화벽·VPN·회사 프록시에서 api.openai.com 연결을 확인하세요.')
    elif status == 401 or code in ('invalid_api_key', 'authentication_error'):
        message = 'OpenAI API 키 인증에 실패했습니다. 키가 폐기·만료됐는지 확인하고 같은 프로젝트에서 새 키를 발급하세요.'
    elif code in ('insufficient_quota', 'billing_hard_limit_reached', 'billing_not_active', 'organization_usage_limit_exceeded'):
        message = 'OpenAI API 잔액 또는 사용 한도가 부족합니다. 연결 안내의 API 결제 설정에서 잔액·결제·프로젝트 한도를 확인하세요.'
    elif status == 403:
        message = '이 키 또는 프로젝트에 요청 권한이 없습니다. 키의 Responses 쓰기 권한과 프로젝트·모델 접근 권한을 확인하세요.'
    elif status == 404 or code == 'model_not_found':
        message = '선택한 모델을 찾을 수 없거나 이 프로젝트에 모델 접근 권한이 없습니다. 모델 이름을 확인하고 연결 안내의 키·모델 확인을 실행하세요.'
    elif status == 429 or code == 'rate_limit_exceeded':
        message = 'OpenAI 요청 한도에 도달했습니다. 잠시 기다린 뒤 다시 시도하세요. API 잔액·프로젝트 한도도 확인할 수 있습니다.'
    elif code == 'invalid_json_schema' or 'invalid schema' in server_message:
        message = 'CAD 앱의 설계 요청 형식(JSON Schema)을 OpenAI가 거부했습니다. API 키 재발급으로 해결되는 문제가 아닙니다. 이 오류 코드와 앱 버전을 알려주세요.'
    elif code in ('unsupported_parameter', 'unsupported_value'):
        message = '선택한 모델이 CAD 앱의 요청 옵션을 지원하지 않습니다. 아래 문제 항목과 모델 이름을 확인하세요.'
    elif status in (400, 422):
        message = 'OpenAI가 CAD 요청 형식 또는 옵션을 거부했습니다. 아래 오류 코드·문제 항목을 확인하세요. 키 문제로 단정할 수 없습니다.'
    elif (isinstance(status, int) and status >= 500) or code in ('server_error', 'server_is_overloaded'):
        message = 'OpenAI 서버에서 일시적인 오류가 발생했습니다. 잠시 뒤 다시 시도하세요.'
    else:
        message = 'OpenAI 설계 생성에 실패했습니다. 아래 진단 정보와 앱 버전을 확인하세요.'
    lines = [message]
    if isinstance(status, int): lines.append(f'HTTP 상태: {status}')
    # Only small identifiers from the response, never arbitrary server prose.
    for title, value in [('모델', model), ('오류 코드', code), ('문제 항목', param), ('요청 ID', request_id)]:
        if isinstance(value, str) and len(value) <= 160 and re.fullmatch(r'[A-Za-z0-9_.:/\[\]-]+', value) and 'sk-' not in value and (not api_key or api_key not in value):
            lines.append(f'{title}: {value}')
    message = '\n'.join(lines)
    logging.getLogger(__name__).warning('%s', message)
    return message


def make_client(api_key, deadline, transport=None):
    from openai import AsyncOpenAI
    for name in ('OPENAI_ORG_ID', 'OPENAI_PROJECT_ID'):
        value = os.getenv(name, '')
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError(f'{name} 인증 설정에 한글·공백·줄바꿈이 있습니다. 이름이 아닌 영문 ID를 사용하거나 잘못 설정한 환경변수를 지운 뒤 앱을 다시 실행하세요.')
    return AsyncOpenAI(api_key=api_key, base_url='https://api.openai.com/v1', max_retries=0,
                      http_client=httpx.AsyncClient(timeout=httpx.Timeout(deadline, connect=10),
                                                    trust_env=False, follow_redirects=False, transport=transport))


def check_access(api_key, model, *, control=None, transport=None, deadline=15):
    """GET model metadata only. No prompt, design or generation endpoint."""
    from openai import APIError
    api_key, model = credentials(api_key, model)
    control = control or DraftControl()
    async def run():
        async with make_client(api_key, deadline, transport) as client:
            control.check()
            result = await client.models.retrieve(model)
            control.check()
            if result.id != model:
                raise ValueError('선택한 모델과 서버의 응답이 다릅니다. 모델 이름을 확인하세요.')
            return 'API 인증 및 선택 모델 조회에 성공했습니다.\n모델: '+model+'\n설계 생성은 실행하지 않았습니다. 잔액·Responses 쓰기 권한·CAD 요청 지원까지 확인한 결과는 아닙니다.'
    try:
        return asyncio.run(control.execute(run, deadline, 'OpenAI 키·모델 확인 시간이 초과되었습니다. 네트워크를 확인하세요.'))
    except APIError as exc:
        message = api_error_message(exc, model, api_key=api_key)
        if getattr(exc, 'status_code', None) == 403:
            message += '\n이번 검사는 모델 조회(Models 읽기) 권한이 필요합니다. 조회 실패만으로 설계 생성 권한도 없다고 단정할 수 없습니다.'
        raise ValueError(message) from None
