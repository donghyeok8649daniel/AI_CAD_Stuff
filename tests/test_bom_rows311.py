"""BOM-row capacity remains separate from physical-body and input budgets."""
from copy import deepcopy
import csv
from io import StringIO
import json

from pydantic import ValidationError
import pytest

from cadstudio.bom_design import (MAX_ITEMS, MAX_CONTEXT_CHARS, MAX_SOURCE_CHARS,
    MAX_FILE_BYTES, BomDocument, bom_context, import_bom_file, parse_bom_text)
from cadstudio.models import Design
from cadstudio.native.document import Document, read_project
from test_bom_design2240 import xlsx_bytes


def table(count, separator=","):
    stream = StringIO()
    writer = csv.writer(stream, delimiter=separator)
    writer.writerow(["Name", "Quantity", "Model", "Length mm", "Notes"])
    for index in range(count):
        writer.writerow([f"Distinct item {index}", "" if index % 7 == 0 else "1",
            f"Exact nominal ID {index}", "20", "Unknown actual rating; retain this declaration and unique row"])
    return stream.getvalue()


def context_data(document):
    context = bom_context(document)
    return json.loads(context.split("\n", 2)[2].rsplit("\n", 1)[0])


@pytest.mark.parametrize("count", [239, 512])
@pytest.mark.parametrize("suffix,separator", [(".csv", ","), (".tsv", "\t"), (".xlsx", ",")])
def test_all_distinct_rows_roundtrip_through_real_import_and_context(tmp_path, count, suffix, separator):
    path = tmp_path / ("owned-bom" + suffix)
    text = table(count, separator)
    if suffix == ".xlsx":
        path.write_bytes(xlsx_bytes(list(csv.reader(StringIO(text)))))
    else:
        path.write_text(text, encoding="utf-8")
    document = import_bom_file(path)
    before = document.model_dump(mode="json")
    data = context_data(document)
    assert MAX_ITEMS == 512 and MAX_CONTEXT_CHARS == 300_000
    assert len(data["items"]) == len(document.items) == count
    assert len({item["id"] for item in data["items"]}) == count
    assert document.model_dump(mode="json") == before
    for actual, original in zip(data["items"], before["items"], strict=True):
        expected = deepcopy(original)
        expected.pop("raw_fields")
        expected["part_binding"] = dict(document_id=document.id, item_id=original["id"], source_sha256=document.source_sha256)
        assert actual == expected
    assert len(bom_context(document)) > 60_000
    assert data["items"][-1]["name"] == f"Distinct item {count - 1}"
    assert data["items"][0]["quantity"] is None


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_513th_row_rejected_without_overwriting_caller(tmp_path, suffix):
    before = parse_bom_text(table(239)).model_dump(mode="json")
    path = tmp_path / ("too-many" + suffix)
    text = table(513)
    path.write_bytes(xlsx_bytes(list(csv.reader(StringIO(text)))) if suffix == ".xlsx" else text.encode())
    with pytest.raises(ValueError, match="512"):
        import_bom_file(path)
    assert len(BomDocument.model_validate(before).items) == 239
    extra = deepcopy(before["items"][-1])
    oversized = before | {"items": before["items"] + [extra] * (513 - 239)}
    with pytest.raises(ValidationError):
        BomDocument.model_validate(oversized)


def test_raw_source_and_file_budgets_remain_independent(tmp_path):
    assert MAX_SOURCE_CHARS == 100_000 and MAX_FILE_BYTES == 2_000_000
    with pytest.raises(ValueError, match="100,000"):
        parse_bom_text("Name,Notes\n" + "Item," + "x" * 3900 + "\n" + ("Another," + "x" * 3900 + "\n") * 25)
    path = tmp_path / "oversize.csv"
    path.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="2 MB"):
        import_bom_file(path)
    with pytest.raises(ValueError, match="2 MB"):
        parse_bom_text("x" * (MAX_FILE_BYTES + 1))


def test_context_budget_rejects_atomically_without_truncating_rows():
    document = parse_bom_text(table(100))
    for item in document.items:
        item.notes = "User evidence " + "x" * 3980
    before = document.model_dump(mode="json")
    with pytest.raises(ValueError, match="300,000"):
        bom_context(document)
    assert document.model_dump(mode="json") == before


def test_239_bom_rows_keep_all_bindings_and_history_after_save_reopen(tmp_path):
    bom = parse_bom_text(table(239))
    parts = [dict(id=f"part_{i}", name=item.name,
        geometry=dict(kind="plate", length=20, width=10, thickness=1, hole_count=0),
        bom=dict(document_id=bom.id, item_id=item.id, source_sha256=bom.source_sha256))
        for i, item in enumerate(bom.items)]
    document = Document()
    document.commit(Design(name="239 distinct nominal bodies", parts=parts, bom=bom), "All distinct rows")
    original = document.project().model_dump(mode="json")
    changed = Design.model_validate(document.design)
    changed.parts[-1].name = "Last body explicitly renamed"
    document.commit(changed, "Manual rename")
    expected = document.project().model_dump(mode="json")
    path = tmp_path / "owned239.pcad"
    document.write(path)
    reopened = read_project(path)
    assert reopened.model_dump(mode="json") == expected
    restored = Document()
    restored.load(reopened)
    original_cursor = original["history"]["cursor"]
    restored.commit(restored.journal.at(original_cursor), "Undo", cursor=original_cursor)
    assert restored.design == original["design"]
    final_cursor = expected["history"]["cursor"]
    restored.commit(restored.journal.at(final_cursor), "Redo", cursor=final_cursor)
    assert restored.project().model_dump(mode="json") == expected
    assert len(restored.design["parts"]) == len(restored.design["bom"]["items"]) == 239
    assert Design.model_json_schema()["properties"]["parts"]["maxItems"] == 256


def test_existing_cad_bom_csv_export_keeps_239_distinct_physical_bodies(tmp_path):
    from cadstudio.drawings import export_bom
    from cadstudio.kernel import KERNEL_LOCK
    parts = [dict(id=f"part_{i}", name=f"Distinct body {i}",
        geometry=dict(kind="plate", length=20, width=10, thickness=1, hole_count=0)) for i in range(239)]
    design = Design(parts=parts, bom=parse_bom_text(table(239)))
    before = design.model_dump(mode="json")
    path = tmp_path / "physical-body-bom.csv"
    with KERNEL_LOCK:
        export_bom(design, path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["Part ID"] for row in rows] == [part["id"] for part in parts]
    assert [row["Name"] for row in rows] == [part["name"] for part in parts]
    assert all(row["Quantity"] == "1" and float(row["Volume mm3"]) == pytest.approx(200) for row in rows)
    assert design.model_dump(mode="json") == before
