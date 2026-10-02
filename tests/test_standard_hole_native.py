import math
import pytest
from cadstudio.models import Design,Part
from cadstudio.kernel import preview
from cadstudio.mechanical_catalog import get_clearance_hole
from cadstudio.native.inspect_tools import HoleDialog
from test_placement_native import app,wait,dispose


def test_sourced_hole_creates_actual_cut_and_preserves_nominal_source(app):
    raw=Design(parts=[Part(id='plate',name='Plate',geometry=dict(kind='plate',length=40,
                     width=40,thickness=8,hole_count=0))]).model_dump()
    initial=preview(Design.model_validate(raw))
    face=next(f for f in initial['meshes'][0]['faces'] if f.get('normal')==[0,0,1])
    dialog=HoleDialog(None,raw,'plate',face)
    dialog.show()
    try:
        dialog.set_standard(get_clearance_hole('M4'))
        wait(app,lambda:dialog.checked is not None and not dialog.timer.isActive() and not dialog.running)
        result=preview(dialog.checked)
        assert dialog.diameter.value()==4.5 and dialog.through.isChecked()
        assert result['stats']['volume']==pytest.approx(40*40*8-math.pi*(4.5/2)**2*8)
        record=dialog.standard_record()
        assert record['nominal_diameter_mm']==4.5 and not record['user_override']
        assert record['standard']=='ISO 273:1979' and record['source_url'].startswith('https://')
        dialog.diameter.setValue(5)
        assert dialog.standard_record()['user_override']
        assert dialog.standard_record()['nominal_diameter_mm']==4.5
        assert raw['parts'][0]['features']==[]
    finally:dispose(app,dialog)
