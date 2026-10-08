"""Structured, credential-free Codex failure classification.

An occurrence of 'model' in a network error is not a model-access failure.
Only the classification, RPC method and numeric status may be persisted.
"""
from __future__ import annotations

import json


def error_details(error):
    text = json.dumps(error, ensure_ascii=True).lower()
    statuses = set()
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in ('httpstatuscode', 'status_code') and isinstance(item, int):
                    statuses.add(item)
                visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    visit(error)
    rpc_code = error.get('code') if isinstance(error, dict) else None
    if not isinstance(rpc_code, int): rpc_code = None
    def has(*values): return any(value in text for value in values)
    if statuses & {401, 403} or has('unauthorized', 'authentication', 'token expired', 'sign in', 'not logged'):
        category = 'authentication'
    elif 429 in statuses or has('usagelimit', 'usage_limit', 'ratelimit', 'rate_limit', 'quota', 'credit_balance_exhausted', 'limit reached', 'sessionbudgetexceeded'):
        category = 'usage'
    elif has('contextwindowexceeded', 'context length', 'context window'):
        category = 'context'
    elif has('invalid schema', 'invalid_json_schema', 'schema is invalid', 'output schema', 'outputschema') and (400 in statuses or has('badrequest', 'invalid', 'unsupported', 'not supported')):
        category = 'schema'
    elif has('requires experimentalapi', 'unknown variant', 'missing field', 'invalid params', 'method not found') or rpc_code in (-32601, -32602):
        category = 'protocol'
    elif has('model_not_found', 'unsupported_model', 'model is not supported', 'model not supported', 'model is unavailable', 'model does not exist', 'model access', 'unsupported model') or ('model' in text and has('not supported with', 'does not have access')):
        category = 'model'
    elif statuses & {400, 404, 409, 422} or has('badrequest', 'unsupported', 'invalid request'):
        category = 'request'
    elif any(code >= 500 or code in (408, 425) for code in statuses) or has(
        'httpconnectionfailed', 'responsestreamconnectionfailed', 'responsestreamdisconnected',
        'responsetoomanyfailedattempts', 'internalservererror', 'serveroverloaded',
        'connection reset', 'connection refused', 'connection closed', 'stream closed',
        'stream disconnected', 'network is unreachable', 'dns error', 'error sending request',
        'failed to connect', 'timed out', 'temporarily unavailable', 'econnreset',
        'os error 10054', 'os error 10060', 'os error 11001'):
        category = 'network'
    else:
        category = 'unknown'
    return {'category': category, 'rpc_code': rpc_code, 'http_status': sorted(statuses)}


def safe_error(error):
    category = error_details(error)['category']
    return {
        'authentication': 'Codex 로그인이 필요하거나 만료되었습니다. Codex 연결에서 ChatGPT로 다시 로그인하세요.',
        'usage': 'Codex 사용량 한도에 도달했습니다. Codex에서 남은 사용량과 초기화 시간을 확인하세요. API로 전환하지 않았습니다.',
        'context': 'Codex 입력이 모델의 문맥 한도를 넘었습니다. 첨부자료나 설계 범위를 줄여 다시 시도하세요. 현재 설계는 변경되지 않았습니다.',
        'schema': 'Codex가 CAD 작업 계획의 응답 규격을 거절했습니다. 모델 로그인을 다시 해도 해결되지 않을 수 있습니다. 앱 업데이트와 연결 진단을 확인하세요.',
        'protocol': 'Codex CLI와 앱의 연결 규격이 맞지 않습니다. CLI를 업데이트하고 연결을 새로 확인하세요. 현재 설계는 변경되지 않았습니다.',
        'model': '선택한 Codex 모델의 접근 권한이나 지원 여부를 확인해야 합니다. 모델 목록을 새로 찾고 직접 사용할 모델을 선택하세요.',
        'request': 'Codex가 생성 요청을 거절했습니다. 연결 진단에서 요청 단계와 오류 분류를 확인하세요. 현재 설계는 변경되지 않았습니다.',
        'network': 'Codex 통신이 일시적으로 끊겼습니다. 연결 복구를 기다립니다.',
        'unknown': 'Codex 연결 또는 설계 요청에 실패했습니다. 연결 진단과 Codex 로그인·사용량을 확인하세요. 현재 설계는 변경되지 않았습니다.',
    }[category]


def record_error(path, error, method=''):
    """Bounded support report; excludes all server prose, input and credentials."""
    from datetime import datetime, timezone
    from .. import __version__
    from pathlib import Path
    import os
    import tempfile
    safe_methods = {'initialize', 'config/read', 'account/read', 'model/list',
        'account/rateLimits/read', 'account/login/start', 'account/login/cancel',
        'thread/start', 'mcpServerStatus/list', 'turn/start', 'turn/interrupt', 'turn/completed', 'error'}
    row = dict(error_details(error), method=method if method in safe_methods else '',
        at=datetime.now(timezone.utc).isoformat(), app_version=__version__)
    path = Path(path)
    try:
        rows = json.loads(path.read_text(encoding='utf-8')) if path.is_file() and path.stat().st_size < 65536 else []
        if not isinstance(rows, list): rows = []
        # Sanitize earlier diagnostic files too; never echo unknown keys.
        rows = [{k: v for k, v in item.items() if k in row} for item in rows[-31:] if isinstance(item, dict)]
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.codex-diagnostic-', suffix='.tmp', dir=path.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump([*rows, row], stream, ensure_ascii=False)
        os.replace(name, path)
    except (OSError, ValueError, TypeError):
        pass  # Diagnostics must not break cancellation or replace the true error.
