"""Local PCB transactions: a preview is never an edit or a manufacturing approval."""
from copy import deepcopy
from .pcb import PCBProject, pcb_digest


def _data(project):
    return PCBProject.model_validate(project).model_dump(mode='json')


def _copper_preserved(before, after):
    for key in ('tracks', 'vias', 'zones'):
        rows = {row['id']: row for row in after.get(key, [])}
        if any(rows.get(row['id']) != row for row in before.get(key, [])):
            raise ValueError('기존 배선·비아·구리 영역은 제거하거나 바꿀 수 없습니다. / Existing copper must be preserved.')


def _preview_contract(before, after, kind):
    if kind not in ('placement', 'routing', 'alignment'):
        raise ValueError('지원하지 않는 PCB 미리보기 종류입니다.')
    _copper_preserved(before, after)
    if kind == 'routing':
        allowed = {'tracks', 'vias', 'layer_count'}
        if {k: v for k, v in before.items() if k not in allowed} != {k: v for k, v in after.items() if k not in allowed}:
            raise ValueError('배선 후보는 부품·보드·연결 정보를 바꿀 수 없습니다.')
        if after.get('layer_count', 2) < before.get('layer_count', 2):
            raise ValueError('배선 후보가 기존 구리층을 제거할 수 없습니다.')
        return
    if {k: v for k, v in before.items() if k != 'components'} != {k: v for k, v in after.items() if k != 'components'}:
        raise ValueError('배치·정렬 후보는 보드와 기존 구리를 보존해야 합니다.')
    old = {c['ref']: c for c in before['components']}
    new = {c['ref']: c for c in after['components']}
    if old.keys() != new.keys():
        raise ValueError('배치·정렬 중 부품을 추가하거나 삭제할 수 없습니다.')
    coordinates = {'x_mm', 'y_mm'} | ({'rotation_deg'} if kind == 'alignment' else set())
    wired_nets = {row['net'] for key in ('tracks', 'vias', 'zones') for row in before.get(key, [])}
    for ref, component in old.items():
        other = new[ref]
        if {k: v for k, v in component.items() if k not in coordinates} != {k: v for k, v in other.items() if k not in coordinates}:
            raise ValueError('핀 위치·피치·부품 규격을 변형해서 정렬할 수 없습니다.')
        if component != other and any(pin.get('net') in wired_nets for pin in component['pins']):
            raise ValueError('기존 구리에 연결된 부품은 배선 보호를 해제하지 않는 한 이동하지 않습니다.')
        if component != other and before.get('zones'):
            raise ValueError('저장된 구리 영역이 있는 PCB는 자동 이동을 보류합니다.')


class PCBWorkflowSession:
    """Bounded local undo and staged results, independent of the CAD document.

    Every returned object is a copy. The host still explicitly applies the local
    PCB draft through its existing CAD journal transaction.
    """
    def __init__(self, project, undo_limit=20):
        if type(undo_limit) is not int or not 1 <= undo_limit <= 64:
            raise ValueError('PCB 되돌리기 한도는 1~64입니다.')
        self.undo_limit = undo_limit
        self.reset(project)

    def current(self):
        return PCBProject.model_validate(deepcopy(self._current))

    def reset(self, project):
        self._current = _data(project)
        self._undo = []
        self._redo = []
        self._preview = None
        return self.current()

    @property
    def preview(self):
        return deepcopy(self._preview)

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    def replace(self, project):
        candidate = _data(project)  # Validate before changing any state.
        if candidate != self._current:
            self._undo.append(self._current)
            self._undo = self._undo[-self.undo_limit:]
            self._current = candidate
            self._redo = []
        self._preview = None
        return self.current()

    def stage_candidate(self, candidate, *, expected_base_sha256, label, kind):
        if expected_base_sha256 != pcb_digest(self._current):
            raise ValueError('PCB 초안이 바뀌었습니다. 후보를 다시 계산하세요. / Stale PCB result.')
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise ValueError('PCB 후보 이름이 잘못되었습니다.')
        after = _data(candidate)
        _preview_contract(self._current, after, kind)
        old = {c['ref']: c for c in self._current['components']}
        self._preview = dict(base_sha256=expected_base_sha256, candidate_sha256=pcb_digest(after),
            candidate=after, label=label, kind=kind,
            moved_refs=[c['ref'] for c in after['components'] if old.get(c['ref']) != c],
            added_track_ids=[r['id'] for r in after['tracks'] if r['id'] not in {t['id'] for t in self._current['tracks']}],
            added_via_ids=[r['id'] for r in after.get('vias', []) if r['id'] not in {v['id'] for v in self._current.get('vias', [])}],
            local_draft_only=True, manufacturing_qualified=False)
        return self.preview

    def apply_preview(self):
        preview = self._preview
        if preview is None:
            raise ValueError('적용할 PCB 미리보기가 없습니다.')
        if preview['base_sha256'] != pcb_digest(self._current) or preview['candidate_sha256'] != pcb_digest(preview['candidate']):
            self._preview = None
            raise ValueError('PCB 미리보기의 기준 또는 후보가 바뀌었습니다.')
        _preview_contract(self._current, preview['candidate'], preview['kind'])
        return self.replace(preview['candidate'])

    def cancel_preview(self):
        self._preview = None

    def undo(self):
        if not self._undo:
            raise ValueError('되돌릴 PCB 작업이 없습니다.')
        self._redo.append(self._current)
        self._current = self._undo.pop()
        self._preview = None
        return self.current()

    def redo(self):
        if not self._redo:
            raise ValueError('다시 실행할 PCB 작업이 없습니다.')
        self._undo.append(self._current)
        self._current = self._redo.pop()
        self._preview = None
        return self.current()
