"""Official read-only usage response, without confusing weekly/short buckets."""
import json
import pytest
from cadstudio.native.codex_usage import normalize_usage,usage_text
from test_codex_connection import server


def payload():
    return dict(rateLimits={'primary':{'usedPercent':1,'windowDurationMins':10080}},rateLimitsByLimitId={
        'codex':{'primary':{'usedPercent':87,'windowDurationMins':10080,'resetsAt':1791046745},'secondary':None},
        'codex_other':{'primary':{'usedPercent':0,'windowDurationMins':10080}}})


def test_multi_bucket_primary_can_be_weekly_and_does_not_use_other_allowance():
    value=normalize_usage(payload());text=usage_text(value)
    assert '13% 남음' in text and '100% 남음' not in text and '99% 남음' not in text
    assert '초기화' in text and len(value['buckets'])==2
    value=normalize_usage({'rateLimitsByLimitId':{'codex_other':payload()['rateLimitsByLimitId']['codex_other']}})
    assert '잔여량 확인 불가' in usage_text(value) and '100%' not in usage_text(value)


@pytest.mark.parametrize('used',[None,True,'87',float('nan'),float('inf')])
def test_unknown_usage_is_not_zero_or_full(used):
    value=normalize_usage({'rateLimits':{'primary':{'usedPercent':used,'windowDurationMins':10080}}})
    assert '잔여량 확인 불가' in usage_text(value) and '%' not in usage_text(value)


def test_legacy_windows_clamped_and_null_is_unavailable():
    value=normalize_usage({'rateLimits':{'primary':{'usedPercent':-3,'windowDurationMins':300},'secondary':{'usedPercent':120,'windowDurationMins':10080,'resetsAt':1e99}}})
    text=usage_text(value)
    assert '주간 · 0% 남음' in text and '5시간 · 100% 남음' in text
    assert '확인 불가' in usage_text(normalize_usage(None))
    assert '확인 불가' in usage_text(normalize_usage({'rateLimits':None,'rateLimitsByLimitId':None}))


def test_connection_usage_is_read_only_no_model_turn_or_reset(server):
    from cadstudio.native.codex_connection import connect
    factory,log,children,_=server
    result=connect(session_factory=lambda _:factory())
    assert result['account']['plan']=='pro' and result['usage']['buckets']==[]
    calls=[json.loads(line)['method'] for line in log.read_text().splitlines()]
    assert 'account/rateLimits/read' in calls
    assert not any(v.startswith(('turn/','thread/','account/rateLimitResetCredit/')) for v in calls)
    assert children[0].returncode is not None


def test_usage_panel_refresh_and_unavailable_state(app,monkeypatch,tmp_path):
    from cadstudio.native import window,codex_connection
    from cadstudio.native.model_picker import LocalModelPicker
    from test_openai_setup_native import wait
    monkeypatch.setattr(window,'DATA_DIR',tmp_path);monkeypatch.setattr(LocalModelPicker,'refresh',lambda _:None)
    result={'account':{'plan':'pro'},'models':[{'model':'test','name':'Test','efforts':['medium']}],'usage':normalize_usage(payload())}
    monkeypatch.setattr(codex_connection,'connect',lambda *args,**kw:result)
    w=window.MainWindow();w.resize(1000,700);w.show();w.ai_dock.show();w.ai_dock.raise_()
    w.provider.setCurrentIndex(w.provider.findData('codex'));w.codex_config=dict(executable='fake.exe',model='test')
    try:
        w.codex_check_button.click();wait(app,lambda:w.codex_probe_task is None)
        assert '13% 남음' in w.codex_usage.text() and '✓' in w.codex_status.text()
        assert w.codex_usage.isVisible() and w.codex_check_button.isEnabled()
        result['usage']={'buckets':[]};w.codex_check_button.click();wait(app,lambda:w.codex_probe_task is None)
        assert '확인 불가' in w.codex_usage.text() and '13%' not in w.codex_usage.text()
        w.provider.setCurrentIndex(w.provider.findData('ollama'));assert not w.codex_usage.isVisible()
    finally:w.document.dirty=False;w.close();app.processEvents()


from test_placement_native import app
