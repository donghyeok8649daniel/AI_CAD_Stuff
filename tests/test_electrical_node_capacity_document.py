"""Dense electrical projects preserve portable data and every history branch."""

from base64 import b64encode
from copy import deepcopy
from hashlib import sha256
import zlib

import pytest

from cadstudio.bom_design import bind_bom_item, parse_bom_text
from cadstudio.circuit_connections import add_schematic_wire, update_schematic_wire
from cadstudio.electrical import ElectricalWorkspace
from cadstudio.electrical_registration import register_part, registration_for_part
from cadstudio.firmware_bundle import (
    create_bundle, to_program_attachment, verify_bundle_binding,
)
from cadstudio.firmware_libraries import import_library_directory
from cadstudio.mcu_connections import connection_endpoints, pin_connections
from cadstudio.models import Design
from cadstudio.native.document import Document, read_project


@pytest.fixture
def dense_project(tmp_path):
    """264 used nets, 131 physical cables and registered board/source snapshots."""
    parts = [
        dict(id="frame", name="Frame", role="structure", length=120, width=100),
        dict(id="board_body", name="Controller", role="electrical", length=85, width=56),
        dict(id="driver_body", name="Driver", role="electrical", length=30, width=20),
        dict(id="source_body", name="Source bank", role="electrical", length=100, width=20),
        dict(id="target_body", name="Target bank", role="electrical", length=100, width=20),
    ]
    cad_parts = [
        dict(id=part["id"], name=part["name"], role=part["role"],
             geometry=dict(kind="plate", length=part["length"], width=part["width"],
                           thickness=2, hole_count=0))
        for part in parts
    ]
    # Document serialization treats embedded payloads as opaque data. This
    # synthetic payload deliberately requires no topology import or CAD kernel.
    asset_bytes = b"synthetic document-only embedded asset snapshot\n"
    base = Design.model_validate(dict(
        name="Dense circuit \u00b7 saved sources", parts=cad_parts,
        parameters={"frame_length": "120"},
        assets={"fixture_asset": dict(
            name="opaque-serialization-fixture.brep", format="brep",
            data=b64encode(zlib.compress(asset_bytes)).decode("ascii"),
            sha256=sha256(asset_bytes).hexdigest())},
    ))
    bom = parse_bom_text(
        "Name,Quantity,Length mm,Width mm,Thickness mm,Role\n"
        + "\n".join(
            f'{part["name"]},1,{part["length"]},{part["width"]},2,{part["role"]}'
            for part in parts
        )
    )
    for part, item in zip(parts, bom.items):
        base = bind_bom_item(base, bom, item.id, [part["id"]])
    original = base.model_dump()

    source_ports = {f"CH_{index:03d}": f"SRC_{index:03d}" for index in range(130)}
    target_ports = {f"CH_{index:03d}": f"DST_{index:03d}" for index in range(130)}
    workspace = ElectricalWorkspace.model_validate(dict(
        nodes=["GND", "PWR", *source_ports.values(), *target_ports.values()],
        components=[
            dict(id="supply", name="Synthetic 5 V supply", kind="battery",
                 a="PWR", b="GND", voltage_v=5),
            dict(id="source_bank", name="Source bank", kind="load", a="PWR", b="GND",
                 terminal_pins=source_ports, part_id="source_body",
                 part_registration=True, analysis_enabled=False),
            dict(id="target_bank", name="Target bank", kind="load", a="PWR", b="GND",
                 terminal_pins=target_ports, part_id="target_body",
                 part_registration=True, analysis_enabled=False),
        ],
    ))
    raw = deepcopy(original)
    raw["electrical"] = workspace.model_dump()
    registered = register_part(raw, "board_body", dict(
        catalog_id="rpi4b", a="PWR", b="GND", analysis_enabled=False,
    ))
    registered = register_part(registered, "driver_body", dict(
        catalog_id="pololu_2130", a="PWR", b="GND", analysis_enabled=False,
    ))
    board_id = registration_for_part(registered, "board_body").id
    driver_id = registration_for_part(registered, "driver_body").id
    workspace = registered.electrical
    for index in range(130):
        workspace = add_schematic_wire(
            workspace, "source_bank", f"port:CH_{index:03d}",
            "target_bank", f"port:CH_{index:03d}", name=f"Bank cable {index:03d}",
            length_mm=100 + index, cross_section_mm2=.2, wire_color="#123456",
        )
    workspace = add_schematic_wire(
        workspace, board_id, "pin:GPIO17", driver_id, "port:AIN1",
        name="Board command cable", length_mm=150, cross_section_mm2=.2,
        wire_color="#Ab1234",
    )
    board_wire_id = workspace.components[-1].id
    layout = workspace.model_dump()
    layout["schematic_positions"] = {
        component.id: dict(x=index * 12, y=40)
        for index, component in enumerate(workspace.components)
    }
    workspace = ElectricalWorkspace.model_validate(layout)

    source_folder = tmp_path / "library-source"
    source_folder.mkdir()
    library_source = 'raise RuntimeError("source snapshot must never execute")\nVALUE = 42\n'
    (source_folder / "sensor.py").write_bytes(library_source.encode("utf-8"))
    library = import_library_directory(
        source_folder, name="Sensor", version="1.2.3", ecosystem="python",
    )
    (source_folder / "sensor.py").unlink()
    source_folder.rmdir()
    source = "import sensor\n# Stored for review only.\nvalue = sensor.VALUE\n"
    board = next(item for item in workspace.components if item.id == board_id)
    bundle = create_bundle(
        "Dense board source", "raspberry_python", workspace, board_id,
        [dict(path="main.py", content=source),
         dict(path="README.md", content="Synthetic source fixture.\n", role="documentation")],
        "main.py", libraries=[library],
        pin_bindings=[dict(pin="GPIO17", node=board.signal_pins["GPIO17"],
                           function="Driver command")],
    )
    attached = workspace.model_dump()
    attached["firmware_bundles"] = [bundle.model_dump()]
    attached["programs"] = [to_program_attachment(bundle, workspace).model_dump()]
    complete = deepcopy(original)
    complete["electrical"] = ElectricalWorkspace.model_validate(attached).model_dump()
    complete = Design.model_validate(complete).model_dump()

    assert len(workspace.nodes) == 264
    assert len(workspace.components) == 136
    assert {endpoint.node for endpoint in connection_endpoints(workspace)
            if endpoint.node is not None} == set(workspace.nodes)
    assert complete["parts"] == original["parts"]
    return dict(original=original, complete=complete, board_id=board_id,
                driver_id=driver_id, board_wire_id=board_wire_id,
                library=library, library_source=library_source, source=source)


def assert_dense_snapshot(design, fixture, *, binding_status="current"):
    work = ElectricalWorkspace.model_validate(design["electrical"])
    assert len(work.nodes) == 264 and len(work.components) == 136
    endpoints = {(item.component_id, item.terminal): item.node
                 for item in connection_endpoints(work)}
    wires = [item for item in work.components if item.kind == "wire"]
    assert len(wires) == 131
    for wire in wires:
        assert len(wire.wire_endpoints) == 2
        assert [endpoints[(item.component_id, item.terminal)]
                for item in wire.wire_endpoints] == [wire.a, wire.b]
    assert set(endpoints.values()) - {None} == set(work.nodes)
    board = next(item for item in work.components if item.id == fixture["board_id"])
    driver = next(item for item in work.components if item.id == fixture["driver_id"])
    board_wire = next(item for item in wires if item.id == fixture["board_wire_id"])
    assert board.part_id == "board_body" and board.part_registration
    assert board.catalog_id == board.pinout_catalog_id == "rpi4b"
    assert board.source_url
    assert driver.catalog_id == driver.product_pinout_catalog_id == "pololu_2130"
    assert board.signal_pins["GPIO17"] == board_wire.a
    assert driver.terminal_pins["AIN1"] == board_wire.b
    pin = next(item for item in pin_connections(work, board.id) if item.key == "GPIO17")
    assert "11" in pin.label and pin.node == board_wire.a
    assert [(item.component_id, item.terminal) for item in board_wire.wire_endpoints] == [
        (board.id, "pin:GPIO17"), (driver.id, "port:AIN1"),
    ]
    assert work.programs[0].source == fixture["source"]
    assert work.programs[0].sha256 == sha256(fixture["source"].encode()).hexdigest()
    assert work.programs[0].board_component_id == board.id
    bundle = work.firmware_bundles[0]
    assert bundle.libraries == [fixture["library"]]
    library_file = next(item for item in bundle.libraries[0].files if item.path == "sensor.py")
    assert library_file.content == fixture["library_source"]
    assert library_file.sha256 == sha256(fixture["library_source"].encode()).hexdigest()
    assert verify_bundle_binding(bundle, work).status == binding_status
    for key in ("parts", "bom", "assets", "parameters"):
        assert design[key] == fixture["original"][key]


def test_dense_project_save_reopen_preserves_nodes_physical_wires_and_portable_sources(
        tmp_path, dense_project):
    original = deepcopy(dense_project["original"])
    doc = Document()
    doc.commit(original, "Original CAD and BOM", {"fixture_source": "synthetic"})
    doc.commit(dense_project["complete"], "Add dense circuit and saved source")
    expected = doc.project().model_dump()
    target = tmp_path / "dense-electrical-project.pcad"
    doc.write(target)
    reopened = read_project(target)
    assert reopened.model_dump() == expected
    restored = Document()
    restored.load(reopened, target)
    assert restored.project().model_dump() == expected
    assert_dense_snapshot(restored.design, dense_project)
    assert restored.journal.at(restored.journal.data["entries"][0]["id"]) == original
    assert dense_project["original"] == original


def test_dense_electrical_undo_redo_and_saved_abandoned_branch_keep_exact_history(
        tmp_path, dense_project):
    original = deepcopy(dense_project["original"])
    complete = deepcopy(dense_project["complete"])
    doc = Document()
    doc.commit(original, "Original CAD and BOM", {"fixture_source": "synthetic"})
    root_id = doc.journal.data["cursor"]
    doc.commit(complete, "Add dense circuit and firmware library")
    dense_id = doc.journal.data["cursor"]
    longer = deepcopy(complete)
    longer["electrical"] = update_schematic_wire(
        complete["electrical"], dense_project["board_wire_id"], length_mm=275,
    ).model_dump()
    doc.commit(longer, "Change physical command cable length")
    abandoned_id = doc.journal.data["cursor"]
    doc.commit(doc.journal.at(dense_id), "Undo length", cursor=dense_id)
    assert doc.design == complete
    assert doc.journal.data["head"] == abandoned_id
    assert_dense_snapshot(doc.design, dense_project)

    # Save while undone: the current snapshot and the redo head differ.
    target = tmp_path / "dense-electrical-history.pcad"
    undone = doc.project().model_dump()
    doc.write(target)
    reopened = read_project(target)
    assert reopened.model_dump() == undone
    restored = Document()
    restored.load(reopened, target)
    restored.commit(restored.journal.at(abandoned_id), "Redo length", cursor=abandoned_id)
    assert restored.design == longer
    assert_dense_snapshot(restored.design, dense_project, binding_status="stale")
    restored.commit(restored.journal.at(dense_id), "Undo length again", cursor=dense_id)
    alternative = deepcopy(complete)
    alternative["electrical"] = update_schematic_wire(
        complete["electrical"], dense_project["board_wire_id"], wire_color="#00Aa55",
    ).model_dump()
    entries_before_branch = deepcopy(restored.journal.data["entries"])
    restored.commit(alternative, "Alternative cable color")
    branch_id = restored.journal.data["cursor"]
    assert restored.journal.data["entries"][:-1] == entries_before_branch
    assert restored.journal.data["entries"][-1]["parent"] == dense_id
    assert restored.journal.data["head"] == branch_id
    expected = restored.project().model_dump()
    restored.write(target)
    loaded = read_project(target)
    assert loaded.model_dump() == expected
    restored.load(loaded, target)
    snapshots = {root_id: original, dense_id: complete,
                 abandoned_id: longer, branch_id: alternative}
    assert len(restored.journal.data["entries"]) == 4
    saved_entries = deepcopy(restored.journal.data["entries"])
    for identifier, snapshot in snapshots.items():
        assert restored.journal.at(identifier) == snapshot
        restored.commit(snapshot, "Restore exact branch", cursor=identifier)
        assert restored.design == snapshot
        assert restored.journal.data["entries"] == saved_entries
        if identifier != root_id:
            assert_dense_snapshot(
                restored.design, dense_project,
                binding_status="stale" if identifier == abandoned_id else "current",
            )
    restored.write(target)
    assert read_project(target).model_dump() == restored.project().model_dump()
    assert dense_project["original"] == original
    assert dense_project["complete"] == complete
