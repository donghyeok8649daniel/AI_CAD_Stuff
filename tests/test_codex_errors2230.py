import json

import pytest

from cadstudio.native.codex_errors import error_details, record_error, safe_error
from cadstudio.native.codex_reconnect import ConnectionInterrupted, classified_error


@pytest.mark.parametrize('error', [
    {'message':'Model response stream closed: os error 10054'},
    {'codexErrorInfo':'serverOverloaded', 'message':'Model request unavailable'},
    {'codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':503}},'message':'model upstream failed'},
])
def test_model_word_in_transport_error_retries(error):
    assert error_details(error)['category']=='network'
    assert isinstance(classified_error(error),ConnectionInterrupted)
    assert '모델' not in safe_error(error)


@pytest.mark.parametrize(('error','category'), [
    ({'codexErrorInfo':{'responseStreamConnectionFailed':{'httpStatusCode':401}}},'authentication'),
    ({'codexErrorInfo':'rateLimitExceeded','message':'connection reset'},'usage'),
    ({'codexErrorInfo':'contextWindowExceeded'},'context'),
    ({'code':-32602,'message':'invalid params private-token'},'protocol'),
    ({'message':'turn/start.dynamicTools requires experimentalApi capability'},'protocol'),
    ({'codexErrorInfo':'badRequest','message':'Invalid output schema for model'},'schema'),
    ({'message':'The model is not supported with this account'},'model'),
    ({'message':'A model request failed at unknown location'},'unknown'),
    ({'codexErrorInfo':{'httpConnectionFailed':{'httpStatusCode':403}},'message':'stream disconnected'},'authentication'),
])
def test_permanent_errors_are_distinct_and_do_not_retry(error,category):
    assert error_details(error)['category']==category
    assert not isinstance(classified_error(error),ConnectionInterrupted)
    assert 'private-token' not in safe_error(error)


def test_support_report_is_bounded_and_cannot_leak_server_text(tmp_path):
    path=tmp_path/'diagnostic.json'
    path.write_text(json.dumps([{'message':'secret','category':'unknown'}]))
    for _ in range(40):
        record_error(path, {'code':-32602,'message':'invalid params sk-secret-key private-prompt',
            'authorization':'Bearer secret'},'turn/start')
    text=path.read_text()
    rows=json.loads(text)
    assert len(rows)==32 and all(row['method']=='turn/start' for row in rows)
    assert all(set(row)=={'category','rpc_code','http_status','method','at','app_version'} for row in rows)
    assert not any(secret in text for secret in ('secret','prompt','authorization','Bearer'))
