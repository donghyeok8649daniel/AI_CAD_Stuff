import pytest
from cadstudio.native.display_style import DisplayStyle,DisplayPreferences,DisplayStyleDialog,preferences
from cadstudio.native.viewport import CADViewport
from cadstudio.native.sketch import SketchEditor
from test_placement_native import app


def test_saved_appearance_roundtrip_and_corruption_fallback(app,tmp_path):
    path=tmp_path/'display.json';prefs=DisplayPreferences(path)
    value=DisplayStyle(grid_color='#ffcc22',grid_width=3,axes_width=4,grid_brightness=65,axes_brightness=75)
    prefs.set(value,persist=True);assert DisplayPreferences(path).style==value
    path.write_text('{bad',encoding='utf-8');assert DisplayPreferences(path).style==DisplayStyle()
    with pytest.raises(ValueError):prefs.set(dict(grid_width=float('nan')))
    with pytest.raises(ValueError):prefs.set(dict(grid_color='invalid'))


def test_live_appearance_reaches_3d_and_sketch_cancel_restores(app,tmp_path):
    prefs=preferences();original=prefs.style.model_copy(deep=True);oldpath=prefs.path;prefs.path=tmp_path/'display.json'
    view=CADViewport();editor=SketchEditor();editor.start(None,{'plane':'XY'});view.resize(600,400);view.show();editor.resize(800,600);editor.show();app.processEvents()
    dialog=DisplayStyleDialog();dialog.show()
    try:
        dialog.set_value('grid_color','#ff0000');dialog.fields['grid_width'].setValue(3);dialog.fields['grid_brightness'].setValue(65);dialog.fields['axes_width'].setValue(4);dialog.set_value('x_color','#abcdef');app.processEvents()
        assert view.grid_actor.GetProperty().GetLineWidth()==3
        assert view.grid_actor.GetProperty().GetOpacity()==pytest.approx(.65)
        assert view.axes.GetXAxisShaftProperty().GetLineWidth()==4
        assert editor.canvas.display_prefs.style.grid_color=='#ff0000'
        assert not editor.canvas.grab().isNull()
        view.make_grid(250);assert view.grid_actor.GetProperty().GetLineWidth()==3
        view.show_grid(False);view.show_axes(False);dialog.fields['axes_width'].setValue(2.5);app.processEvents()
        assert not view.grid_actor.GetVisibility() and not view.axes_widget.GetEnabled()
        dialog.reject();assert prefs.style==original and not prefs.path.exists()
        second=DisplayStyleDialog();second.fields['grid_width'].setValue(2.5);second.accept()
        assert DisplayPreferences(prefs.path).style.grid_width==2.5
    finally:
        if dialog.isVisible():dialog.reject()
        prefs.set(original);prefs.path=oldpath;editor.stop();editor.close();view.shutdown();view.close();app.processEvents()
