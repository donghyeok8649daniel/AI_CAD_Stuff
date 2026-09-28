from copy import deepcopy
from cadstudio.native.joint_alignment_dialog import JointAlignmentDialog
from test_joint_alignment import eccentric,selected
from test_placement_native import app,wait,dispose


def test_select_both_axes_preview_and_cancel_without_document_change(app):
    raw=eccentric().model_dump();before=deepcopy(raw);pi,ci=selected(raw);dialog=JointAlignmentDialog(None,raw,'j');dialog.show()
    try:
        wait(app,lambda:dialog.faces_for=='j')
        assert not dialog.apply_button.isEnabled()
        dialog.parent_face.setCurrentIndex(dialog.parent_face.findData(pi));wait(app,lambda:not dialog.timer.isActive() and not dialog.running)
        assert dialog.parent_face.currentData()==pi and not dialog.apply_button.isEnabled()
        dialog.child_face.setCurrentIndex(dialog.child_face.findData(ci));wait(app,lambda:dialog.alignment is not None)
        assert dialog.apply_button.isEnabled() and '1.6000 mm' in dialog.detail.text()
        assert not dialog.result['stats']['collisions']
        dialog.reject();assert raw==before
    finally:dispose(app,dialog)
