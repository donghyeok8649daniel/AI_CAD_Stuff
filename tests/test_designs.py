import json
import math
import struct
from collections import Counter

import cadquery as cq
import pytest
from pydantic import ValidationError

from cadstudio.catalog import catalog, preset
from cadstudio.kernel import build, export, preview
from cadstudio.models import Design, Extrusion, FlatSpecimen, Link, Plate, RoundSpecimen, Wafer


@pytest.mark.parametrize("kind", [item["kind"] for item in catalog()])
def test_presets_real_solids_step_and_stl_roundtrip(kind, tmp_path):
    design = preset(kind)
    shapes = build(design)
    assert all(s.isValid() and len(s.Solids()) == 1 and s.Volume() > 0 for s in shapes)
    result = preview(design)
    assert result["stats"]["valid"] and not result["stats"]["collisions"]
    for mesh in result["meshes"]:
        assert len(mesh["vertices"]) % 3 == 0 and len(mesh["triangles"]) % 3 == 0
        assert max(mesh["triangles"]) < len(mesh["vertices"]) // 3
        assert all(math.isfinite(v) for v in mesh["vertices"])
    step, stl = tmp_path / f"{kind}.step", tmp_path / f"{kind}.stl"
    export(design, step, "step")
    imported = cq.importers.importStep(str(step))
    assert len(imported.solids().vals()) == len(design.parts)
    assert all(s.isValid() for s in imported.solids().vals())
    assert sum(s.Volume() for s in imported.solids().vals()) == pytest.approx(sum(s.Volume() for s in shapes), rel=1e-7)
    assert "ISO-10303-21" in step.read_text()
    export(design, stl, "stl")
    data = stl.read_bytes()
    count = struct.unpack_from("<I", data, 80)[0]
    assert count > 0 and len(data) == 84 + count * 50
    volume = 0
    for i in range(count):
        values = struct.unpack_from("<12fH", data, 84 + i*50)
        a, b, c = values[3:6], values[6:9], values[9:12]
        volume += sum(a[k] * (b[(k+1)%3]*c[(k+2)%3]-b[(k+2)%3]*c[(k+1)%3]) for k in range(3)) / 6
    assert abs(volume) == pytest.approx(result["stats"]["volume"], rel=.012)


def test_analytic_volumes_and_gauge_section():
    g = RoundSpecimen()
    big, small = g.grip_diameter/2, g.gauge_diameter/2
    delta = small-big
    expected = math.pi*((g.length-g.gauge_length-2*g.transition_length)*big**2 + g.gauge_length*small**2 + 2*g.transition_length*(big**2+big*delta+13*delta**2/35))
    shape = build(preset("round_specimen"))[0]
    assert shape.Volume() == pytest.approx(expected, rel=1e-7)
    section = shape.intersect(cq.Workplane("XY").box(1, 40, 40).val())
    assert section.Volume() == pytest.approx(math.pi*small**2, rel=1e-7)
    g = FlatSpecimen()
    expected = g.thickness*((g.length-g.gauge_length-2*g.transition_length)*g.grip_width+g.gauge_length*g.gauge_width+g.transition_length*(g.grip_width+g.gauge_width))
    assert build(preset("flat_specimen"))[0].Volume() == pytest.approx(expected, rel=1e-7)


def test_holes_are_real_through_voids():
    link = preset("link")
    solid = build(link)[0]
    g = link.parts[0].geometry
    for x in (-g.hole_spacing/2, g.hole_spacing/2):
        probe = cq.Solid.makeCylinder(g.hole_diameter*.45, g.thickness, cq.Vector(x, 0, 0))
        assert solid.intersect(probe).Volume() == pytest.approx(0, abs=1e-6)
    plate = preset("plate");g = plate.parts[0].geometry
    assert build(plate)[0].Volume() == pytest.approx((g.length*g.width-g.hole_count*math.pi*(g.hole_diameter/2)**2)*g.thickness)


@pytest.mark.parametrize("model,changes", [
    (RoundSpecimen, {"gauge_diameter": 16}), (RoundSpecimen, {"length": 50}),
    (RoundSpecimen, {"length": float("nan")}), (FlatSpecimen, {"thickness": 0}),
    (Wafer, {"flat_depth": 30}), (Link, {"hole_spacing": 200}),
    (Link, {"hole_diameter": 30}), (Plate, {"hole_count": 3}),
    (Plate, {"hole_pitch_x": 2}), (Plate, {"length": -3}),
])
def test_invalid_dimensions_rejected(model, changes):
    with pytest.raises(ValidationError):
        model(**changes)


def test_design_rejects_executable_or_unbounded_content():
    design = preset("wafer").model_dump()
    for field, value in [("units", "inch"), ("script", "print('injected')")]:
        with pytest.raises(ValidationError):
            Design.model_validate({**design, field: value})
    design["parts"][0]["geometry"]["kind"] = "python"
    with pytest.raises(ValidationError):
        Design.model_validate(design)
    design = preset("wafer").model_dump()
    design["parts"] *= 13
    with pytest.raises(ValidationError):
        Design.model_validate(design)


def test_extrusion_polygon_validation_and_volume():
    g = Extrusion(points=[{"x": -20, "y": -15}, {"x": 20, "y": -15}, {"x": 20, "y": 15}, {"x": -20, "y": 15}], holes=[{"x": 0, "y": 0, "diameter": 6}], thickness=4)
    d = preset("extrusion").model_dump();d["parts"][0]["geometry"] = g.model_dump()
    assert build(Design.model_validate(d))[0].Volume() == pytest.approx((40*30-math.pi*9)*4)
    for changes in [
        {"points": [{"x":0,"y":0},{"x":20,"y":20},{"x":0,"y":20},{"x":20,"y":0}]},
        {"holes": [{"x":100,"y":0,"diameter":6}]},
        {"holes": [{"x":0,"y":0,"diameter":6},{"x":1,"y":0,"diameter":6}]},
        {"points": [{"x":0,"y":0},{"x":20,"y":0},{"x":40,"y":0}]},
    ]:
        with pytest.raises(ValidationError):
            Extrusion.model_validate({**g.model_dump(), **changes})


def test_transform_order_and_collision_detection():
    d = preset("plate").model_dump();d["parts"][0]["transform"] = {"x":100,"y":20,"z":5,"rx":0,"ry":0,"rz":90}
    shape = build(Design.model_validate(d))[0]
    assert shape.Center().x == pytest.approx(100)
    assert shape.Center().y == pytest.approx(20)
    assert shape.Center().z == pytest.approx(8)
    second = json.loads(json.dumps(d["parts"][0]));second["id"] = "second";d["parts"].append(second)
    collisions = preview(Design.model_validate(d))["stats"]["collisions"]
    assert len(collisions) == 1
    assert collisions[0]["volume"] == pytest.approx(shape.Volume())
