"""Exact G474 header expansion stays bound and preserves saved documents."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import cadstudio.board_pins as board_pins
from cadstudio.board_pins import BoardPin, board_pinout
from cadstudio.circuit_connections import add_schematic_wire, update_schematic_wire
from cadstudio.electrical_registration import register_part, registration_for_part
from cadstudio.firmware_bundle import (
    FirmwareBundle, create_binding, create_bundle, to_program_attachment,
    verify_bundle_binding,
)
from cadstudio.firmware_generation import build_context
from cadstudio.mcu_connections import connection_endpoints, pin_connections
from cadstudio.models import Design
from cadstudio.native.document import Document, read_project


CATALOG = "st_nucleo_g474re"
LEGACY_KEYS = ("PA5", "PA6", "PA7", "PB6", "PC7", "PB5")
NEW_CONNECTORS = {
    "PA11": "CN10.14", "PA12": "CN10.12", "PB10": "CN10.25",
    "PB11": "CN10.18", "PB12": "CN10.16", "PB8": "CN10.3",
    "PB9": "CN10.5", "PC6": "CN10.4", "PA8": "CN10.23",
    "PA9": "CN10.21", "PC0": "CN7.38", "PC1": "CN7.36",
    "PC2": "CN7.35", "PC3": "CN7.37", "PB0": "CN7.34",
    "PB1": "CN10.24",
}

# The pre-expansion catalog is frozen here, rather than recovered from a real
# project or inferred from the new catalog. It lets a synthetic old document
# exercise the actual before/after pin-map fingerprint without migrations.
LEGACY_ROWS = (
    ("NC_CN6_1", "CN6.1 · NC", ("Reserved for test",), "other", "left", 0),
    ("IOREF_CN6_2", "CN6.2 · IOREF", ("I/O reference",), "other", "left", 1),
    ("NRST_CN6_3", "CN6.3 · NRST", ("PG10-NRST reset",), "reset", "left", 2),
    ("3V3_CN6_4", "CN6.4 · 3V3", ("3.3 V input/output; SB5 and external-supply configuration must be checked",), "power", "left", 3),
    ("5V_CN6_5", "CN6.5 · 5V", ("5 V output rail; not automatically a safe external input",), "power", "left", 4),
    ("GND_CN6_6", "CN6.6 · GND", ("GND",), "ground", "left", 5),
    ("GND_CN6_7", "CN6.7 · GND", ("GND",), "ground", "left", 6),
    ("VIN_CN6_8", "CN6.8 · VIN", ("7–12 V input; power-source jumpers must be checked",), "power", "left", 7),
    ("PA5", "CN5.6 · D13 / PA5", ("GPIO", "SPI1_SCK", "LD2 via SB6; disconnect SB6 if using this candidate SPI clock"), "signal", "right", 0),
    ("PA6", "CN5.5 · D12 / PA6", ("GPIO", "SPI1_MISO"), "signal", "right", 1),
    ("PA7", "CN5.4 · D11 / PA7", ("GPIO", "SPI1_MOSI", "TIM3_CH2"), "signal", "right", 2),
    ("PB6", "CN5.3 · D10 / PB6", ("GPIO", "SPIx_CS", "TIM4_CH1"), "signal", "right", 3),
    ("PC7", "CN5.2 · D9 / PC7", ("GPIO", "TIM3_CH2 or TIM8_CH2"), "signal", "right", 4),
    ("PB5", "CN9.5 · D4 / PB5", ("GPIO",), "signal", "right", 5),
    ("GND_CN5_7", "CN5.7 · GND", ("GND",), "ground", "right", 6),
    ("E5V_CN7_6", "CN7.6 · E5V", ("External input 4.75–5.25 V; 500 mA maximum; JP5 pins 5–6; external supply before USB",), "power", "left", 8),
)


def registered_fixture():
    original = Design.model_validate(dict(name="Synthetic G474 header project", parts=[
        dict(id="g474_body", name="G474 CAD body", role="electrical",
             geometry=dict(kind="plate", length=82, width=70, thickness=2, hole_count=0)),
        dict(id="module_body", name="Manual terminal module", role="electrical",
             geometry=dict(kind="plate", length=50, width=50, thickness=2, hole_count=0)),
    ])).model_dump()
    raw = deepcopy(original)
    raw["electrical"] = dict(nodes=["GND", "PWR"], components=[
        dict(id="supply", name="Synthetic source", kind="battery", a="PWR", b="GND", voltage_v=5),
    ])
    registered = register_part(raw, "g474_body", dict(
        catalog_id=CATALOG, a="PWR", b="GND", analysis_enabled=False,
    ))
    registered = register_part(registered, "module_body", dict(
        kind="load", a="PWR", b="GND", analysis_enabled=False,
        terminal_pins={f"DAQ_{key}": f"MODULE_{key}" for key in LEGACY_KEYS},
    ))
    return original, registered, registration_for_part(registered, "g474_body").id, \
        registration_for_part(registered, "module_body").id


def add_pin_wires(design, board_id, module_id, keys):
    work = design.electrical
    for key in keys:
        work = add_schematic_wire(
            work, board_id, f"pin:{key}", module_id, f"port:DAQ_{key}",
            name=f"Saved {key} cable", length_mm=120, cross_section_mm2=.2,
            analysis_enabled=False, wire_color="#2A5F90",
        )
    raw = design.model_dump()
    raw["electrical"] = work.model_dump()
    return Design.model_validate(raw)


def legacy_wiring(design, board_id, module_id):
    work = add_schematic_wire(
        design.electrical, "supply", "a", board_id, "supply:E5V_CN7_6",
        name="Saved external-source cable", length_mm=80, cross_section_mm2=.5,
        analysis_enabled=False,
    )
    work = add_schematic_wire(
        work, "supply", "b", board_id, "supply:GND_CN6_6",
        name="Saved physical ground cable", length_mm=80, cross_section_mm2=.5,
        analysis_enabled=False,
    )
    raw = design.model_dump()
    raw["electrical"] = work.model_dump()
    return add_pin_wires(Design.model_validate(raw), board_id, module_id, LEGACY_KEYS)


def append_source_bundle(design, board_id, keys, name):
    work = design.electrical
    bundle = create_bundle(
        name, "stm32_hal", work, board_id,
        [dict(path=f"{name}.c", content=f"/* Synthetic {name} source snapshot. */\nvoid fixture_source(void) {{}}\n")],
        f"{name}.c", pin_bindings=[
            dict(pin=key, node=next(item for item in work.components if item.id == board_id).signal_pins[key],
                 function="Saved synthetic terminal connection") for key in keys
        ],
        missing_parameters=["Physical target, alternate-function selection, clock and jumper verification"],
    )
    assert isinstance(bundle, FirmwareBundle)
    raw = design.model_dump()
    raw["electrical"]["firmware_bundles"] = [
        *(item.model_dump() for item in work.firmware_bundles), bundle.model_dump(),
    ]
    raw["electrical"]["programs"] = [
        *(item.model_dump() for item in work.programs), to_program_attachment(bundle, work).model_dump(),
    ]
    return Design.model_validate(raw), bundle


def assert_physical_membership(design, board_id, module_id, keys):
    work = design.electrical
    board = next(item for item in work.components if item.id == board_id)
    assert board.part_id == "g474_body" and board.part_registration
    assert board.catalog_id == board.pinout_catalog_id == CATALOG and board.source_url
    assert set(board.signal_pins) == set(keys)
    assert board.supply_pinout_catalog_id == CATALOG
    assert set(board.board_supply_pins) == {"E5V_CN7_6", "GND_CN6_6"}
    endpoints = {(item.component_id, item.terminal): item.node
                 for item in connection_endpoints(work)}
    wires = [item for item in work.components if item.kind == "wire"]
    assert len(wires) == len(keys) + 2
    rows = {item.key: item for item in pin_connections(work, board_id)}
    for wire in wires:
        assert len(wire.wire_endpoints) == 2
        assert [endpoints[(item.component_id, item.terminal)] for item in wire.wire_endpoints] == [wire.a, wire.b]
    for key in keys:
        wire = next(item for item in wires if
                    [(ref.component_id, ref.terminal) for ref in item.wire_endpoints] ==
                    [(board_id, f"pin:{key}"), (module_id, f"port:DAQ_{key}")])
        assert rows[key].node == board.signal_pins[key] == wire.a
        assert wire.a != wire.b
    return board


def test_expanded_g474_registration_all_sixteen_wires_context_and_history_roundtrip(tmp_path):
    pinout = board_pinout(CATALOG)
    pin_map = {item.key: item for item in pinout.pins}
    for key, connector in NEW_CONNECTORS.items():
        assert pin_map[key].kind == "signal" and pin_map[key].label.startswith(connector + " ·")
    for row in LEGACY_ROWS:
        assert pin_map[row[0]].label == row[1] and pin_map[row[0]].kind == row[3]
    assert {item.key for item in pinout.pins if item.kind in ("power", "ground")} == {
        row[0] for row in LEGACY_ROWS if row[3] in ("power", "ground")
    }
    original, registered, board_id, module_id = registered_fixture()
    legacy, old_bundle = append_source_bundle(
        legacy_wiring(registered, board_id, module_id), board_id, LEGACY_KEYS, "legacy-daq",
    )
    legacy_snapshot = legacy.model_dump()
    legacy_board = assert_physical_membership(legacy, board_id, module_id, LEGACY_KEYS)
    expanded = register_part(legacy, "module_body", dict(terminal_pins={
        **next(item for item in legacy.electrical.components if item.id == module_id).terminal_pins,
        **{f"DAQ_{key}": f"MODULE_{key}" for key in NEW_CONNECTORS},
    }))
    expanded = add_pin_wires(expanded, board_id, module_id, NEW_CONNECTORS)
    expanded, new_bundle = append_source_bundle(
        expanded, board_id, (*LEGACY_KEYS, *NEW_CONNECTORS), "expanded-g474",
    )
    expanded_snapshot = expanded.model_dump()
    board = assert_physical_membership(expanded, board_id, module_id, (*LEGACY_KEYS, *NEW_CONNECTORS))
    assert {key: board.signal_pins[key] for key in LEGACY_KEYS} == legacy_board.signal_pins
    assert board.board_supply_pins == legacy_board.board_supply_pins
    old_wires = {item.id: item for item in legacy.electrical.components if item.kind == "wire"}
    assert all(next(item for item in expanded.electrical.components if item.id == key) == wire
               for key, wire in old_wires.items())
    assert expanded.electrical.firmware_bundles[0] == old_bundle
    assert expanded.electrical.programs[0] == legacy.electrical.programs[0]
    assert verify_bundle_binding(old_bundle, expanded.electrical).status == "stale"
    assert verify_bundle_binding(new_bundle, expanded.electrical).status == "current"
    assert new_bundle.binding.catalog_id == new_bundle.binding.pinout_catalog_id == CATALOG
    assert new_bundle.binding.part_id == "g474_body"
    assert new_bundle.binding == create_binding(expanded.electrical, board_id)

    context = build_context(expanded.electrical, board_id, "Review saved pin expansion",
                            target="stm32_hal", existing_bundle=new_bundle)
    assert context["board"]["catalog_id"] == CATALOG
    assert context["board"]["source_url"] == pinout.source_url
    assert context["binding"] == new_bundle.binding.model_dump()
    assert context["existing_candidate"]["binding_current"] is True
    context_pins = {item["pin"]: item for item in context["pins"]}
    for key, connector in NEW_CONNECTORS.items():
        row = context_pins[key]
        assert row["label"].startswith(connector + " ·")
        assert row["kind"] == "signal" and row["node"] == board.signal_pins[key]
        assert row["functions"] == list(pin_map[key].functions)
        assert any(item["component_id"] == module_id and item["part_id"] == "module_body"
                   and item["terminal"] == f"port:DAQ_{key}"
                   for item in row["connected_endpoints"])
    assert len(context["wires"]) == 24
    assert len(new_bundle.pin_bindings) == 22
    assert context["existing_source_snapshots"][-1]["sha256"] == new_bundle.files[0].sha256
    assert sha256(new_bundle.files[0].content.encode()).hexdigest() == new_bundle.files[0].sha256
    assert expanded_snapshot["parts"] == original["parts"]

    doc = Document()
    doc.commit(registered, "Register exact G474 CAD part")
    registered_id = doc.journal.data["cursor"]
    doc.commit(legacy, "Preserve six DAQ pins and physical supply")
    legacy_id = doc.journal.data["cursor"]
    doc.commit(expanded, "Add sixteen confirmed header pins and source snapshot")
    expanded_id = doc.journal.data["cursor"]
    target = tmp_path / "g474-expanded.pcad"
    expected = doc.project().model_dump()
    doc.write(target)
    loaded = read_project(target)
    assert loaded.model_dump() == expected
    restored = Document()
    restored.load(loaded, target)
    entries = deepcopy(restored.journal.data["entries"])
    for identifier, snapshot in ((legacy_id, legacy_snapshot),
                                 (registered_id, registered.model_dump()),
                                 (expanded_id, expanded_snapshot)):
        restored.commit(restored.journal.at(identifier), "Undo or redo exact snapshot", cursor=identifier)
        assert restored.design == snapshot
        assert restored.journal.data["entries"] == entries
    restored.write(target)
    assert read_project(target).model_dump() == expected
    assert legacy.model_dump() == legacy_snapshot


def test_legacy_g474_saved_document_is_exact_after_catalog_expansion(tmp_path, monkeypatch):
    expanded_pinout = board_pinout(CATALOG)
    legacy_pinout = replace(
        expanded_pinout, model="ST NUCLEO-G474RE · MB1367 selected DAQ headers",
        pins=tuple(BoardPin(*row) for row in LEGACY_ROWS),
    )
    target = tmp_path / "synthetic-legacy-g474.pcad"
    with monkeypatch.context() as patch:
        patch.setitem(board_pins._BY_ID, CATALOG, legacy_pinout)
        _, registered, board_id, module_id = registered_fixture()
        legacy, bundle = append_source_bundle(
            legacy_wiring(registered, board_id, module_id), board_id, LEGACY_KEYS, "legacy-source",
        )
        assert verify_bundle_binding(bundle, legacy.electrical).status == "current"
        doc = Document()
        doc.commit(registered, "Original registered G474")
        registered_id = doc.journal.data["cursor"]
        doc.commit(legacy, "Saved legacy DAQ and source")
        legacy_id = doc.journal.data["cursor"]
        longer = legacy.model_dump()
        wire_id = next(item.id for item in legacy.electrical.components if item.kind == "wire")
        longer["electrical"] = update_schematic_wire(legacy.electrical, wire_id, length_mm=100).model_dump()
        doc.commit(longer, "Legacy cable edit")
        edited_id = doc.journal.data["cursor"]
        doc.commit(doc.journal.at(legacy_id), "Undo legacy edit", cursor=legacy_id)
        expected = doc.project().model_dump()
        doc.write(target)
    saved_bytes = target.read_bytes()
    assert board_pinout(CATALOG) is expanded_pinout
    loaded = read_project(target)
    assert loaded.model_dump() == expected and target.read_bytes() == saved_bytes
    assert loaded.design.electrical.firmware_bundles == [bundle]
    assert verify_bundle_binding(bundle, loaded.design.electrical).status == "stale"
    assert create_binding(loaded.design.electrical, board_id).pin_map_sha256 != bundle.binding.pin_map_sha256
    restored = Document()
    restored.load(loaded, target)
    entries = deepcopy(restored.journal.data["entries"])
    for identifier, snapshot in ((registered_id, registered.model_dump()),
                                 (edited_id, longer), (legacy_id, legacy.model_dump())):
        restored.commit(restored.journal.at(identifier), "Restore legacy snapshot", cursor=identifier)
        assert restored.design == snapshot
        assert restored.journal.data["entries"] == entries
    assert_physical_membership(restored.project().design, board_id, module_id, LEGACY_KEYS)
    rewritten = tmp_path / "rewritten-legacy-g474.pcad"
    restored.write(rewritten)
    assert read_project(rewritten).model_dump() == expected
    assert rewritten.read_bytes() == saved_bytes
