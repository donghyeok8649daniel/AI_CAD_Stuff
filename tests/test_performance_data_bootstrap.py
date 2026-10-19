import pytest
from cadstudio.performance_data_check import audit_toolkit_modules


def test_frozen_qtcore_relocation_is_distinct_from_gui_application():
    before={'sys','PySide6','PySide6.QtCore','PySide6.support','PySide6.support.signature'}
    report=audit_toolkit_modules(before,before|{'cadstudio.kernel'})
    assert report['added']==[] and report['preloaded']==sorted(before-{'sys'})


@pytest.mark.parametrize('name',['PySide6.QtWidgets','PySide6.QtGui','tkinter','pyautogui'])
def test_gui_toolkit_is_rejected_even_when_already_preloaded(name):
    with pytest.raises(AssertionError):audit_toolkit_modules({name},{name})


@pytest.mark.parametrize('name',['PySide6.QtCore','PySide6.QtWidgets','PyQt6.QtCore'])
def test_acceptance_cannot_import_toolkit_modules_after_dispatch(name):
    with pytest.raises(AssertionError):audit_toolkit_modules(set(),{name})
