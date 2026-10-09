"""BOM repair has feasible grammars and fails impossible inputs before AI."""
import json

import pytest

from cadstudio.bom_design import BomInputRequired, bind_bom_part, parse_bom_text, preflight_bom_design, reconcile_bom
from cadstudio.electrical_registration import register_part
from cadstudio.kernel import preview
from cadstudio.models import Design, DraftRequest
from cadstudio.native.cad_schema import plan_schema
from cadstudio.native.cad_scope import Scope, expand_bom_scope
from cadstudio.native.cad_tools import execute_plan
from cadstudio.native.draft_repair import DraftRepair


def request(quantity=2, *, model=""):
    bom = parse_bom_text(f"Name,Quantity,Length mm,Width mm,Thickness mm,Model\nPlate,{quantity},80,60,4,{model}")
    return DraftRequest(prompt="BOM대로 설계", current=Design(bom=bom), bom=bom)


def body(identifier="a", **extra):
    return dict(id=identifier, name="Plate", geometry=dict(kind="plate", length=80, width=60, thickness=4, hole_count=0), **extra)


def one_instance(req, identifier="a"):
    return json.dumps(dict(summary="BOM", actions=[
        dict(tool="create", target=identifier, args=dict(name="Plate", geometry=body()["geometry"])),
        dict(tool="bom_bind", target=identifier, args=dict(item_id=req.bom.items[0].id)),
    ]))


@pytest.mark.parametrize("ids", [["a"], ["a", "b"]])
def test_single_part_selection_promotes_before_validation_and_expands_quantity(ids):
    req = request()
    scope = Scope.parse(json.dumps(dict(intent="part", tools=["create"], shapes=["plate"], new_parts=ids)), req)
    assert scope.intent == "assembly" and scope.tools == ("create", "bom_bind")
    assert len(scope.new_parts) == 2 and scope.new_parts[0] == "a"
    assert len(set(scope.new_parts)) == 2
    assert Scope.parse(json.dumps(dict(intent="part", tools=["create"], shapes=["plate"], new_parts=ids)), req) == scope
    schema = plan_schema(scope.tools, scope.shapes, new_parts=scope.new_parts)
    create = next(action for action in schema["properties"]["actions"]["items"]["anyOf"] if action["properties"]["tool"]["const"] == "create")
    assert create["properties"]["target"]["enum"] == list(scope.new_parts)


def test_initial_edit_scope_gets_create_for_missing_bodies_and_preserves_joint_ids():
    req = request(3)
    scope = Scope.parse(json.dumps(dict(intent="edit", tools=["joint"], shapes=[], new_parts=["a", "b"],
        connections=[dict(kind="rigid", parent="a", child="b")])), req)
    assert scope.intent == "assembly" and "create" in scope.tools and "bom_bind" in scope.tools
    assert len(scope.new_parts) == 3
    assert scope.connections[0]["parent"] == "a" and scope.connections[0]["child"] == "b"


@pytest.mark.parametrize("explicit_ids", [(), ("a",)])
def test_renderable_quantity_repair_expands_nonempty_and_fallback_scopes(explicit_ids):
    req = request()
    content = one_instance(req)
    result = execute_plan(content, req)
    repair = DraftRepair(req)
    scope = Scope(tools=("create", "bom_bind"), shapes=("plate",), intent="assembly", new_parts=explicit_ids)
    with pytest.raises(ValueError, match="BOM reconciliation"):
        repair.check(result, preview(result.design), content, scope)
    retained = repair.pending("codex", 1)
    assert retained["validation"]["status"] == "needs_repair"
    assert len(retained["repair"]["scope"]["new_parts"]) == 2
    assert retained["repair"]["scope"]["new_parts"][0] == "a"
    next_scope, messages = repair.next(scope, content, "retry")
    assert next_scope.new_parts == tuple(retained["repair"]["scope"]["new_parts"])
    assert next_scope.new_parts[1] in messages[0]["content"]


def test_unbound_rendered_bodies_can_be_bound_without_duplicate_creates():
    req = request()
    candidate = Design(parts=[body("a"), body("b")], bom=req.bom)
    scope = Scope(tools=("create",), shapes=("plate",), intent="assembly", new_parts=("a", "b"))
    expanded = expand_bom_scope(scope, req, candidate)
    assert expanded.new_parts == ("a", "b")


def test_more_than_32_remaining_instances_fails_before_subscription_session(monkeypatch):
    from cadstudio.native.codex_ai import generate
    calls = []
    def forbidden_session(*args, **kwargs):
        calls.append(True)
        pytest.fail("impossible BOM reached provider")
    with pytest.raises(BomInputRequired, match="32"):
        generate(request(33), "not-reached", session_factory=forbidden_session)
    assert calls == []


def test_bound_instances_reduce_remaining_budget_without_name_matching():
    req = request(33)
    baseline = Design(parts=[body()], bom=req.bom)
    req.current = bind_bom_part(baseline, req.bom, req.bom.items[0].id, "a")
    assert preflight_bom_design(req)["remaining"] == 32
    unbound = request(33)
    unbound.current = baseline
    with pytest.raises(BomInputRequired, match="32"):
        DraftRepair(unbound)


@pytest.mark.parametrize("quantity,existing", [(257, 0), (32, 225)])
def test_project_body_capacity_has_explicit_input_needed_error(quantity, existing):
    req = request(quantity)
    if existing:
        req.current = Design(parts=[body(f"old_{index}") for index in range(existing)], bom=req.bom)
    with pytest.raises(BomInputRequired, match="256"):
        DraftRepair(req)


def test_linked_conflicting_product_requires_metadata_correction_before_provider():
    req = request(1, model="Exact-SKU")
    req.current = bind_bom_part(Design(parts=[body(product=dict(model="Different-SKU"))], bom=req.bom), req.bom, req.bom.items[0].id, "a")
    assert req.current.parts[0].product.model == "Different-SKU"
    with pytest.raises(BomInputRequired, match="제품 정보"):
        DraftRepair(req)


def test_existing_electrical_registration_cannot_be_overruled_by_bom_label():
    bom = parse_bom_text("Name,Quantity,Model,Catalog ID,Catalog namespace,Length mm\nBoard,1,4 Model B,rpi4b,electrical,80")
    initial = register_part(Design(parts=[body()], bom=bom), "a", dict(catalog_id="rpi5", analysis_enabled=False))
    linked = bind_bom_part(initial, bom, bom.items[0].id, "a")
    assert linked.parts[0].product.catalog_id == "rpi4b"
    assert not reconcile_bom(linked).all_matched
    req = DraftRequest(prompt="BOM대로 설계", current=linked, bom=bom)
    with pytest.raises(BomInputRequired, match="전장 등록"):
        DraftRepair(req)


def test_unknown_values_keep_preflight_pending_and_bom_source_unchanged():
    bom = parse_bom_text("Name,Quantity\nConcept,")
    req = DraftRequest(prompt="BOM 개념 설계", current=Design(bom=bom), bom=bom)
    before = req.model_dump()
    assert preflight_bom_design(req)["remaining"] == 1
    assert req.model_dump() == before
