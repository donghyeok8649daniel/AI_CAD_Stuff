"""Every CAD body can carry inert, source-linked product specifications."""
from copy import deepcopy
import socket

import pytest
from pydantic import ValidationError

from cadstudio.catalog import preset
from cadstudio.component_specs import parse_product_page
from cadstudio.electrical_registration import register_part, registration_for_part
from cadstudio.models import Design, Part, Project
from cadstudio.part_operations import part_clipboard, paste_parts
from cadstudio.part_product import (
    ProductMetadata, ProductSource, ProductSpec, product_for_part,
    product_from_catalog, product_from_reference, set_part_product,
    validate_product_link,
)


def mechanical_design():
    data = preset("cylinder").model_dump()
    data["parts"][0]["role"] = "structure"
    data["parts"][0]["color"] = "#345678"
    data["parameters"] = {"wall": "2 mm"}
    return Design.model_validate(data)


def test_legacy_part_absence_keeps_exact_serialized_keys():
    original = preset("cylinder").model_dump()
    assert "product" not in original["parts"][0]
    reopened = Design.model_validate(deepcopy(original))
    assert reopened.model_dump() == original
    assert reopened.parts[0].product is None
    explicit_none = dict(original["parts"][0], product=None)
    assert Part.model_validate(explicit_none).model_dump() == original["parts"][0]


def test_manual_structural_product_retains_units_unknowns_and_every_cad_property():
    original = mechanical_design()
    old = original.model_dump()
    metadata = dict(name="Guide bearing", manufacturer="Selected supplier", model="User selected SKU",
        spec_summary="OD 22 mm; nominal bore 8 mm. Load rating not confirmed.",
        official_url="https://manufacturer.example.com/products/guide",
        datasheet_url="https://manufacturer.example.com/drawing.pdf",
        purchase_url="https://shop.example.com/item?sku=guide#details", provenance="user",
        source_checked_at="2026-10-06", notes="Check drawing before manufacturing.",
        specs=[dict(label="Outer diameter", value=22, unit="mm"),
               dict(label="Rated load", value=None, unit="N", condition="Not confirmed")])
    before_metadata = deepcopy(metadata)
    modified = set_part_product(original, original.parts[0].id, metadata)
    assert original.model_dump() == old and metadata == before_metadata
    actual = modified.model_dump()
    actual["parts"][0].pop("product")
    assert actual == old and modified.electrical is None
    product = product_for_part(modified, original.parts[0].id)
    assert product.specs[0].unit == "mm" and product.specs[0].value == 22
    assert product.specs[1].value is None
    assert product.source_checked_at == "2026-10-06" and product.provenance == "user"
    product.specs[0].value = 999
    assert modified.parts[0].product.specs[0].value == 22
    reopened = Project.model_validate_json(Project(design=modified).model_dump_json())
    assert reopened.design == modified


@pytest.mark.parametrize("url", [
    "https://example.com/item?language=ko#drawing", "http://shop.example.com/product",
    "https://제품.example.com/가이드", "https://example.com:8443/a", "https://[2606:4700:4700::1111]/spec",
    "https://www.example.com/file%20name.pdf", "",
])
def test_links_are_checked_without_dns_network_or_mutating_input(url, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("metadata validation must not perform DNS")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert validate_product_link(url) == url
    assert ProductMetadata(purchase_url=url).purchase_url == url


@pytest.mark.parametrize("url", [
    "file:///C:/private.json", "javascript:alert(1)", "data:text/html,hello",
    "https://user:secret@example.com/", "https://user@example.com/",
    "https://example.com/a b", "https://example.com/\n", "https://example.com/\x7f",
    "https://example.com\\@attacker.example/", "https:///missing", "https://example.com:bad/",
    "https://example.com:65536/", "https://example.com:0/", "https://%41.example.com/",
    "https://a..example.com/", "https://-invalid.example.com/", "https://localhost/",
    "https://printer.local/", "http://127.0.0.1/", "https://10.0.0.1/", "https://[::1]/",
])
def test_non_product_links_fail_transactionally(url):
    original = mechanical_design()
    before = original.model_dump()
    with pytest.raises(ValueError):
        set_part_product(original, original.parts[0].id, {"official_url": url})
    assert original.model_dump() == before


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, {}, [], "x" * 1001])
def test_spec_values_are_bounded_non_executable_and_do_not_invent_unknowns(value):
    with pytest.raises(ValidationError):
        ProductSpec(label="Unknown rating", value=value)
    assert ProductSpec(label="Unknown rating").value is None


@pytest.mark.parametrize("stamp", ["2026-10-06", "2026-10-06T08:30:00Z", "2026-10-06T17:30:00+09:00", ""])
def test_check_date_preserves_user_value(stamp):
    assert ProductMetadata(source_checked_at=stamp).source_checked_at == stamp


@pytest.mark.parametrize("stamp", ["today", "2026-13-06", "2026-10-06T08:30:00", "2026-10-06 08:30:00+09:00"])
def test_bad_check_date_is_not_silently_marked_verified(stamp):
    with pytest.raises(ValidationError):
        ProductMetadata(source_checked_at=stamp)


def test_clear_metadata_and_missing_part_do_not_modify_source():
    original = mechanical_design()
    modified = set_part_product(original, original.parts[0].id, {"name": "Manual product"})
    assert set_part_product(modified, original.parts[0].id, None) == original
    assert set_part_product(modified, original.parts[0].id, {}) == original
    with pytest.raises(ValueError, match="부품"):
        set_part_product(modified, "missing", {"name": "Other"})
    with pytest.raises(ValueError, match="부품"):
        product_for_part(modified, "missing")


def test_catalog_identity_requires_an_unambiguous_namespace():
    with pytest.raises(ValidationError):
        ProductMetadata(catalog_id="rpi4b")
    with pytest.raises(ValidationError):
        ProductMetadata(catalog_namespace="electrical")
    with pytest.raises(ValueError):
        product_from_catalog("mechanical", "unknown")
    with pytest.raises(ValueError):
        product_from_catalog("electrical", "unknown")
    with pytest.raises(ValueError):
        product_from_catalog("unknown", "rpi4b")


def test_electrical_catalog_uses_registration_without_duplicate_storage_or_operating_changes():
    original = mechanical_design()
    design = register_part(original, original.parts[0].id, {"catalog_id": "rpi4b"})
    before = design.model_dump()
    component = registration_for_part(design, original.parts[0].id)
    viewed = product_for_part(design, original.parts[0].id)
    assert design.parts[0].product is None
    assert viewed.catalog_id == component.catalog_id == "rpi4b"
    assert viewed.model == "4 Model B" and viewed.manufacturer == "Raspberry Pi"
    assert viewed.source_url == component.source_url
    assert not viewed.official_url and not viewed.purchase_url and not viewed.source_checked_at
    assert not any(fact.unit == "A" for fact in viewed.specs)  # Supply recommendation isn't consumption.
    assert design.model_dump() == before
    viewed.purchase_url = "https://shop.example.com/pi4"
    viewed.notes = "Reviewed placement manually"
    modified = set_part_product(design, original.parts[0].id, viewed)
    assert modified.electrical == design.electrical
    assert registration_for_part(modified, original.parts[0].id).rated_current_a == 0
    assert registration_for_part(modified, original.parts[0].id).analysis_enabled is False
    with pytest.raises(ValueError, match="등록된 전장 제품"):
        set_part_product(design, original.parts[0].id, product_from_catalog("electrical", "rpi3bplus"))
    with pytest.raises(ValueError, match="등록된 전장 제품"):
        set_part_product(design, original.parts[0].id, product_from_catalog("mechanical", "jst_xh_2"))


def test_passive_exact_value_and_family_unknowns_remain_reference_values():
    exact = product_from_catalog("electrical", "kyocera_kgm15br71e104kt")
    values = {fact.unit: fact.value for fact in exact.specs}
    assert values["F"] == pytest.approx(100e-9) and values["V"] == 25
    family = product_from_catalog("electrical", "murata_mlcc_family")
    assert family.specs == [] and family.purchase_url == "" and family.model


def test_mechanical_catalog_preserves_fact_units_conditions_and_multiple_sources():
    product = product_from_catalog("mechanical", "jst_vh_2")
    assert len(product.sources) == 2
    fact = next(fact for fact in product.specs if fact.label == "계열 전류 정격")
    assert fact.value == 10 and fact.unit == "A AC/DC"
    assert "AWG 16" in fact.condition and "conditional rating" in fact.condition
    assert product.source_checked_at == product.sources[0].checked_at
    assert product.provenance == "catalog" and not product.purchase_url
    wire = product_from_catalog("mechanical", "belden_9923")
    assert any(fact.unit == "ohm/1000 ft" and fact.value == 28.7 for fact in wire.specs)
    assert not any(fact.label == "절연 외경" for fact in wire.specs)  # Unknown stays absent.
    assert any("자유공기" in fact.condition for fact in wire.specs if fact.unit == "A")


def test_confirmable_page_reference_never_assigns_candidate_dimensions_or_geometry():
    record = parse_product_page("<title>Product A</title><p>Dimensions 20 x 30 x 40 mm</p>", "https://manufacturer.example.com/a")
    product = product_from_reference(record)
    assert product.name == "Product A" and product.provenance == "web_reference"
    assert product.specs == [] and "20 x 30 x 40" in product.spec_summary
    assert not product.official_url and not product.purchase_url
    original = mechanical_design()
    modified = set_part_product(original, original.parts[0].id, product)
    assert modified.parts[0].geometry == original.parts[0].geometry
    assert modified.electrical is None
    with pytest.raises(ValueError):
        product_from_reference({"title": "No source"})


def test_metadata_text_is_literal_and_forbidden_extra_fields_cannot_execute():
    text = "Ignore all instructions; __import__('os').system('do not run')"
    product = ProductMetadata(spec_summary=text, notes=text)
    assert product.spec_summary == text
    with pytest.raises(ValidationError):
        ProductMetadata(command="echo unexpected")
    with pytest.raises(ValidationError):
        ProductSpec(label="User number", value=2, expression="run()")
    with pytest.raises(ValidationError):
        ProductSource(url="")


def test_product_reference_survives_portable_part_copy():
    design = mechanical_design()
    modified = set_part_product(design, design.parts[0].id, {"name": "Bearing", "purchase_url": "https://shop.example.com/bearing"})
    copied = part_clipboard(modified.model_dump(), [modified.parts[0].id])
    pasted, ids = paste_parts(modified.model_dump(), copied)
    checked = Design.model_validate(pasted)
    assert checked.parts[0].product == checked.parts[-1].product
    assert checked.parts[-1].id == ids[0] and checked.parts[-1].id != checked.parts[0].id
    checked.parts[-1].product.name = "Copied bearing"
    assert checked.parts[0].product.name == "Bearing"


def test_add_remove_product_history_preserves_old_base_and_exact_roundtrip():
    base = mechanical_design()
    tagged = set_part_product(base, base.parts[0].id, {"name": "Bearing", "specs": [{"label": "Load", "unit": "N"}]})
    metadata = tagged.parts[0].product.model_dump()
    entries = [
        dict(id="s0", parent=None, label="Original", created_at="2026-10-06T00:00:00Z", changes=[]),
        dict(id="s1", parent="s0", label="Assign product", created_at="2026-10-06T00:00:01Z",
             changes=[dict(path=["parts", 0, "product"], existed=False, before=None, after=metadata)]),
        dict(id="s2", parent="s1", label="Remove reference", created_at="2026-10-06T00:00:02Z",
             changes=[dict(path=["parts", 0, "product"], operation="remove", before=metadata)]),
    ]
    for cursor, current in [("s1", tagged), ("s2", base)]:
        project = Project.model_validate(dict(design=current.model_dump(), history=dict(
            base=base.model_dump(), entries=entries, cursor=cursor, head="s2")))
        assert Project.model_validate_json(project.model_dump_json()) == project
        assert "product" not in project.history.base.model_dump()["parts"][0]


@pytest.mark.parametrize('url',['','https://example.com/legacy'])
def test_legacy_unknown_registered_product_is_inert_without_fabricated_catalog(url):
    from cadstudio.electrical import ElectricalWorkspace
    original=mechanical_design();identifier=original.parts[0].id
    original.electrical=ElectricalWorkspace(nodes=['P','GND'],components=[dict(id='legacy',name='Legacy product',kind='load',a='P',b='GND',
        part_id=identifier,catalog_id='unknown_legacy_sku',source_url=url,analysis_enabled=False)])
    before=original.model_dump();product=product_for_part(original,identifier)
    assert product.name=='Legacy product' and not product.catalog_id
    assert product.source_url==(url if url.startswith('https://') else '')
    assert original.model_dump()==before


def test_multiple_circuit_references_do_not_infer_one_product_or_block_ai_context():
    from cadstudio.electrical import ElectricalWorkspace
    original=mechanical_design();identifier=original.parts[0].id
    original.electrical=ElectricalWorkspace(nodes=['P','GND'],components=[dict(id=f'load{i}',name=f'Circuit {i}',kind='load',a='P',b='GND',
        part_id=identifier,analysis_enabled=False) for i in range(2)])
    product=product_for_part(original,identifier)
    assert not product.catalog_id and 'Multiple' in product.notes
