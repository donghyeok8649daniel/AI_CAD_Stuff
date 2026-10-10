"""Timeline labels hide an automatic AI prefix without rewriting history."""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt

from test_ai_settings_v3 import app, window, wait
from cadstudio.catalog import preset
from cadstudio.native.document import Document, differences, read_project


@pytest.mark.parametrize('source,context,label,expected', [
    ('ai', {}, 'AI 설계 시작', '설계 시작'),
    ('openai', {'tool': 'prompt'}, 'AI 치수 변경 · body', '치수 변경 · body'),
    ('local', {'tool': 'prompt'}, 'AI 부품 생성 · AI 실험', '부품 생성 · AI 실험'),
    ('manual', {'tool': 'prompt'}, 'AI 설계 시작', '설계 시작'),
    ('manual', {'tool': 'dimensions'}, 'AI 실험', 'AI 실험'),
    ('openai', {'tool': 'dimensions'}, 'AI 실험', 'AI 실험'),
    ('manual', {}, 'AI 실험', 'AI 실험'),
    ('openai', {'tool': 'prompt'}, '설계 명령 적용', '설계 명령 적용'),
    ('openai', {'tool': 'prompt'}, 'AIx 실험', 'AIx 실험'),
    ('openai', {'tool': 'prompt'}, '치수 변경 · AI 실험', '치수 변경 · AI 실험'),
])
def test_timeline_label_strips_only_marked_automatic_prefix(source, context, label, expected):
    from cadstudio.native.window import timeline_step_label
    entry = {'id': 'stable-step', 'source': source, 'context': context, 'label': label}
    before = deepcopy(entry)
    assert timeline_step_label(entry) == expected
    assert entry == before


def ai_fixture():
    """Owned declarative CAD data matching the real apply_draft context."""
    base = preset('cylinder').model_dump()
    base['name'] = 'AI 실험'
    base['parts'][0]['name'] = 'AI 부품'
    after = deepcopy(base)
    after['parts'][0]['geometry']['height'] += 4
    target = base['parts'][0]['id']
    action = dict(tool='dimensions', target=target, args={'height': after['parts'][0]['geometry']['height']})
    context = dict(source='openai', provider='codex', tool='prompt', prompt='owned offline cylinder fixture',
        model_provenance={'model': 'gpt-6.1-sol', 'effort': 'ultra'}, journal_base=base,
        journal_steps=[dict(action=action, changes=differences(base, after))])
    return base, after, target, context


def assert_timeline(window, labels):
    entries = window.document.journal.path()
    assert len(entries) == window.timeline.count() == len(labels)
    for number, (entry, label) in enumerate(zip(entries, labels)):
        item = window.timeline.item(number)
        assert item.text() == f'{number + 1:02d}  {label}'
        assert item.toolTip() == entry['created_at'] + '\n' + label
        assert item.data(Qt.ItemDataRole.UserRole) == entry['id']


def test_saved_legacy_ai_history_display_preserves_journal_names_save_reopen_and_undo(app, window, tmp_path):
    base, after, target, context = ai_fixture()
    document = Document()
    document.commit(after, '설계 명령 적용', context)
    manual = deepcopy(after)
    manual['parts'][0]['geometry']['diameter'] += 2
    document.commit(manual, 'AI 실험', {'source': 'manual', 'tool': 'dimensions'})
    original = deepcopy(document.project().model_dump(mode='json'))
    path = tmp_path / 'saved-legacy-ai.pcad'
    document.write(path)
    saved_bytes = path.read_bytes()

    w = window
    w.open_project(path)
    wait(app, lambda: not w.busy)
    assert w.document.path == path
    expected_labels = ['설계 시작', '치수 변경 · ' + target, 'AI 실험']
    assert_timeline(w, expected_labels)
    for _ in range(3):
        w.rebuild_timeline()
    assert w.document.project().model_dump(mode='json') == original
    assert path.read_bytes() == saved_bytes
    assert w.document.design['name'] == 'AI 실험'
    assert w.document.design['parts'][0]['name'] == 'AI 부품'
    assert [entry['label'] for entry in w.document.journal.path()] == [
        'AI 설계 시작', 'AI 치수 변경 · ' + target, 'AI 실험']

    ids = [entry['id'] for entry in w.document.journal.data['entries']]
    w.undo()
    wait(app, lambda: not w.busy)
    assert w.document.design == after
    assert [entry['id'] for entry in w.document.journal.data['entries']] == ids
    w.redo()
    wait(app, lambda: not w.busy)
    assert w.document.project().model_dump(mode='json') == original
    assert_timeline(w, expected_labels)
    assert w.save()
    assert read_project(path).model_dump(mode='json') == original
    assert path.read_bytes() == saved_bytes
    w.open_project(path)
    wait(app, lambda: not w.busy)
    assert w.document.project().model_dump(mode='json') == original
    assert_timeline(w, expected_labels)


def test_actual_apply_draft_uses_plain_operation_labels_and_keeps_actual_model_provenance(app, window):
    base, after, target, context = ai_fixture()
    w = window
    w.last_draft = dict(serial=w.operation_serial, provider='codex', prompt=context['prompt'],
        design=after, model='selected-model', effort='high', response=dict(summary='Owned offline fixture',
            model='gpt-6.1-sol', effort='ultra', journal_base=base, journal_steps=context['journal_steps']))
    w.apply_draft()
    wait(app, lambda: not w.busy)
    assert w.document.design == after
    assert_timeline(w, ['설계 시작', '치수 변경 · ' + target])
    entries = w.document.journal.path()
    assert entries[0]['label'] == 'AI 설계 시작'
    assert entries[1]['label'] == 'AI 치수 변경 · ' + target
    for entry in entries:
        assert entry['source'] == 'openai'
        assert entry['context']['tool'] == 'prompt'
        assert entry['context']['model_provenance'] == {'model': 'gpt-6.1-sol', 'effort': 'ultra'}
    before = deepcopy(w.document.project().model_dump(mode='json'))
    w.rebuild_timeline()
    assert w.document.project().model_dump(mode='json') == before
