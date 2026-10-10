"""ChatGPT-authenticated Codex plans, validated by the existing CAD kernel."""
import asyncio
import math

from ..kernel import KERNEL_LOCK, preview
from ..power_paths import PowerInputRequired
from .cad_scope import Scope, scope_schema, scope_messages
from .cad_schema import plan_schema
from .cad_tools import execute_plan, TOOL_LABELS
from .cloud_ai import response_schema, decode_plan
from .codex_connection import CodexSession
from .local_ai import DraftControl, restore_sketch_display, validation_feedback
from .draft_repair import DraftRepair
from .codex_models import validate_selection, CodexRuntimeSettings


def generate(request, model, *, executable='', control=None, progress=None, deadline=600,
             effort='medium', session_factory=CodexSession, repair=None, runtime_config=None):
    control = control or DraftControl(); progress = progress or (lambda message: None)
    repairs = DraftRepair(request, repair)
    runtime_config = runtime_config or CodexRuntimeSettings(model, effort)
    provenance = dict(model=model, effort=effort)
    def keep_candidate(response, verified):
        response.update(provenance)
        if repairs.best: repairs.best['result'].update(provenance)
        control.keep_draft(response, verified)
    if deadline is not None and (not isinstance(deadline, (int, float)) or not math.isfinite(deadline) or deadline <= 0):
        raise ValueError('대기 시간은 양수 또는 무제한이어야 합니다.')
    async def run():
        from .codex_reconnect import RecoveringSession
        async with RecoveringSession(session_factory,executable,control,progress) as session:
            await session.account()
            available = await session.models()
            validate_selection(available, *runtime_config.snapshot())
            async def content(messages, schema):
                control.check()
                selected_model, selected_effort = runtime_config.snapshot()
                validate_selection(available, selected_model, selected_effort)
                # RecoveringSession retries these captured settings and messages;
                # the next phase may capture a newer GUI selection.
                value = await session.content(selected_model, messages, response_schema(schema), selected_effort, progress)
                provenance.update(model=selected_model, effort=selected_effort)
                return value
            scope = repairs.initial_scope()
            if scope is None:
                progress('Codex · 요청의 부품과 CAD 도구 선택 중…')
                raw = await content(scope_messages(request), scope_schema())
                try: scope = Scope.parse(raw, request)
                except (ValueError, TypeError):
                    scope = Scope(); progress('Codex · 전체 CAD 도구로 계획합니다…')
            messages = repairs.messages(scope)
            attempt = 0
            while True:
                control.check()
                schema = plan_schema(scope.tools, scope.shapes, single_part=scope.intent == 'part',
                    connections=scope.connections, new_parts=scope.new_parts,
                    existing_parts=[p.id for p in request.current.parts] if request.current else ())
                progress('Codex · CAD 작업 계획 생성 중…' if not attempt and not repair else f'Codex · CAD 검증 오류 수정 중… {attempt+1}회'+(' · 무제한' if deadline is None else '/6'))
                raw = await content(messages, schema)
                try:
                    control.check(); progress('Codex 생성 완료 · 실제 CAD 형상 검증 중…')
                    with KERNEL_LOCK:
                        control.check()
                        result = scope.validate_result(execute_plan(decode_plan(raw), request, check=control.check,
                            progress=progress, single_part=scope.intent == 'part'))
                        verified = preview(result.design)
                    control.check()
                    restore_sketch_display(result.design, request.current)
                    reviewed = repairs.check(result, verified, raw, scope, control.check,
                        checkpoint=keep_candidate, provider='codex', attempts=attempt+1)
                    return {**reviewed, 'provider': 'codex', **provenance, 'attempts': attempt + 1,
                        'changes': [f"{s['step']}. {TOOL_LABELS[s['tool']]} · {s['target']}" for s in result.tool_actions],
                        'planning': dict(intent=scope.intent, tools=scope.tools, shapes=scope.shapes,
                                         connections=scope.connections, new_parts=scope.new_parts)}
                except PowerInputRequired:raise
                except (ValueError, RuntimeError) as exc:
                    reason = validation_feedback(exc)
                    if deadline is not None and (attempt == 5 or (attempt >= 2 and not repairs.best)):
                        pending = repairs.pending('codex', attempt+1)
                        if pending: return {**provenance, **pending}
                        raise ValueError('Codex 설계가 3차례의 치수·형상 검증을 통과하지 못했습니다. 현재 설계는 변경되지 않았습니다.\n\n검증 원인:\n' + reason) from None
                    scope, messages = repairs.next(scope, raw, exc)
                    attempt += 1
                    await asyncio.sleep(.1)
    try:return asyncio.run(control.execute(run, deadline, 'Codex가 제한 시간 안에 완료하지 못했습니다. AI 최대 대기를 늘리거나 무제한으로 설정하세요.'))
    except PowerInputRequired:raise
    except ValueError as exc:
        control.check()
        pending=repairs.interrupted('codex',str(exc))
        if pending:return {**provenance, **pending}
        raise
