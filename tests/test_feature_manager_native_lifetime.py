"""Suppression must retain the Qt item currently emitting itemChanged."""

from copy import deepcopy
import time

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QThreadPool, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cadstudio.kernel import build
from cadstudio.models import Design, Part, SolidFeature
from cadstudio.native.feature_manager import FeatureManager


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    yield instance
    assert QThreadPool.globalInstance().waitForDone(10000)
    instance.processEvents()


def patterned_design():
    features = [
        SolidFeature(id="along_x", name="X copies", operation="linear_pattern", spacing=[35, 0, 0]),
        SolidFeature(id="along_z", name="Z copies", operation="linear_pattern", spacing=[0, 0, 25], support_feature="along_x"),
        SolidFeature(id="along_x_again", name="More X copies", operation="linear_pattern", spacing=[70, 0, 0], support_feature="along_z"),
    ]
    return Design(parts=[Part(id="part", name="Patterned part",
                              geometry=dict(kind="cylinder", diameter=10, height=5),
                              features=features)]).model_dump()


def wait(app, predicate):
    deadline = time.monotonic() + 30
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), "Feature preview did not settle"


def show(app, raw):
    dialog = FeatureManager(None, raw, "part")
    dialog.show()
    wait(app, lambda: dialog.checked is not None and not dialog.running and not dialog.timer.isActive())
    return dialog


def dispose(app, dialog):
    dialog.reject()
    assert QThreadPool.globalInstance().waitForDone(10000)
    dialog.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def suppressed(dialog):
    return [feature.get("suppressed", False) for feature in dialog.features()]


def test_emitting_item_and_other_rows_survive_following_suppression_and_restore(app):
    original = patterned_design()
    before = deepcopy(original)
    dialog = show(app, original)
    try:
        rows = [dialog.list.item(index) for index in range(3)]
        native_pointers = [shiboken6.getCppPointer(item)[0] for item in rows]
        emitting = rows[1]
        observed = []
        dialog.list.itemChanged.connect(lambda item: observed.append(
            (item is emitting, shiboken6.isValid(item), shiboken6.getCppPointer(item)[0], dialog.timer.isActive())))
        initial_volume = build(dialog.checked)[0].Volume()
        emitting.setCheckState(Qt.CheckState.Unchecked)
        # Check immediately within the setter's event cycle, before a timer or
        # replacement graphics can conceal deletion of the emitting item.
        assert observed == [(True, True, native_pointers[1], True)]
        assert suppressed(dialog) == [False, True, True]
        assert [dialog.list.item(index) for index in range(3)] == rows
        assert all(shiboken6.isValid(item) for item in rows)
        assert [shiboken6.getCppPointer(item)[0] for item in rows] == native_pointers
        assert dialog.list.currentRow() == 1 and dialog.checked is None
        wait(app, lambda: dialog.checked is not None and not dialog.running)
        assert build(dialog.checked)[0].Volume() == pytest.approx(initial_volume / 4)
        emitting.setCheckState(Qt.CheckState.Checked)
        assert observed[-1] == (True, True, native_pointers[1], True)
        assert len(observed) == 2  # Updating following rows creates no recursion.
        assert suppressed(dialog) == [False, False, False]
        wait(app, lambda: dialog.checked is not None and not dialog.running)
        assert build(dialog.checked)[0].Volume() == pytest.approx(initial_volume)
        assert original == before
    finally:
        dispose(app, dialog)


def test_native_checkbox_click_suppresses_only_selected_feature_when_following_is_off(app):
    dialog = show(app, patterned_design())
    try:
        dialog.following.setChecked(False)
        rows = [dialog.list.item(index) for index in range(3)]
        emitting = rows[1]
        initial_volume = build(dialog.checked)[0].Volume()
        # Use the actual delegate's check box, rather than calling the slot.
        point = dialog.list.visualItemRect(emitting).center()
        point.setX(10)
        QTest.mouseClick(dialog.list.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert emitting.checkState() == Qt.CheckState.Unchecked
        assert suppressed(dialog) == [False, True, False]
        assert dialog.list.item(1) is emitting and shiboken6.isValid(emitting)
        assert [dialog.list.item(index) for index in range(3)] == rows
        wait(app, lambda: dialog.checked is not None and not dialog.running)
        assert build(dialog.checked)[0].Volume() == pytest.approx(initial_volume / 2)
        emitting.setCheckState(Qt.CheckState.Checked)
        wait(app, lambda: dialog.checked is not None and not dialog.running)
        assert build(dialog.checked)[0].Volume() == pytest.approx(initial_volume)
    finally:
        dispose(app, dialog)


def test_repeated_toggle_keeps_original_native_items_and_one_pending_preview(app):
    dialog = show(app, patterned_design())
    try:
        rows = [dialog.list.item(index) for index in range(3)]
        emitting = rows[0]
        revision = dialog.revision
        changes = []
        dialog.list.itemChanged.connect(lambda item: changes.append(shiboken6.getCppPointer(item)[0]))
        pointer = shiboken6.getCppPointer(emitting)[0]
        for index in range(20):
            checked = index % 2 == 1
            emitting.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            assert suppressed(dialog) == [not checked] * 3
            assert all(shiboken6.isValid(item) for item in rows)
            assert [dialog.list.item(row) for row in range(3)] == rows
        assert changes == [pointer] * 20
        assert dialog.revision == revision + 20 and dialog.timer.isActive()
        wait(app, lambda: dialog.checked is not None and not dialog.running and not dialog.timer.isActive())
        assert not any(feature.suppressed for feature in dialog.checked.parts[0].features)
    finally:
        dispose(app, dialog)
