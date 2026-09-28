"""ChatGPT-authenticated Codex plans, validated by the existing CAD kernel."""
import asyncio
import math

from ..kernel import KERNEL_LOCK, preview
from .cad_scope import Scope, scope_schema, scope_messages
from .cad_schema import plan_schema
from .cad_tools import execute_plan, TOOL_LABELS
from .cloud_ai import response_schema, decode_plan
from .codex_connection import CodexSession
from .local_ai import DraftControl, restore_sketch_display, validation_feedback


def generate(request, model, *, executable='', control=None, progress=None, deadline=600,
             effort='medium', session_factory=CodexSession):
    control = control or DraftControl(); progress = progress or (lambda message: None)
    if deadline is not None and (not isinstance(deadline, (int, float)) or not math.isfinite(deadline) or deadline <= 0):
        raise ValueError('대기 시간은 양수 또는 무제한이어야 합니다.')
    async def run():
        async with session_factory(executable) as session:
            await session.account()
            available = {item['model']: item for item in await session.models()}
            if model not in available:
                raise ValueError('선택한 모델을 현재 Codex 계정에서 찾을 수 없습니다. Codex 연결에서 모델 목록을 새로 찾으세요.')
            if effort not in available[model]['efforts']:
                raise ValueError('선택한 모델은 이 추론 강도를 지원하지 않습니다. Codex 연결에서 모델과 추론 강도를 다시 선택하세요.')
            async def content(messages, schema):
                control.check()
                return await session.content(model, messages, response_schema(schema), effort, progress)
            progress('Codex · 요청의 부품과 CAD 도구 선택 중…')
            raw = await content(scope_messages(request), scope_schema())
            try: scope = Scope.parse(raw, request)
            except (ValueError, TypeError):
                scope = Scope(); progress('Codex · 전체 CAD 도구로 계획합니다…')
            schema = plan_schema(scope.tools, scope.shapes, single_part=scope.intent == 'part',
                connections=scope.connections, new_parts=scope.new_parts,
                existing_parts=[p.id for p in request.current.parts] if request.current else ())
            messages = scope.plan_messages(request)
            messages[0]['content'] += '\nFor the strict output schema, use null for unused optional fields. dimensions.args.values is an array of {key,value_json}; each value_json is JSON encoded text. Do not invent unused dimensions.'
            for attempt in range(3):
                control.check()
                progress('Codex · CAD 작업 계획 생성 중…' if not attempt else 'Codex · CAD 검증 오류 수정 중…')
                raw = await content(messages, schema)
                try:
                    control.check(); progress('Codex 생성 완료 · 실제 CAD 형상 검증 중…')
                    with KERNEL_LOCK:
                        control.check()
                        result = scope.validate_result(execute_plan(decode_plan(raw), request, check=control.check,
                            progress=progress, single_part=scope.intent == 'part'))
                        verified = preview(result.design)
                    control.check()
                    from ..interference import validate_candidate
                    collision_report=validate_candidate(result.design,request.current,collisions=verified['stats']['collisions'],check=control.check)
                    if collision_report['existing']:result.assumptions.append('기존 설계의 간섭이 남아 있습니다. 새 간섭은 없으나 조립 전 수정하세요.')
                    restore_sketch_display(result.design, request.current)
                    return {**result.model_dump(), 'provider': 'codex', 'attempts': attempt + 1,
                        'changes': [f"{s['step']}. {TOOL_LABELS[s['tool']]} · {s['target']}" for s in result.tool_actions],
                        'planning': dict(intent=scope.intent, tools=scope.tools, shapes=scope.shapes,
                                         connections=scope.connections, new_parts=scope.new_parts)}
                except (ValueError, RuntimeError) as exc:
                    reason = validation_feedback(exc)
                    if attempt == 2:
                        raise ValueError('Codex 설계가 3차례의 치수·형상 검증을 통과하지 못했습니다. 현재 설계는 변경되지 않았습니다.\n\n검증 원인:\n' + reason) from None
                    messages = messages[:2] + [{'role': 'assistant', 'content': raw[:30000]},
                        {'role': 'user', 'content': 'CAD 검증 오류를 수정한 전체 계획을 반환하세요. 원래 요청과 올바른 작업을 유지하세요.\n' + reason}]
    return asyncio.run(control.execute(run, deadline, 'Codex가 제한 시간 안에 완료하지 못했습니다. AI 최대 대기를 늘리거나 무제한으로 설정하세요.'))
