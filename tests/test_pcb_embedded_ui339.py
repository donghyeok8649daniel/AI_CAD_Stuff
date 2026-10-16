"""Source integration contracts only; no native UI proof is asserted."""
import ast
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]/'cadstudio'


def methods(file,cls):
    text=(BASE/file).read_text(encoding='utf-8');tree=ast.parse(text)
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    return text,{n.name:n for n in node.body if isinstance(n,ast.FunctionDef)}


def test_embedded_forms_offer_physical_geometry_and_pin_rating_table_without_json_editor():
    text,m=methods('native/pcb_embedded_dialog.py','PCBEmbeddedDialog')
    assert 'pin_specs_from_rows(rows)' in text and "QTableWidget(0,len(PIN_SPEC_COLUMNS))" in text
    assert 'json.loads' not in text and "self.confirm.isChecked()" in text
    assert 'component_from_catalog' in text and 'bind_catalog_product' in text
    assert 'self.set_project' not in text and 'applyRequested.emit' not in text
    # Switching SKU must not carry the former product's current/voltage rating.
    reference=ast.get_source_segment(text,m['show_reference'])
    assert "old.catalog_id==entry['catalog_id']" in reference and 'if same else []' in reference


def test_stability_runs_on_worker_copy_and_advisory_uses_compact_bom_helper():
    text,m=methods('native/pcb_workbench.py','PCBWorkbench')
    start=ast.get_source_segment(text,m['start_workflow']);review=ast.get_source_segment(text,m['review'])
    assert "review_embedded(project,net_conditions=conditions)" in start
    assert "cost_advice_request if mode=='cost' else advice_request" in review
    assert "review_cost if mode=='cost' else review_pcb" in review
    assert 'self.ai_identity()==(model,effort)' in review and 'design_digest(self.current_raw())==base_sha' in review
    assert 'task.cancel()' in ast.get_source_segment(text,m['stop_advice'])


def test_product_edit_uses_same_local_undo_transaction_as_existing_manual_editor():
    text,m=methods('native/pcb_workbench.py','PCBWorkbench')
    body=ast.get_source_segment(text,m['embedded_product'])
    assert 'self.set_project(dialog.checked)' in body and 'applyRequested.emit' not in body
    assert 'preserve_library_metadata(self.original,candidate)' in text
