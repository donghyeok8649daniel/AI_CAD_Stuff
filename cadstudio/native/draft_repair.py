"""Keep renderable rejected drafts, with measured repair feedback and no apply bypass."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json

from ..interference import assess, check_joint_travel, describe, travel_message
from ..kernel import KERNEL_LOCK, build, exact_bounds
from .cad_scope import Scope


def fingerprint(request):
    return hashlib.sha256(request.model_dump_json().encode('utf-8')).hexdigest()


def review_candidate(design, baseline, verified, check=lambda: None):
    report = assess(design, baseline, collisions=verified['stats']['collisions'], check=check)
    travel = None if report['blocked'] or baseline is None else check_joint_travel(baseline, design, check=check)
    issues = []
    if report['blocked']:
        issues.append('부품 간섭을 수정해야 합니다.\n' + describe(design, report['blocked']))
    if travel and travel['blocked']:
        issues.append(travel_message(design, travel))
    return dict(status='needs_repair' if issues else 'ready', issues=issues,
                collisions=report['blocked'], existing=report['existing'], travel=travel)


def repair_scope(scope):
    # A selector that chose create-only must not forbid the pocket needed to fix a fit.
    additions = ('transform', 'hole', 'pocket', 'edit_feature')
    return replace(scope, tools=tuple(dict.fromkeys((*scope.tools, *additions))))


def measured_feedback(design, review, check=lambda: None):
    """Exact intersection extents in both global and each part's local coordinates."""
    collisions = review['collisions']
    lines = list(review['issues'])
    if collisions:
        with KERNEL_LOCK:
            shapes = dict(zip((p.id for p in design.parts), build(design)))
            parts = {p.id: p for p in design.parts}
            def bounds(shape):
                b = exact_bounds(shape)
                return {axis: [round(getattr(b, axis+'min'), 5), round(getattr(b, axis+'max'), 5)] for axis in 'xyz'}
            facts = []
            for collision in collisions[:8]:
                check(); a, b = collision['a'], collision['b']
                overlap = shapes[a].intersect(shapes[b])
                fact = dict(pair=[a, b], volume_mm3=round(collision['volume'], 5),
                            overlap_world_mm=bounds(overlap), parts=[])
                for identifier in (a, b):
                    part = parts[identifier]; t = part.transform
                    local = overlap.translate((-t.x, -t.y, -t.z))
                    for angle, axis in ((t.rz, (0,0,1)), (t.ry, (0,1,0)), (t.rx, (1,0,0))):
                        if angle: local = local.rotate((0,0,0), axis, -angle)
                    fact['parts'].append(dict(id=identifier, world_bounds_mm=bounds(shapes[identifier]),
                        overlap_local_mm=bounds(local), placement=t.model_dump(),
                        joint_driven=any(m.child==identifier for m in design.mates)))
                facts.append(fact)
            lines.append('Measured CAD intersections (mm; extents are bounds, not a commanded cut):\n' + json.dumps(facts, ensure_ascii=False, separators=(',', ':')))
    lines.append('Return a corrected COMPLETE plan executed from the ORIGINAL current_design, not a patch against the rejected draft. Keep the original requested dimensions, colors, all required bodies and joint relationships. Do not delete, shrink a specimen, group, hide or union separate functional parts to evade collision checks. For an inserted specimen/shaft, create a real slot/bore/pocket in its support, with explicit assembly clearance; coincident contact is allowed, overlapping volume is not. Do not scatter assembly parts merely to eliminate intersections. Correct joint offsets in the original joint action for joint-driven placement. Preserve correctly implemented actions; use local overlap coordinates with the documented face frame to position cuts. In feedback, local coordinates refer to the PART frame; hole/pocket profiles refer to the selected FACE bounding-box midpoint. Check both frames before calculating a profile center.')
    return '\n\n'.join(lines)


class DraftRepair:
    def __init__(self, request, resume=None):
        self.request = request
        self.best = None
        self.score = None
        self.prior_attempts = 0
        self.seed = deepcopy(resume)
        if resume:
            if resume.get('request_fingerprint') != fingerprint(request):
                raise ValueError('초안의 원본 설계나 요청이 바뀌었습니다. 현재 설계로 새 초안을 생성하세요.')
            self.prior_attempts = int(resume.get('attempts', 0))

    def initial_scope(self):
        if not self.seed: return None
        return Scope.parse(json.dumps(self.seed['scope']), self.request)

    def messages(self, scope, feedback='', plan=None):
        messages = scope.plan_messages(self.request)
        messages[0]['content'] += '\nFor strict schemas use null for unused optional fields. dimensions.args.values uses {key,value_json} entries, each value_json is JSON encoded text.'
        seed = self.seed or {}
        plan = plan or seed.get('plan')
        feedback = feedback or seed.get('feedback', '')
        if seed.get('user_instruction'):feedback += '\n사용자 추가 수정 지시: '+seed['user_instruction'][:1000]
        if plan:
            messages += [dict(role='assistant', content=plan), dict(role='user', content='CAD 검증 오류를 수정한 전체 CAD 계획을 반환하세요. 원래 요청을 유지하세요.\n' + feedback)]
        return messages

    def check(self, result, verified, plan, scope, check=lambda: None):
        review = review_candidate(result.design, self.request.current, verified, check)
        result_data = result.model_dump()
        result_data['validation'] = review
        if review['existing']:
            result_data['assumptions'].append('기존 설계의 간섭이 남아 있습니다. 조립 전 수정하세요.')
        if review['status'] == 'ready': return result_data
        try:feedback = measured_feedback(result.design, review, check)
        except (ValueError, RuntimeError):feedback='\n'.join(review['issues'])+'\n간섭 위치의 상세 계산은 완료되지 않았습니다. 원래 치수와 조립 관계를 유지하며 배치 또는 홈을 수정하세요.'
        # Prefer fewer conflicts, then smaller overlap. An invalid later attempt never
        # replaces an earlier renderable result. No partial execution is presented.
        score = (len(review['collisions']) + bool(review['travel']), sum(c['volume'] for c in review['collisions']))
        if self.score is None or score < self.score:
            self.score = score
            retained_scope = repair_scope(scope)
            if not retained_scope.new_parts and 'create' in retained_scope.tools:
                old_ids = {p.id for p in self.request.current.parts} if self.request.current else set()
                identifiers=tuple(p.id for p in result.design.parts if p.id not in old_ids)
                if len(identifiers)<=32:retained_scope = replace(retained_scope, new_parts=identifiers)
            self.best = dict(result=result_data, plan=plan, feedback=feedback, scope=asdict(retained_scope))
        raise ValueError(feedback)

    def pending(self, provider, attempts):
        if not self.best: return None
        result = deepcopy(self.best['result'])
        result.update(provider=provider, attempts=attempts,
            repair=dict(plan=self.best['plan'], feedback=self.best['feedback'], scope=self.best['scope'],
                        request_fingerprint=fingerprint(self.request), attempts=self.prior_attempts+attempts))
        from .cad_tools import TOOL_LABELS
        result['changes'] = [f"{s['step']}. {TOOL_LABELS[s['tool']]} · {s['target']}" for s in result.get('tool_actions', [])]
        return result

    def interrupted(self, provider, message):
        result=self.pending(provider,0)
        if result:
            result['assumptions'].append('추가 자동 수정이 중단되어 검증된 형상의 이전 초안을 보존했습니다. '+message[:300])
        return result

    def next(self, scope, plan, error):
        if self.best:
            scope = Scope.parse(json.dumps(self.best['scope']), self.request)
            feedback = self.best['feedback']
            if str(error) != feedback:
                feedback += '\nLast attempted correction was invalid: ' + str(error)[:1800] + '\nRepair the retained renderable plan below; do not repeat that invalid correction.'
            return scope, self.messages(scope, feedback, self.best['plan'])
        return scope, self.messages(scope, str(error)[:1800], plan)
