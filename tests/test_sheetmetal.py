import math
import pytest
import ezdxf
from cadstudio.models import SheetMetalGeometry
from cadstudio.sheetmetal import construct_sheet,bend_allowance,flat_length,export_flat


@pytest.mark.parametrize('angle',[30,90,150])
def test_bend_and_flat_pattern_geometry(angle,tmp_path):
    g=SheetMetalGeometry(bend_angle=angle);solid=construct_sheet(g)
    expected=g.width*(g.length*g.thickness+g.flange_length*g.thickness+math.radians(angle)*((g.bend_radius+g.thickness)**2-g.bend_radius**2)/2)
    assert solid.isValid() and len(solid.Solids())==1 and solid.Volume()==pytest.approx(expected)
    flat=construct_sheet(g.model_copy(update={'flat':True}));assert flat.Volume()==pytest.approx(expected)
    g.k_factor=.33;assert bend_allowance(g)==pytest.approx(math.radians(angle)*(g.bend_radius+.33*g.thickness))
    export_flat(g,tmp_path/'blank.dxf');doc=ezdxf.readfile(tmp_path/'blank.dxf');assert len(doc.modelspace().query('LINE'))==2 and doc.units==4
