"""Draft requests own mutable designs before nested assembly validation."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from cadstudio.mechanisms import four_bar
from cadstudio.models import Design, DraftRequest, Part


def test_typed_closed_loop_request_preserves_exact_caller_and_owns_graph():
    current = four_bar()
    before = current.model_dump()
    request = DraftRequest(prompt="Move the independent input joint", current=current)
    assert current.model_dump() == before
    assert request.current is not current
    assert all(owned is not original for owned, original
               in zip(request.current.parts, current.parts))
    assert all(owned is not original for owned, original
               in zip(request.current.mates, current.mates))
    assert all(owned is not original for owned, original
               in zip(request.current.loops, current.loops))
    assert request.current.loops == current.loops
    assert [part.geometry for part in request.current.parts] == [part.geometry for part in current.parts]
    request.current.mates[0].rz = -60
    request.current.parts[1].transform.x += 1
    request.current.loops[0].offset[0] = 3
    assert current.model_dump() == before


def test_failed_request_validation_preserves_exact_typed_closed_loop_input():
    current = four_bar()
    before = current.model_dump()
    with pytest.raises(ValidationError):
        DraftRequest(prompt="", current=current)
    assert current.model_dump() == before


def test_raw_closed_loop_dictionary_preserved_exactly():
    raw = four_bar().model_dump()
    before = deepcopy(raw)
    request = DraftRequest(prompt="Review this mechanism", current=raw)
    assert raw == before
    request.current.mates[0].rz = 120
    request.current.parts[1].transform.x += 2
    assert raw == before


def test_raw_dictionary_with_nested_typed_members_preserves_original_graph():
    current = four_bar()
    before = current.model_dump()
    raw = dict(parts=list(current.parts), mates=list(current.mates), loops=list(current.loops))
    request = DraftRequest(prompt="Review nested typed inputs", current=raw)
    assert current.model_dump() == before
    assert all(owned is not original for owned, original
               in zip(request.current.parts, current.parts))
    assert all(owned is not original for owned, original
               in zip(request.current.mates, current.mates))
    request.current.mates[0].rz = 45
    assert current.model_dump() == before


def bound_raw_design():
    raw = Design(parts=[Part(id="base", name="Base", fixed=True,
                             geometry={"kind": "plate", "length": 80, "hole_count": 0})]).model_dump()
    raw["parameters"] = {"length": "100 mm"}
    raw["dimension_bindings"] = [{"path": ["parts", "base", "geometry", "length"],
                                  "expression": "length"}]
    return raw


def test_raw_parameter_evaluation_has_private_copy_before_numeric_changes():
    raw = bound_raw_design()
    before = deepcopy(raw)
    request = DraftRequest(prompt="Review bound dimensions", current=raw)
    assert request.current.parts[0].geometry.length == 100
    assert raw == before and raw["parts"][0]["geometry"]["length"] == 80
    request.current.parameters["length"] = "120 mm"
    assert raw == before


def test_rejected_raw_parameter_expression_leaves_input_dictionary_exact():
    raw = bound_raw_design()
    raw["dimension_bindings"][0]["expression"] = "length / 0"
    before = deepcopy(raw)
    with pytest.raises(ValidationError):
        DraftRequest(prompt="Review invalid dimensions", current=raw)
    assert raw == before
