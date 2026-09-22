import pytest

from cadstudio.catalog import preset
from cadstudio.kernel import preview


@pytest.mark.parametrize("neck", [5, 6, 8, 12])
def test_curve_bounding_box_does_not_depend_on_display_tessellation(neck):
    design = preset("round_specimen")
    data = design.model_dump()
    data["parts"][0]["geometry"]["gauge_diameter"] = neck
    design = type(design).model_validate(data)
    result = preview(design)
    assert result["stats"]["bounds"] == pytest.approx([100, 16, 16], abs=1e-5)
