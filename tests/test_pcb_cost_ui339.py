"""Data-only cost form/transaction integration; no Qt or real provider call."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from cadstudio.pcb import PCBProject,PCBComponent,PCBPin,pcb_digest
from cadstudio.pcb_cost_workflow import with_cost_inputs,read_cost_inputs,estimate_saved_cost,adopt_cost_proposal
from cadstudio.pcb_workflow import PCBWorkflowSession

NATIVE=Path(__file__).parents[1]/'cadstudio/native'


def methods(file,cls):
    text=(NATIVE/file).read_text(encoding='utf-8');tree=ast.parse(text)
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
    return text,{n.name:n for n in owner.body if isinstance(n,ast.FunctionDef)}


def extracted(file,cls,name,**values):
    _,functions=methods(file,cls);fn=deepcopy(functions[name]);fn.decorator_list=[]
    scope=dict(deepcopy=deepcopy,**values);exec(compile(ast.Module(body=[fn],type_ignores=[]),'<cost form data>','exec'),scope)
    return scope[name]


class Table:
    def __init__(self,rows):self.rows=rows
    def rowCount(self):return len(self.rows)
    def cellWidget(self,row,col):return None
    def item(self,row,col):return SimpleNamespace(text=lambda:self.rows[row][col])


def form(*,zero_shipping=False,partial=False):
    extras=[['cost','','','USD','user_estimate','','',''] for _ in range(4)]
    if zero_shipping:extras[2]=['shipping','0','0','USD','user_estimate','','','Explicit local pickup, synthetic only']
    if partial:extras[2][1]='1'
    host=SimpleNamespace(tiers=Table([['U1','10','0.125','USD','reference','2026-01-01','Synthetic supplier','https://example.org/quote','Entered fixture']]),
        additional=Table(extras),cost_kinds=('pcb_fabrication','assembly_consumables','shipping','tax_import'),
        saved=dict(quantity_breaks={},additional_costs={},accepted_ai_estimates=[]),clear_ai=SimpleNamespace(isChecked=lambda:False))
    # Run the actual cell and inputs implementations without importing Qt.
    tree=ast.parse((NATIVE/'pcb_cost_dialog.py').read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='cell')
    scope={};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<cost cell>','exec'),scope)
    return host,extracted('pcb_cost_dialog.py','PCBCostInputsDialog','inputs',cell=scope['cell'])


def project():
    return PCBProject(components=[PCBComponent(ref='U1',mpn='Synthetic SKU',pins=[PCBPin(number='1')])],budget=dict(board_quantity=20))


def test_quote_form_keeps_decimal_strings_blank_costs_and_explicit_zero_distinct():
    host,inputs=form(zero_shipping=True);raw=inputs(host)
    assert raw['quantity_breaks']['U1'][0]['unit_price']=='0.125'
    assert raw['additional_costs']['shipping']['minimum']=='0'
    assert 'pcb_fabrication' not in raw['additional_costs']
    before=project();after=with_cost_inputs(before,raw)
    restored=PCBProject.model_validate_json(after.model_dump_json())
    report=estimate_saved_cost(restored)
    assert report['known_subtotals']=={'USD':'2.50'}
    assert report['conditional_ranges']['USD']==dict(minimum='2.50',maximum='2.50')
    assert 'shipping' not in report['unknown_additional_costs'] and 'pcb_fabrication' in report['unknown_additional_costs']
    assert before.budget.cost_inputs is None and report['complete_total'] is None


def test_half_filled_cost_range_is_not_completed_with_zero():
    host,inputs=form(partial=True)
    with pytest.raises(ValueError,match='함께'):inputs(host)


def test_budget_quantity_edit_preserves_price_inputs_and_undo():
    host,inputs=form();before=with_cost_inputs(project(),inputs(host));session=PCBWorkflowSession(before)
    changed=[]
    fake=SimpleNamespace(project=before,quantity=SimpleNamespace(value=lambda:21),currency=SimpleNamespace(text=lambda:'USD'),limit=SimpleNamespace(text=lambda:''),
        set_project=lambda raw:changed.append(session.replace(raw)),cost_estimate=lambda:None,error=lambda exc:pytest.fail(str(exc)))
    extracted('pcb_workbench.py','PCBWorkbench','update_budget')(fake)
    assert len(changed)==1 and read_cost_inputs(changed[0])==read_cost_inputs(before)
    assert changed[0].budget.board_quantity==21 and session.undo()==before


def test_local_cost_input_commit_is_one_undoable_change_before_cad_apply():
    before=project();saved=before.model_dump(mode='json');host,inputs=form(zero_shipping=True)
    session=PCBWorkflowSession(before);candidate=with_cost_inputs(before,inputs(host));session.replace(candidate)
    assert session.current()!=before and before.model_dump(mode='json')==saved
    assert session.undo()==before and not session.can_undo


def test_price_generation_does_not_adopt_and_dialog_requires_explicit_confirmation():
    text,functions=methods('pcb_workbench.py','PCBWorkbench');review=ast.get_source_segment(text,functions['review'])
    assert 'cost_proposal_request' in review and 'propose_cost' in review
    assert 'self.set_project' not in review and 'adopt_cost_proposal' not in review
    assert 'self.ai_identity()==(model,effort)' in review and 'pcb_digest(self.project)==sha' in review
    preview=ast.get_source_segment(text,functions['preview_cost_proposal'])
    assert 'pcb_digest(self.project)!=base' in preview and 'self.set_project(dialog.checked)' in preview
    dialog,funcs=methods('pcb_cost_dialog.py','PCBCostProposalDialog');accept=ast.get_source_segment(dialog,funcs['accept'])
    assert 'self.confirm.isChecked()' in accept and 'adopt_cost_proposal(self.project,self.proposal)' in accept
    assert 'applyRequested.emit' not in dialog


def test_ref_tier_rebinding_requires_explicit_form_choice():
    text,functions=methods('pcb_cost_dialog.py','PCBCostInputsDialog');accept=ast.get_source_segment(text,functions['accept'])
    assert 'rebind_quantity_breaks=self.rebind_tiers.isChecked()' in accept
    assert 'self.rebind_tiers.setChecked(True)' not in text


def adopted():
    p=project()
    return adopt_cost_proposal(p,dict(schema_version=1,base_sha256=pcb_digest(p),status='ai_estimate',summary='Synthetic estimate only',
        rows=[dict(refs=['U1'],mpn='Synthetic SKU',required_quantity=20,purchase_quantity=20,minimum_unit_price='1',maximum_unit_price='2',
            currency='USD',as_of=None,source_url='',basis='Synthetic fixture only, not a market quote',status='ai_estimate')]))


def test_ai_identity_binding_survives_editing_only_additional_costs():
    before=adopted();host,inputs=form(zero_shipping=True);host.tiers.rows=[]
    host.saved=read_cost_inputs(before).model_dump(mode='json')
    after=with_cost_inputs(before,inputs(host));report=estimate_saved_cost(after)
    assert read_cost_inputs(after).accepted_ai_bindings==read_cost_inputs(before).accepted_ai_bindings
    assert len(report['used_ai_estimates'])==1 and not report['stale_ai_estimates']
    assert report['conditional_ranges']['USD']==dict(minimum='20.00',maximum='40.00')


def test_clear_ai_form_choice_removes_estimates_and_their_bindings_only():
    before=adopted();host,inputs=form();host.tiers.rows=[];host.saved=read_cost_inputs(before).model_dump(mode='json')
    host.clear_ai=SimpleNamespace(isChecked=lambda:True)
    after=with_cost_inputs(before,inputs(host));saved=read_cost_inputs(after)
    assert not saved.accepted_ai_estimates and not saved.accepted_ai_bindings
    assert before.components==after.components and read_cost_inputs(before).accepted_ai_estimates
