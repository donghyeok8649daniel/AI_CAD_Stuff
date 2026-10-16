"""Execute small UI state methods with data-only doubles, without importing Qt."""
import ast
from pathlib import Path
from types import SimpleNamespace

BASE=Path(__file__).resolve().parents[1]/'cadstudio/native'


def method(file,cls,name,**globals):
    tree=ast.parse((BASE/file).read_text(encoding='utf-8'))
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    fn=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name==name)
    scope=dict(globals);exec(compile(ast.Module(body=[fn],type_ignores=[]),'<data-only UI state method>','exec'),scope)
    return scope[name]


class Field:
    def __init__(self):self.value='old product data';self.checked=True;self.index=1;self.blocked=False;self.rows=2
    def clear(self):self.value=''
    def setChecked(self,value):self.checked=value
    def setCurrentIndex(self,value):self.index=value
    def setEnabled(self,value):self.enabled=value
    def setPlainText(self,value):self.value=value
    def blockSignals(self,value):self.blocked=value
    def setRowCount(self,value):self.rows=value


class Products(Field):
    def clearSelection(self):self.selected=False
    def setCurrentCell(self,row,col):self.current=row
    def setItem(self,*_):pass
    def resizeColumnsToContents(self):pass


def test_same_count_search_never_reuses_prior_selection_or_acknowledgment():
    host=SimpleNamespace(rows=[dict(catalog_id='old')],selected_catalog_id='old',checked={'old':True},products=Products(),query=SimpleNamespace(text=lambda:'next'),update_specs=lambda rows:None)
    for key in ('confirm','review_record','reviewer','review_date','review_note','model','product_source','revision','orientation','height','clearance','reference','side'):setattr(host,key,Field())
    populate=method('pcb_embedded_dialog.py','PCBEmbeddedDialog','populate',search_embedded=lambda *a,**k:[dict(catalog_id='new',manufacturer='new',model='new',category='new')],QTableWidgetItem=str)
    populate(host)
    assert host.products.current==-1 and not host.products.selected and host.selected_catalog_id is None
    assert host.checked is None and not host.confirm.checked and not host.review_record.checked
    assert host.model.value==host.height.value==host.reference.value==''
    assert not host.products.blocked and host.rows[0]['catalog_id']=='new'


def test_exact_sku_edit_invalidates_old_pin_ratings_and_geometry_acknowledgment():
    ratings=[dict(number='1',current_limit_a=5)]
    host=SimpleNamespace(update_specs=lambda rows:ratings.__setitem__(slice(None),rows))
    for key in ('confirm','review_record','reviewer','review_date','review_note','revision','orientation','height','clearance','side'):setattr(host,key,Field())
    method('pcb_embedded_dialog.py','PCBEmbeddedDialog','product_identity_edited')(host)
    assert ratings==[] and not host.confirm.checked and not host.review_record.checked
    assert host.height.value==host.review_date.value=='' and host.side.index==0


def test_replacement_document_discards_old_condition_values_and_marks_report_stale():
    host=SimpleNamespace(embedded_report=Field(),bom_text=Field(),net_conditions=Field(),cost_proposal={'old':True},cost_preview_button=Field())
    method('pcb_workbench.py','PCBWorkbench','invalidate_embedded_review')(host,clear_conditions=True)
    assert host.net_conditions.rows==0 and not host.net_conditions.blocked
    assert host.bom_text.value=='' and '다시 실행' in host.embedded_report.value
    assert host.cost_proposal is None and not host.cost_preview_button.enabled
    text=(BASE/'pcb_workbench.py').read_text(encoding='utf-8')
    tree=ast.parse(text);owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PCBWorkbench')
    for name in ('reload','document_changed','replace_project'):
        fn=next(n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert 'self.invalidate_embedded_review(clear_conditions=True)' in ast.get_source_segment(text,fn)


def test_condition_edit_cancels_late_report_and_clears_old_result():
    calls=[];host=SimpleNamespace(workflow_task=object(),workflow_report=Field(),
        invalidate_embedded_review=lambda:calls.append('invalidated'),cancel_workflow=lambda:calls.append('cancelled'))
    method('pcb_workbench.py','PCBWorkbench','operating_conditions_changed')(host)
    assert calls==['invalidated','cancelled'] and host.workflow_report.value==''
