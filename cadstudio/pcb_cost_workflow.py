"""Detached cost drafts and qualified totals; no fetching, purchases or execution."""
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json

from .pcb import PCBProject, pcb_digest
from .pcb_cost_models import PCBCostInputs, CostAIProposal, ADDITIONAL_COSTS


def read_cost_inputs(project):
    p=PCBProject.model_validate(project)
    value=p.budget.cost_inputs
    return PCBCostInputs.model_validate(value.model_dump() if value is not None else {})


def _purchase_identity(component):
    meta=component.library_metadata
    value={key:getattr(component,key) for key in ('mpn','value','footprint','footprint_basis','source_url')}
    value['model']=component.model.model_dump(mode='json')
    value['library']={key:getattr(meta,key) for key in ('catalog_id','manufacturer','model','revision','source_url')} if meta else None
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()



def _context_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _schedule_quote_context(row,tiers):
    return _context_digest(dict(quote=row['quote'],tiers=[tier.model_dump(mode='json') for tier in tiers]))


def _ai_quote_context(components,row,inputs):
    keys=set(row.refs)|({row.mpn} if row.mpn else set())
    return _context_digest(dict(
        estimate=row.model_dump(mode='json'),
        quotes={ref:components[ref].quote.model_dump(mode='json') for ref in row.refs},
        tiers={key:[tier.model_dump(mode='json') for tier in tiers] for key,tiers in inputs.quantity_breaks.items() if key in keys}))


def with_cost_inputs(project,inputs,*,rebind_quantity_breaks=False):
    p=PCBProject.model_validate(project)
    raw=p.model_dump(mode='json')
    if inputs is None:raw['budget']['cost_inputs']=None
    else:
        checked=PCBCostInputs.model_validate(inputs);old=read_cost_inputs(p)
        from .pcb_embedded import estimate_cost
        bom=estimate_cost(p)['rows']
        bindings={};contexts={};components={c.ref:c for c in p.components}
        for key in checked.quantity_breaks:
            if key in old.quantity_breaks and not rebind_quantity_breaks:
                if key in old.quantity_break_bindings:bindings[key]=old.quantity_break_bindings[key].model_dump()
            elif key in components:
                bindings[key]=dict(kind='ref',ref=key,purchase_identity_sha256=_purchase_identity(components[key]))
            if key in old.quantity_breaks and not rebind_quantity_breaks:
                if key in old.quantity_break_contexts:contexts[key]=old.quantity_break_contexts[key]
            else:
                matches=[row for row in bom if key==row['mpn'] or key in row['refs']]
                if len(matches)==1:contexts[key]=_schedule_quote_context(matches[0],checked.quantity_breaks[key])
        value=checked.model_dump(mode='json');value['quantity_break_bindings']=bindings;value['quantity_break_contexts']=contexts
        ai_keys={_row_binding_key(row) for row in checked.accepted_ai_estimates}
        value['accepted_ai_quote_contexts']={key:context for key,context in checked.accepted_ai_quote_contexts.items() if key in ai_keys}
        raw['budget']['cost_inputs']=PCBCostInputs.model_validate(value).model_dump(mode='json')
    return PCBProject.model_validate(raw)


def _key(row):
    refs=row.refs if hasattr(row,'refs') else row['refs']
    mpn=row.mpn if hasattr(row,'mpn') else row['mpn']
    return tuple(sorted(refs)),mpn


def _row_binding_key(row):
    return hashlib.sha256(json.dumps(_key(row),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _eligible(row,bom):
    actual=bom.get(_key(row))
    if actual is None:return False,'BOM refs/MPN changed or row is no longer purchased.'
    if row.required_quantity!=actual['required_quantity'] or row.purchase_quantity!=actual['purchase_quantity']:
        return False,'BOM required/purchase quantity changed.'
    return True,''


def _base_estimate(project,inputs,*,quantity_breaks=None,rounding='0.01'):
    from .pcb_embedded import estimate_cost
    schedules,_=_saved_schedules(project,inputs)
    return estimate_cost(project,quantity_breaks=schedules if quantity_breaks is None else quantity_breaks,rounding=rounding)


def _saved_schedules(project,inputs):
    from .pcb_embedded import estimate_cost
    p=PCBProject.model_validate(project);components={c.ref:c for c in p.components}
    bom=estimate_cost(p)['rows'];schedules={};stale={}
    for key,rows in inputs.quantity_breaks.items():
        matches=[row for row in bom if key==row['mpn'] or key in row['refs']]
        binding=inputs.quantity_break_bindings.get(key)
        if len(matches)!=1:stale[key]='Schedule key is absent or ambiguously matches multiple BOM rows.'
        elif binding is not None:
            component=components.get(binding.ref)
            if binding.ref!=key or component is None or _purchase_identity(component)!=binding.purchase_identity_sha256:
                stale[key]='Reference purchase identity changed; explicitly recheck and rebind this price schedule.'
        elif key in components:
            stale[key]='Reference price schedule has no confirmed purchase identity; explicit rebind required.'
        if key not in stale and inputs.quantity_break_contexts.get(key)!=_schedule_quote_context(matches[0],rows):
            stale[key]='Quote or tier currency/date/source context is missing or changed; explicitly review and rebind this schedule.'
        if key not in stale:schedules[key]=[row.model_dump(mode='json') for row in rows]
    return schedules,stale


def estimate_saved_cost(project,*,quantity_breaks=None,rounding='0.01'):
    p=PCBProject.model_validate(project).model_copy(deep=True);inputs=read_cost_inputs(p)
    result=_base_estimate(p,inputs,quantity_breaks=quantity_breaks,rounding=rounding)
    bom={_key(row):row for row in result['rows']};eligible={};stale=[]
    components={c.ref:c for c in p.components}
    for row in inputs.accepted_ai_estimates:
        valid,reason=_eligible(row,bom)
        if valid:
            binding=inputs.accepted_ai_bindings.get(_row_binding_key(row))
            if not binding or set(binding)!=set(row.refs) or any(ref not in components or _purchase_identity(components[ref])!=identity for ref,identity in binding.items()):
                valid=False;reason='AI estimate purchase identity is missing or changed; a fresh proposal/adoption is required.'
        if valid and inputs.accepted_ai_quote_contexts.get(_row_binding_key(row))!=_ai_quote_context(components,row,inputs):
            valid=False;reason='AI estimate quote or saved-tier currency/date/source context is missing or changed; a fresh proposal/adoption is required.'
        if valid:eligible[_key(row)]=row
        else:stale.append(dict(row=row.model_dump(mode='json'),reason=reason))
    totals={};contributions=[];unpriced=[];used=[];unused=[];quantum=Decimal(str(rounding))
    def add(currency,low,high,kind,refs):
        if currency not in totals:totals[currency]=[Decimal(0),Decimal(0)]
        totals[currency][0]+=low;totals[currency][1]+=high
        contributions.append(dict(currency=currency,minimum=str(low),maximum=str(high),kind=kind,refs=refs))
    ownership_unknown=set(result['ownership_unknown_refs'])
    for key,row in bom.items():
        estimate=eligible.get(key)
        if row['rounded_subtotal'] is not None:
            amount=Decimal(row['rounded_subtotal']);add(row['quote']['currency'],amount,amount,'entered_quote',row['refs'])
            if estimate:unused.append(dict(row=estimate.model_dump(mode='json'),reason='Existing entered quote/tier retained; AI estimate does not replace it.'))
        elif estimate and not ownership_unknown.intersection(row['refs']):
            low=(estimate.minimum_unit_price*row['purchase_quantity']).quantize(quantum,rounding=ROUND_HALF_UP)
            high=(estimate.maximum_unit_price*row['purchase_quantity']).quantize(quantum,rounding=ROUND_HALF_UP)
            add(estimate.currency,low,high,'ai_estimate',row['refs']);used.append(estimate.model_dump(mode='json'))
        else:
            unpriced.extend(row['refs'])
            if estimate:unused.append(dict(row=estimate.model_dump(mode='json'),reason='Purchased module ownership remains unknown.'))
    for name,value in inputs.additional_costs.items():
        add(value.currency,value.minimum,value.maximum,name,[])
    _,stale_schedules=_saved_schedules(p,inputs)
    unknown_additional=[key for key in ADDITIONAL_COSTS if key not in inputs.additional_costs]
    result.update(saved_inputs=inputs.model_dump(mode='json'),
        conditional_ranges={currency:dict(minimum=str(bounds[0]),maximum=str(bounds[1])) for currency,bounds in sorted(totals.items())},
        range_contributions=contributions,unpriced_component_refs=sorted(set(unpriced)|ownership_unknown),
        unknown_additional_costs=unknown_additional,used_ai_estimates=used,stale_ai_estimates=stale,unused_ai_estimates=unused,ignored_ai_estimates=unused,
        stale_quantity_break_keys=sorted(stale_schedules),stale_quantity_breaks=stale_schedules,
        conditional_inputs_complete=not unpriced and not ownership_unknown and not unknown_additional,
        complete_total=None,estimated_complete=False,prices_verified=False,
        qualification='Conditional sums of entered quotes and explicitly adopted estimate ranges, separated by currency. Missing costs remain unknown; no live price, FX, inventory, complete quote or purchase approval.')
    return result


def validate_cost_proposal(project,proposal):
    p=PCBProject.model_validate(project)
    checked=CostAIProposal.model_validate(proposal)
    if checked.base_sha256!=pcb_digest(p):raise ValueError('PCB/BOM changed; generate a fresh cost proposal before adopting.')
    report=_base_estimate(p,read_cost_inputs(p));bom={_key(row):row for row in report['rows']}
    for row in checked.rows:
        valid,reason=_eligible(row,bom)
        if not valid:raise ValueError('Cost proposal row does not match current purchased BOM: '+reason)
    return checked


def adopt_cost_proposal(project,proposal):
    """Return a detached local draft only; caller owns explicit adoption/Undo/save."""
    p=PCBProject.model_validate(project);checked=validate_cost_proposal(p,proposal)
    if not checked.rows:raise ValueError('No estimate rows to adopt; pricing remains unknown because the estimate basis is insufficient.')
    inputs=read_cost_inputs(p);adopted={_key(row):row for row in inputs.accepted_ai_estimates}
    adopted.update({_key(row):row for row in checked.rows})
    raw=inputs.model_dump(mode='json');raw['accepted_ai_estimates']=[row.model_dump(mode='json') for row in adopted.values()]
    bindings=dict(inputs.accepted_ai_bindings);components={c.ref:c for c in p.components}
    for row in checked.rows:bindings[_row_binding_key(row)]={ref:_purchase_identity(components[ref]) for ref in row.refs}
    raw['accepted_ai_bindings']=bindings
    contexts=dict(inputs.accepted_ai_quote_contexts)
    for row in checked.rows:contexts[_row_binding_key(row)]=_ai_quote_context(components,row,inputs)
    raw['accepted_ai_quote_contexts']=contexts
    return with_cost_inputs(p,raw)
