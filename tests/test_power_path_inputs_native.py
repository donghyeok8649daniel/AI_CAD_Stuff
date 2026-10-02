"""Missing power ratings ask for input once, including in unlimited AI mode."""
from copy import deepcopy
import json

import httpx
import pytest

from cadstudio.models import Design, DraftRequest
from cadstudio.power_paths import PowerInputRequired
from test_codex_planner import Session
from test_cloud_planner import answer


def selected_scope():
    return dict(intent='edit', tools=['power_path'], shapes=[], new_parts=[], connections=[])


def incomplete_plan():
    return dict(summary='전원 연결', actions=[dict(tool='power_path', target='supply', args=dict(
        source_voltage_v=5, positive_wire_length_mm=250, positive_wire_cross_section_mm2=.5,
        return_wire_length_mm=350, return_wire_cross_section_mm2=.5,
        load_voltage_v=5, load_current_a=0))])


@pytest.mark.parametrize('provider', ['codex', 'ollama', 'openai'])
def test_unlimited_missing_power_input_stops_after_one_plan_without_changing_design(provider):
    current = Design(parts=[])
    before = deepcopy(current.model_dump())
    request = DraftRequest(prompt='보드 전원 연결. 부하 전류는 아직 미정', current=current)
    calls = []
    if provider == 'codex':
        from cadstudio.native.codex_ai import generate
        session = Session([selected_scope(), incomplete_plan()])
        def invoke():
            return generate(request, 'gpt-6-astra', deadline=None, session_factory=lambda _: session)
    else:
        def handle(http_request):
            calls.append(http_request)
            data = selected_scope() if len(calls) == 1 else incomplete_plan()
            assert len(calls) <= 2, 'Missing operating inputs must not retry indefinitely'
            if provider == 'openai':return answer(data)
            return httpx.Response(200, json=dict(done=True, message=dict(content=json.dumps(data))))
        if provider == 'ollama':
            from cadstudio.native.local_ai import ollama_draft
            def invoke():return ollama_draft(request, 'offline-test', httpx.MockTransport(handle), deadline=None)
        else:
            from cadstudio.native.cloud_ai import generate
            def invoke():return generate(request, 'gpt-4.1', api_key='test-placeholder',
                                        transport=httpx.MockTransport(handle), deadline=None)
    with pytest.raises(PowerInputRequired) as raised:invoke()
    assert raised.value.missing_fields == ('load_current_a',)
    assert current.model_dump() == before
    if provider == 'codex':assert len(session.calls) == 2 and session.closed
    else:assert len(calls) == 2


@pytest.mark.parametrize('language', ['ko', 'en'])
def test_worker_preserves_input_request_and_native_ui_keeps_connection_and_design(app, monkeypatch, tmp_path, language):
    from cadstudio.native.ai_task import AITask
    from cadstudio.native import window
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(window, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(LocalModelPicker, 'refresh', lambda _: None)
    # This test concerns worker packets and UI state, not rendering. Actual VTK
    # is exercised by electrical_smoke2160 under both Windows renderers.
    monkeypatch.setattr(window.CADViewport, 'initialize', lambda _: None)
    w = window.MainWindow(restore=False)
    prior_language=w.language_service.language
    w.language_service.set_language(language,persist=False)
    before = deepcopy(w.document.design)
    error = PowerInputRequired(('load_current_a',))
    def needs_input(*_):raise error
    task = AITask(needs_input)
    packets = []
    task.failed.connect(packets.append)
    task.failed.connect(w.ai_failed)
    blocked=w.provider.blockSignals(True)
    w.provider.setCurrentIndex(w.provider.findData('codex'))
    w.provider.blockSignals(blocked)
    w.ai_task = task
    try:
        task._run()
        app.processEvents()
        assert packets == [(task, error)]
        assert w.ai_task is None and not w.ai_timer.isActive()
        assert w.document.design == before and not w.document.dirty
        assert ('전원 수치 입력 필요' if language=='ko' else 'Power operating inputs required') in w.ai_result.toPlainText()
        assert ('전원 연결 설계…' if language=='ko' else 'Power path design…') in w.ai_result.toPlainText()
        assert 'load_current_a' not in w.ai_result.toPlainText()
        assert '초안 생성 실패' not in w.ai_result.toPlainText()
        assert '✓' in w.codex_status.text()
    finally:
        w.language_service.set_language(prior_language,persist=False)
        w.document.dirty = False
        w.close()
        app.processEvents()


from test_placement_native import app
