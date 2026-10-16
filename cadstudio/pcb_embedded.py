"""Offline embedded-product references, explicit footprints and qualified review.

Catalog/header pin references never supply physical PCB coordinates. All
geometry and operating conditions remain explicit declarations on a copy.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math

from .electrical_catalog import search_catalog, get_catalog_entry
from .board_pins import board_pinout
from .pcb import (PCBProject, PCBComponent, PCBLibraryMetadata, PCBQuote,
                  pcb_digest, inspect_layout, bom_report, pad_positions, source_url)


def _catalog_row(entry):
    pinout = board_pinout(entry.catalog_id)
    return dict(catalog_id=entry.catalog_id, category=entry.category,
        manufacturer=entry.manufacturer, model=entry.model, source_url=entry.source_url,
        spec_summary=entry.spec_summary, reference_only=entry.reference_only,
        verification_level='catalog_reference_only', operating_current_a=None,
        logical_pins=[dict(key=p.key,label=p.label,functions=list(p.functions),kind=p.kind) for p in pinout.pins] if pinout else [],
        logical_pin_source_url=pinout.source_url if pinout else None,
        logic_voltage_reference_v=pinout.logic_voltage_v if pinout else None,
        physical_pin_coordinates_verified=False,
        qualification='Logical connector references only; no package pad XY, footprint, consumption or safety qualification is inferred.')


def search_embedded(query='', *, limit=30):
    if not isinstance(query, str) or len(query)>200 or type(limit) is not int or not 1<=limit<=50:
        raise ValueError('Use a bounded catalog query (200 characters,1–50 results).')
    return [_catalog_row(entry) for entry in search_catalog(query,limit=limit)]


def catalog_product(catalog_id):
    entry=get_catalog_entry(catalog_id)
    if entry is None:
        raise ValueError('Unknown catalog product.')
    return _catalog_row(entry)


def component_from_catalog(catalog_id, footprint, *, library_metadata=None):
    entry=get_catalog_entry(catalog_id)
    if entry is None:
        raise ValueError('Unknown catalog product.')
    raw=deepcopy(footprint.model_dump(mode='json') if isinstance(footprint,PCBComponent) else footprint)
    if not isinstance(raw,dict) or not {'ref','footprint','x_mm','y_mm','rotation_deg','body_width_mm','body_height_mm','pins'}<=raw.keys():
        raise ValueError('Supply the complete explicit footprint: ref/package, placement/rotation, body dimensions and all pads.')
    if not isinstance(raw['pins'],list) or not raw['pins'] or any(not isinstance(pin,dict) or not {'number','x_mm','y_mm','layers'}<=pin.keys()
            or not ('diameter_mm' in pin or {'size_x_mm','size_y_mm'}<=pin.keys()) for pin in raw['pins']):
        raise ValueError('Every physical pad needs an explicit number, XY in mm, copper layers and outer size; logical pin drawings cannot provide these.')
    meta=deepcopy(library_metadata.model_dump(mode='json') if isinstance(library_metadata,PCBLibraryMetadata) else library_metadata or {})
    if not isinstance(meta,dict):raise ValueError('Library metadata must be an explicit declaration mapping.')
    if not all((meta.get('geometry_complete_declared') is True,meta.get('coordinate_units')=='mm',
                meta.get('pin1_number'),meta.get('mounted_side'),meta.get('orientation_reference'),
                meta.get('body_height_mm') is not None,meta.get('service_clearance_mm') is not None)):
        raise ValueError('Acknowledge complete user-declared geometry, mm units, pin1/side/orientation, body height and service clearance.')
    if entry.reference_only and (not meta.get('model') or meta['model']==entry.model):
        raise ValueError('A product-family reference is not an exact SKU. Supply the exact user-declared model.')
    meta.update(catalog_id=entry.catalog_id,manufacturer=meta.get('manufacturer') or entry.manufacturer,
                model=meta.get('model') or entry.model,source_url=meta.get('source_url') or entry.source_url)
    pinout=board_pinout(catalog_id)
    keys={pin.key for pin in pinout.pins} if pinout else set()
    if not isinstance(meta.get('pin_specs',[]),list) or any(not isinstance(s,dict) for s in meta.get('pin_specs',[])):
        raise ValueError('Pin operating specifications must be a list of explicit mappings.')
    for spec in meta.get('pin_specs',[]):
        if spec.get('logical_pin_key') and spec['logical_pin_key'] not in keys:
            raise ValueError('Logical pin reference is not present in the selected exact board reference.')
    # A quotation for the previous purchase identity is not a quote for the
    # newly selected product. Keeping it would create a misleading priced BOM.
    previous=raw.get('library_metadata') or {}
    if raw.get('mpn')!=meta['model'] or (previous.get('catalog_id') and previous['catalog_id']!=catalog_id):
        raw['quote']=PCBQuote().model_dump(mode='json')
    raw.update(library_metadata=meta,mpn=meta['model'],source_url=meta['source_url'])
    if not raw.get('value'):
        raw['value']=meta['model']
    return PCBComponent.model_validate(raw)


def bind_catalog_product(project, ref, catalog_id, *, footprint, library_metadata=None):
    p=PCBProject.model_validate(project).model_copy(deep=True)
    before=next((c for c in p.components if c.ref==ref),None)
    if before is None:
        raise ValueError('Select an existing PCB component reference.')
    replacement=component_from_catalog(catalog_id,footprint,library_metadata=library_metadata)
    # Product binding must not detach existing copper or silently replace an
    # electrical model. Physical footprint replacement is a separate edit.
    for key in ('ref','x_mm','y_mm','rotation_deg','body_width_mm','body_height_mm','pins','model'):
        if getattr(before,key)!=getattr(replacement,key):
            raise ValueError('Product binding cannot move/resize/remap existing pads, nets or models; use a separate explicit footprint edit.')
    raw=p.model_dump(mode='json')
    raw['components']=[replacement.model_dump(mode='json') if c.ref==ref else c.model_dump(mode='json') for c in p.components]
    return PCBProject.model_validate(raw)


def _bounded_layout(project):
    complexity=dict(pads=sum(len(c.pins) for c in project.components),
        segments=sum(len(t.points)-1 for t in project.tracks),vias=len(project.vias),
        vertices=sum(len(z.outline)+sum(len(h) for h in z.holes)+sum(len(p.points)+sum(len(h) for h in p.holes) for p in z.filled_polygons) for z in project.zones))
    if complexity['pads']>256 or complexity['segments']>512 or complexity['vias']>256 or complexity['vertices']>512:
        return dict(status='not_run_resource_limit',pcb_sha256=pcb_digest(project),checked_layers=[],
            findings=[dict(code='review_resource_scope',severity='warning',refs=[],
                message='Large layout exceeds the bounded interactive review scope; geometric violations are unknown, not zero.')],
            input_complexity=complexity,manufacturing_qualified=False)
    return inspect_layout(project)


def review_embedded(project, *, net_conditions=None):
    p=PCBProject.model_validate(project).model_copy(deep=True)
    conditions=deepcopy(net_conditions or {})
    if not isinstance(conditions,dict) or not set(conditions)<=set(p.nets):
        raise ValueError('Electrical conditions must refer to declared PCB nets.')
    for value in conditions.values():
        if not isinstance(value,dict) or not set(value)<= {'voltage_v','source_current_limit_a','declared_load_current_a','source_url','condition'}:
            raise ValueError('Supply only explicit voltage/load/current-limit/source/condition fields.')
        for key in ('voltage_v','source_current_limit_a','declared_load_current_a'):
            number=value.get(key)
            if number is not None and (type(number) not in (int,float) or not math.isfinite(number)
                    or abs(number)>100000 or (key!='voltage_v' and number<0)):
                raise ValueError('Invalid declared electrical operating condition.')
        for key,limit in (('source_url',500),('condition',500)):
            if key in value and (not isinstance(value[key],str) or len(value[key])>limit):
                raise ValueError('Electrical condition notes/sources must be bounded strings.')
        source_url(value.get('source_url',''))
    layout=_bounded_layout(p);checks=[]
    def item(name,status,refs,inputs,message,action,source='user_declared'):
        checks.append(dict(name=name,status=status,refs=refs,inputs=inputs,message=message,
                           source=source,action=action))
    if layout['status']=='not_run_resource_limit':
        item('copper_geometry','unknown',[],layout['input_complexity'],'Geometric inspection was not run; zero violations must not be inferred.','Run a separately bounded/exported detailed DRC.')
    for finding in layout['findings']:
        item('layout_'+finding['code'],'violation' if finding['severity']=='error' else 'unknown',finding['refs'],{},finding['message'],'Review the stored DRC finding.','declared_geometry_model')
    positions={(pad['ref'],pad['pin']):[pad['x'],pad['y']] for pad in pad_positions(p)}
    net_loads={net:[] for net in p.nets};unmodeled_loads=set();output_limits=[]
    for component in p.components:
        meta=component.library_metadata
        if not component.fitted:
            item('unfitted_component','unknown',[component.ref],{},'Optional unpopulated component is excluded from operating-current checks.','Confirm the populated assembly separately.')
            continue
        if meta is None:
            unmodeled_loads.update(pin.net for pin in component.pins if pin.net)
            item('footprint_source','unknown',[component.ref],{},'No dimensioned library footprint/pin rating declaration is attached.','Supply exact product/revision, physical pad geometry and operating conditions.')
            continue
        item('footprint_source','declared_check' if meta.footprint_review_state=='source_reviewed' else 'unknown',[component.ref],
            dict(review_state=meta.footprint_review_state,revision=meta.revision),
            'Dated reviewer/source record stored; this is not independent physical verification.' if meta.footprint_review_state=='source_reviewed' else 'User-declared geometry remains source-unverified.',
            'Check the exact package/revision against the cited drawing.',meta.source_url or 'user_declared')
        specs={spec.number:spec for spec in meta.pin_specs}
        for pin in component.pins:
            spec=specs.get(pin.number);refs=[component.ref,pin.number]
            inputs=dict(net=pin.net,position_mm=positions[(component.ref,pin.number)])
            if spec is None or spec.role=='unknown':
                if pin.net:unmodeled_loads.add(pin.net)
                item('pin_operating_rating','unknown',refs,inputs,'Pin operating range/direction is undeclared; catalog PSU advice and absolute maxima are not substituted.','Enter the actual pin operating specifications and source.')
                continue
            if spec.role=='passive' and pin.net:
                # Passive does not mean zero draw: a resistor/capacitor network
                # requires an actual circuit/operating-point solution. This
                # declaration review deliberately does not run that solver.
                unmodeled_loads.add(pin.net)
            declared=conditions.get(pin.net,{})
            voltage=declared.get('voltage_v')
            return_net=spec.ground_reference_net
            grounds=[q for q in component.pins if (s:=specs.get(q.number)) and s.role=='ground' and q.net==return_net]
            return_voltage=conditions.get(return_net,{}).get('voltage_v') if return_net else None
            has_reference=bool(return_net and return_net!=pin.net and grounds and return_voltage is not None)
            differential=voltage-return_voltage if voltage is not None and has_reference else None
            if spec.role not in ('ground','passive'):
                if differential is None or spec.operating_min_v is None or spec.operating_max_v is None:
                    item('pin_voltage','unknown',refs,inputs,'Actual differential voltage, distinct mapped return potential or pin operating range is unspecified.','Declare operating range and actual net/return operating conditions.',spec.source_url or 'user_declared')
                else:
                    valid=spec.operating_min_v<=differential<=spec.operating_max_v
                    item('pin_voltage','declared_check' if valid else 'violation',refs,
                        dict(**inputs,voltage_v=voltage,return_voltage_v=return_voltage,differential_voltage_v=differential,operating_range_v=[spec.operating_min_v,spec.operating_max_v]),
                        'Explicit declared values are compatible.' if valid else 'Declared operating voltage exceeds the explicit operating range.',
                        'Verify this operating point against the actual source; do not use absolute-max as a normal range.',spec.source_url or 'user_declared')
            if pin.net is None:
                item('pin_connection','violation',refs,inputs,'A declared functional pin has no assigned net.','Assign the intended net or explicitly document NC.')
            if spec.role=='power_in' and pin.net:
                net_loads[pin.net].append(spec.operating_current_a)
                if spec.current_limit_a is not None:
                    item('pin_current','unknown' if spec.operating_current_a is None else 'declared_check' if spec.operating_current_a<=spec.current_limit_a else 'violation',refs,
                        dict(**inputs,operating_current_a=spec.operating_current_a,current_limit_a=spec.current_limit_a),
                        'Comparison uses only the explicitly declared pin operating current and limit.',
                        'Check duty, transient current and the exact operating specification.',spec.source_url or 'user_declared')
                if not return_net or return_net==pin.net or not grounds:
                    item('power_return','unknown',refs,inputs,'A corresponding explicit ground/return pin mapping has not been established.','Declare and check the power return path; a net name alone is not a copper path.')
            if spec.role=='power_out' and pin.net:
                output_limits.append((pin.net,refs,spec.current_limit_a))
    for net, condition in conditions.items():
        capacity=condition.get('source_current_limit_a');explicit=condition.get('declared_load_current_a')
        loads=net_loads[net]
        total=explicit if explicit is not None else sum(loads) if net not in unmodeled_loads and loads and all(v is not None for v in loads) else None
        if capacity is None or total is None:
            item('current_budget','unknown',[net],dict(source_current_limit_a=capacity,operating_load_current_a=total),
                'A complete explicit operating current budget or source limit is missing.','Declare all loads/operating duty and protection limits; recommended PSU ratings are not consumption.')
        else:
            item('current_budget','declared_check' if total<=capacity else 'violation',[net],dict(source_current_limit_a=capacity,operating_load_current_a=total),
                'Explicit declared load fits the explicit limit.' if total<=capacity else 'Declared load exceeds the explicit source/current limit.',
                'Verify conductor, connector, fuse, duty and transient conditions separately.')
    outputs_per_net={net:sum(row[0]==net for row in output_limits) for net,_,_ in output_limits}
    for net,refs,limit in output_limits:
        explicit=conditions.get(net,{}).get('declared_load_current_a');loads=net_loads[net]
        total=explicit if explicit is not None else sum(loads) if net not in unmodeled_loads and loads and all(v is not None for v in loads) else None
        # A whole-rail load is not the current delivered by EACH parallel
        # source. No current sharing/backfeed behavior is inferred here.
        parallel=outputs_per_net[net]>1
        item('output_current_limit','unknown' if parallel or total is None or limit is None else 'declared_check' if total<=limit else 'violation',refs,
             dict(net=net,declared_load_current_a=total,current_limit_a=limit,parallel_output_count=outputs_per_net[net],per_output_current_a=None if parallel else total),
             'Parallel output sharing/current is undeclared; the total rail load is not assigned to each source.' if parallel else 'Output pin limit is compared only with a complete explicit declared load budget; unmodeled loads remain unknown.',
             'Verify the exact output rating, sharing, duty, protection and transient conditions separately.')
    for name in ('thermal_and_insulation','mechanical_mating_and_clearance','physical_commissioning'):
        item(name,'unknown',[],{},'No complete physical/material/ambient or mating/commissioning evidence was supplied.','Review real parts and applicable conditions before fabrication or energizing.')
    return dict(pcb_sha256=pcb_digest(p),layout=layout,checks=checks,
        violations=sum(c['status']=='violation' for c in checks),unknowns=sum(c['status']=='unknown' for c in checks),
        declared_checks=sum(c['status']=='declared_check' for c in checks),status='review_required',
        physical_safety_qualified=False,hardware_IO=False,
        qualification='Declared-data and geometric review only; unknown inputs never become a global safety pass.')


def _purchased(project):
    by_ref={c.ref:c for c in project.components};excluded=[];unknown=[];keep=[]
    for component in project.components:
        if not component.fitted:
            # bom_report omits unpopulated rows too. Ownership uncertainty of
            # an unpopulated internal model is not an unknown purchase.
            continue
        meta=component.library_metadata
        if meta and meta.bom_role=='internal_model':
            parent=by_ref[meta.module_parent_ref]
            while parent.library_metadata and parent.library_metadata.bom_role=='internal_model':
                parent=by_ref[parent.library_metadata.module_parent_ref]
            if parent.fitted:
                excluded.append(dict(ref=component.ref,purchased_parent=parent.ref))
                continue
            unknown.append(component.ref)
        keep.append(component)
    # Exclusion is a BOM projection only, not a routable PCB. Descendants of a
    # non-fitted parent remain unknown priced rows, with their ownership removed
    # only in this private projection so no dangling references are introduced.
    data=project.model_dump(mode='json');data['components']=[]
    for c in keep:
        row=c.model_dump(mode='json')
        if c.ref in unknown:
            row['library_metadata']['bom_role']='purchased'
            row['library_metadata']['module_parent_ref']=None
        data['components'].append(row)
    return PCBProject.model_validate(data),excluded,unknown


def estimate_cost(project, *, quantity_breaks=None, rounding='0.01'):
    p=PCBProject.model_validate(project).model_copy(deep=True)
    try:quantum=Decimal(str(rounding))
    except InvalidOperation:raise ValueError('Invalid monetary rounding quantum.') from None
    if not quantum.is_finite() or quantum<=0 or quantum>1 or quantum.as_tuple().digits!=(1,) or not -6<=quantum.as_tuple().exponent<=0:
        raise ValueError('Choose a power-of-ten rounding quantum from 1 to 0.000001.')
    purchased,excluded,ownership_unknown=_purchased(p)
    report=bom_report(purchased);breaks=quantity_breaks or {}
    if not isinstance(breaks,dict) or len(breaks)>128:
        raise ValueError('Quantity breaks must be a bounded ref/MPN mapping.')
    rows=deepcopy(report['rows']);totals={};exact_totals={};unknown=[]
    for row in rows:
        variants=[breaks[key] for key in [row['mpn'],*row['refs']] if key and key in breaks]
        if variants and any(value!=variants[0] for value in variants):
            raise ValueError('Conflicting quantity-break schedules for one grouped BOM row.')
        if variants:
            schedule=variants[0]
            if not isinstance(schedule,list) or len(schedule)>128:
                raise ValueError('Quantity-break schedule is too large.')
            eligible=[];seen=set()
            for entry in schedule:
                if not isinstance(entry,dict) or not set(entry)<= {'minimum_quantity','unit_price','currency','status','as_of','supplier','source_url','note'}:
                    raise ValueError('A price tier supplies price provenance and threshold only; package/MOQ changes need an explicit BOM edit.')
                threshold=entry.get('minimum_quantity')
                if type(threshold) is not int or threshold<1 or threshold in seen:
                    raise ValueError('Quantity-break minimum quantities must be positive and unique.')
                seen.add(threshold)
                quote=PCBQuote.model_validate({**row['quote'],**entry})
                if threshold<=row['purchase_quantity']:
                    eligible.append((threshold,quote))
            if eligible:
                _,quote=max(eligible,key=lambda pair:pair[0]);row['quote']=quote.model_dump(mode='json')
        q=row['quote'];value=q['unit_price']
        row['price_is_current_offer']=False
        if value is None:
            row.update(subtotal=None,rounded_subtotal=None);unknown.extend(row['refs'])
            continue
        exact=Decimal(value)*row['purchase_quantity'];rounded=exact.quantize(quantum,rounding=ROUND_HALF_UP)
        row.update(subtotal=str(exact),rounded_subtotal=str(rounded))
        currency=q['currency'];totals[currency]=totals.get(currency,Decimal(0))+rounded
        exact_totals[currency]=exact_totals.get(currency,Decimal(0))+exact
    unknown=sorted(set(unknown+ownership_unknown))
    return dict(pcb_sha256=pcb_digest(p),rows=rows,excluded_internal_models=excluded,
        ownership_unknown_refs=ownership_unknown,unknown_refs=unknown,
        known_subtotals={key:str(value) for key,value in sorted(totals.items())},
        exact_known_subtotals={key:str(value) for key,value in sorted(exact_totals.items())},
        rounding=dict(quantum=str(quantum),mode='ROUND_HALF_UP',basis='round_each_line_then_sum_per_currency'),
        component_prices_complete=not unknown,
        single_currency_component_total=str(next(iter(totals.values()))) if not unknown and len(totals)==1 else None,
        additional_costs=dict(pcb_fabrication=None,assembly_consumables=None,shipping=None,tax_import=None),
        complete_total=None,estimated_complete=False,currency_conversion_performed=False,
        quote_inputs=dict(width_mm=p.width_mm,height_mm=p.height_mm,layer_count=p.layer_count,thickness_mm=p.thickness_mm,
            board_quantity=p.budget.board_quantity,requested_currency=p.budget.currency,material=None,copper_thickness=None,
            finish=None,assembly_included=None,region=None),
        qualification='Stored/user-entered estimates only, not live supplier prices, inventory, delivery commitments or a complete project total.')
