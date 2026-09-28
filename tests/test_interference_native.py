from copy import deepcopy
from PySide6.QtWidgets import QMessageBox
from cadstudio.models import Design
from cadstudio.native.workflows import JointDriveDialog
from cadstudio.native.placement_dialog import PlacementDialog
from cadstudio.native.print_dialog import PrintDialog
from cadstudio.native.draft_preview import DraftPreviewDialog
from cadstudio.kernel import preview
from test_interference import blocks,swing
from test_placement_native import app,wait,dispose


def test_collision_warning_and_apply_guard_recover_after_edit(app,monkeypatch):
    raw=blocks(20).model_dump();dialog=PlacementDialog(None,raw,['b']);dialog.show()
    try:
        dialog.fields['x'].setValue(-15);wait(app,lambda:dialog.checked is not None)
        assert dialog.interference['blocked'] and not dialog.apply_button.isEnabled()
        assert dialog.viewport.collision_button.isVisible()
        dialog.accept();assert dialog.alive
        shown=[];monkeypatch.setattr(QMessageBox,'warning',lambda *args:shown.append(args[-1]))
        dialog.viewport.collision_button.click();assert 'mm³' in shown[0]
        dialog.fields['x'].setValue(-5);wait(app,lambda:dialog.checked is not None)
        assert dialog.apply_button.isEnabled() and not dialog.viewport.collision_button.isVisible()
    finally:dispose(app,dialog)


def test_joint_motion_cannot_tunnel_and_last_clear_rechecks(app):
    raw=swing().model_dump();dialog=JointDriveDialog(None,raw);dialog.resize(900,650);dialog.show()
    try:
        dialog.inputs[('hinge','rz')].setValue(90);wait(app,lambda:dialog.checked is not None)
        assert dialog.travel['blocked'] and dialog.stop_button.isEnabled()
        assert not dialog.apply_button.isEnabled() and '관절 구동 중 간섭' in dialog.status.text()
        dialog.accept();assert dialog.alive
        dialog.stop_button.click();wait(app,lambda:dialog.checked is not None)
        assert not dialog.travel['blocked'] and dialog.apply_button.isEnabled()
        assert dialog.checked.mates[0].rz<0 and raw==swing().model_dump()
    finally:dispose(app,dialog)


def test_print_preview_blocks_out_of_bed_and_exports_checked_shape(app,monkeypatch,tmp_path):
    from cadstudio.native.print_dialog import QFileDialog
    raw=blocks().model_dump();before=deepcopy(raw);dialog=PrintDialog(None,raw);dialog.show()
    try:
        dialog.bed[0].setValue(2);wait(app,lambda:dialog.checked is not None)
        assert dialog.warnings and not dialog.apply_button.isEnabled()
        dialog.bed[0].setValue(100);wait(app,lambda:dialog.checked is not None)
        path=tmp_path/'plate.stl';monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a: (str(path),'STL'))
        dialog.apply_button.click();wait(app,lambda:not dialog.running)
        assert path.is_file() and path.stat().st_size>84 and raw==before
        assert '저장 완료' in dialog.status.text()
    finally:dispose(app,dialog)


def test_draft_preview_switches_without_changing_design(app):
    before=preview(blocks(20));after=preview(blocks(40));dialog=DraftPreviewDialog(None,before,after,'B를 20 mm 이동');dialog.show()
    try:
        assert dialog.viewport.result is after
        dialog.mode.setCurrentIndex(1);app.processEvents();assert dialog.viewport.result is before
        dialog.mode.setCurrentIndex(0);app.processEvents();assert dialog.viewport.result is after
    finally:dialog.reject();app.processEvents()


def test_chat_and_codex_checkmark_only_after_verified_connection(app,monkeypatch,tmp_path):
    from cadstudio.native import window,codex_connection,ai_chat
    from cadstudio.native.model_picker import LocalModelPicker
    monkeypatch.setattr(LocalModelPicker,'refresh',lambda self:None);monkeypatch.setattr(window,'DATA_DIR',tmp_path)
    monkeypatch.setattr(codex_connection,'settings',lambda:dict(model='test-model',executable='test.exe'))
    w=window.MainWindow();w.show();w.show_error=lambda text: (_ for _ in ()).throw(AssertionError(text))
    try:
        w.provider.setCurrentIndex(w.provider.findData('codex'));assert '✓' not in w.codex_status.text()
        monkeypatch.setattr(codex_connection,'connect',lambda *a,**k:dict(account={'plan':'pro'},models=[dict(model='test-model',efforts=['medium'])],executable='test.exe'))
        w.codex_check_button.click();wait(app,lambda:w.codex_probe_task is None)
        assert '✓' in w.codex_status.text() and '연결 완료' in w.codex_status.text()
        def fail(*a,**k):raise ValueError('login required')
        monkeypatch.setattr(codex_connection,'connect',fail);w.codex_check_button.click();wait(app,lambda:w.codex_probe_task is None)
        assert '✓' not in w.codex_status.text() and '실패' in w.codex_status.text()
        monkeypatch.setattr(ai_chat,'answer',lambda *a,**k:'질문에 대한 답변')
        w.ai_mode.setCurrentIndex(w.ai_mode.findData('chat'));w.prompt.setPlainText('필렛은 뭐야?');w.generate_draft();wait(app,lambda:w.ai_task is None)
        assert w.document.design is None and w.last_draft is None and not w.accept_draft.isEnabled()
        assert '질문에 대한 답변' in w.ai_result.toPlainText() and len(w.chat_history)==2
    finally:w.document.dirty=False;w.close();app.processEvents()
