"""Bundled native engineering checks using synthetic local data only."""
from copy import deepcopy
import json
import time
import traceback

import numpy as np
from PySide6.QtCore import QThreadPool, QEvent
from PySide6.QtTest import QTest
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter

from ..models import Design, Part
from ..kernel import preview
from ..electrical import ElectricalWorkspace
from ..measurement_catalog import catalog_measurement
from ..measurement_specs import ForceChainSpec
from .document import Document, read_project


def _synthetic_chain():
    """Explicit example settings and logical pin wiring, never a live device."""
    load=catalog_measurement('hbk_u10m_25kn_passive').model_dump()
    load.update(excitation_voltage_v=2.5,sensitivity_mv_per_v=2.2)
    adc=catalog_measurement('ti_ads131m04').model_dump()
    adc.update(gain=64,sample_rate_sps=4000,analog_supply_voltage_v=3.3,digital_supply_voltage_v=3.3,
               clock_frequency_hz=8192000,oversampling_ratio=1024,power_mode='high_resolution')
    components=[
        dict(id='excitation',name='Synthetic excitation',kind='battery',a='EXC',b='GND',voltage_v=2.5),
        dict(id='adc_power',name='Synthetic ADC rail',kind='battery',a='AV',b='GND',voltage_v=3.3),
        dict(id='loadcell',name='Synthetic passive bridge',kind='load',a='LC_A',b='LC_B',catalog_id='hbk_u10m_25kn_passive',analysis_enabled=False,
             measurement=load,terminal_pins={'EXC_POS':'EXC','EXC_NEG':'GND','SIG_POS':'SIGP','SIG_NEG':'SIGN'}),
        dict(id='adc',name='Synthetic ADC settings',kind='load',a='ADC_A',b='ADC_B',catalog_id='ti_ads131m04',analysis_enabled=False,
             measurement=adc,terminal_pins={'AIN0P':'SIGP','AIN0N':'SIGN','AVDD':'AV','AGND':'GND','DVDD':'AV','DGND':'GND',
                 'SCLK':'CLK','DOUT':'DATA','DIN':'COMMAND','CS':'SELECT','DRDY':'READY','CLKIN':'OSC'}),
        dict(id='host',name='Synthetic host terminals',kind='mcu',a='HOST_A',b='HOST_B',catalog_id='rpi4b',analysis_enabled=False,
             signal_pins={'GPIO11':'CLK','GPIO9':'DATA','GPIO10':'COMMAND','GPIO8':'SELECT','GPIO17':'READY','GPIO18':'OSC'},
             board_supply_pins={'GND_6':'GND'},supply_pinout_catalog_id='rpi4b'),
    ]
    nodes=['GND','EXC','AV','SIGP','SIGN','CLK','DATA','COMMAND','SELECT','READY','OSC','LC_A','LC_B','ADC_A','ADC_B','HOST_A','HOST_B']
    spec=ForceChainSpec(source_id='excitation',load_cell_id='loadcell',adc_id='adc',controller_id='host',
        target_frequency_hz=1,target_peak_force_n=1000,
        controller_terminals={'clock':'pin:GPIO11','data_out':'pin:GPIO9','data_in':'pin:GPIO10',
            'chip_select':'pin:GPIO8','data_ready':'pin:GPIO17','ground':'supply:GND_6'})
    return ElectricalWorkspace.model_validate(dict(nodes=nodes,components=components,force_chain=spec.model_dump()))


def _requirements():
    return dict(protected_swept_bounds=dict(minimum_mm=[-30,-44,364.7],maximum_mm=[30,32,529.7]),
        static_rod_seals=[dict(id='upper',rod_diameter_mm=25,position_xy_mm=[0,6])],
        rod_interfaces=[dict(id='lower',face='bottom',rod_diameter_mm=25,position_xy_mm=[0,6],
            bellows_inner_diameter_mm=28,bellows_outer_diameter_mm=44,installed_length_mm=44)])


def _wait(app,condition,title,timeout=60):
    deadline=time.monotonic()+timeout
    while not condition() and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    if not condition():raise AssertionError('Timed out: '+title)


def _dispose(app,dialog):
    dialog.reject()
    if not QThreadPool.globalInstance().waitForDone(10000):raise AssertionError('Native preview worker did not stop')
    dialog.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()


def _capture(view,path,check):
    check(view.initialized and not view.closed and view.isVisible(),'capture uses a live initialized native viewport')
    view.render();capture=vtkWindowToImageFilter();capture.SetInput(view.window);capture.ReadFrontBufferOff();capture.Update()
    values=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())[:,:3]
    check(np.count_nonzero(np.max(values,axis=1)>120)>1000,'actual viewport pixels contain visible lit solids')
    from vtkmodules.vtkIOImage import vtkPNGWriter
    writer=vtkPNGWriter();writer.SetFileName(str(path));writer.SetInputConnection(capture.GetOutputPort());writer.Write()


def run(app,window,path):
    """Run only in an explicitly launched smoke process; own window is closed."""
    from .material_dialog import MaterialDialog
    from .studies import TensileStudy
    from ..material_assignments import assign_material
    from ..material_catalog import material_from_catalog
    from .force_acquisition_dialog import ForceAcquisitionDialog, MeasurementComponentDialog
    from .chamber_dialog import ChamberDialog

    path.parent.mkdir(parents=True,exist_ok=True);checks=[];dialogs=[];started=time.monotonic()
    def check(value,title):
        if not value:raise AssertionError(title)
        checks.append(title)
    def opened(dialog):dialogs.append(dialog);dialog.resize(1100,760);dialog.show();app.processEvents();return dialog
    try:
        app.setQuitOnLastWindowClosed(False);window.resize(1300,900);window.show();app.processEvents();QTest.qWait(100)
        raw=Design(parts=[
            Part(id='frame',name='Synthetic frame',geometry=dict(kind='plate',hole_count=0),transform=dict(x=150)),
            Part(id='specimen',name='Synthetic protected body',geometry=dict(kind='cylinder',diameter=8,height=30),transform=dict(z=430)),
            Part(id='coupon',name='Synthetic tensile coupon',geometry=dict(kind='round_specimen'),transform=dict(x=300)),
        ]).model_dump()
        before=deepcopy(raw);window.result=preview(Design.model_validate(raw));window.viewport.load(window.result)
        window.document=Document();window.document.commit(raw,'Synthetic engineering fixture');window.rebuild_tree()
        for key in ('materials','force_acquisition','chamber','specimen'):
            check(key in window.actions and window.actions[key].isEnabled(),'native menu exposes '+key)

        material=opened(MaterialDialog(window,raw,part_ids=['frame']))
        _wait(app,lambda:material.checked is not None,'initial material preview')
        check(not material.inputs['density'].text() and not material.apply_button.isEnabled(),'unknown material stays blank and cannot be applied implicitly')
        revision=material.revision;material.query.setText('6061');app.processEvents()
        check(material.revision==revision and material.checked.model_dump()==before,'catalog search is read-only')
        material.use_catalog();_wait(app,lambda:material.checked is not None and material.apply_button.isEnabled(),'catalog material selection')
        assigned=next(p for p in material.checked.parts if p.id=='frame').material
        check(assigned.catalog_id=='al_6061_t6_extruded' and assigned.poisson is None,'official material selection retains unsupported unknown property')
        check(next(p for p in material.checked.parts if p.id=='coupon').material is None,'material application remains scoped to explicit targets')
        _dispose(app,material);check(window.document.design==before,'material preview cancellation leaves CAD unchanged')

        tensile_raw=assign_material(raw,['coupon'],material_from_catalog('al_6061_t6_extruded')).model_dump()
        tensile=opened(TensileStudy(window,tensile_raw,part_id='coupon'));settings=deepcopy(tensile.settings())
        tensile.use_part_material()
        check('poisson' in tensile.status.text() and tensile.settings()==settings and tensile.checked is None,
              'incomplete material cannot silently populate a tensile analysis')
        _dispose(app,tensile)

        workspace=_synthetic_chain();original_electrical=workspace.model_dump()
        force=opened(ForceAcquisitionDialog(window,dict(parts=[],electrical=original_electrical)))
        force.frequency.setText('2');force.check_button.click();app.processEvents()
        check(force.result.status=='pending' and not force.result.hardware_verified,'configured bridge and ADC are pending physical qualification')
        check(force.result.metrics['samples_per_cycle']==2000,'native selected rate and frequency produce explicit samples per cycle')
        _dispose(app,force);check(workspace.model_dump()==original_electrical,'force-chain review cancellation preserves original electrical workspace')

        calibration=opened(MeasurementComponentDialog(window,workspace.components[2],workspace,'load_cell'))
        calibration.calibration_points.setPlainText('1000,0\n21000,100');calibration.calibrate();declared=calibration.candidate().calibration
        check(declared.status=='user_calibrated' and abs(declared.scale_n_per_count-.005)<1e-12,'native entered calibration points produce explicit N/count mapping')
        check(workspace.components[2].measurement.calibration.status=='uncalibrated','local calibration preview does not mutate its source')
        _dispose(app,calibration)

        broken=workspace.model_copy(deep=True);broken.components[2].terminal_pins['SIG_POS']='LC_A'
        fault=opened(ForceAcquisitionDialog(window,dict(parts=[],electrical=broken.model_dump())));fault.check_button.click();app.processEvents()
        check(fault.result.status=='blocked' and 'signal_positive_open' in {f.code for f in fault.result.findings},'actual open bridge signal path is blocked')
        _dispose(app,fault)

        chamber=opened(ChamberDialog(window,raw,requirements=_requirements()))
        _wait(app,lambda:chamber.checked is not None and not chamber.running,'full chamber preview')
        check(chamber.apply_button.isEnabled() and len(chamber.report['parts'])==33,'full stationary-top and moving-bottom chamber has 33 checked BREP parts')
        check(chamber.inputs['bottom-diameter'].value()==25 and not chamber.report['leak_test_verified'],'native Ø25 chamber controls do not claim tested leakage')
        _capture(chamber.viewport,path.with_name('engineering-chamber-viewport.png'),check)
        chamber.inspect_open.setChecked(True)
        check(not chamber.viewport.actors['chamber-door'][0].GetVisibility() and not chamber.viewport.actors['chamber-door'][1].GetVisibility(),
              'display disassembly hides both door faces and edges')
        check(len(chamber.checked.parts)==len(raw['parts'])+33,'display inspection retains every physical component')
        _capture(chamber.viewport,path.with_name('engineering-chamber-interior.png'),check)
        old=chamber.checked.assets['chamber-case-brep'].sha256;chamber.inputs['wall'].setValue(7)
        _wait(app,lambda:chamber.checked is not None and chamber.apply_button.isEnabled() and chamber.checked.assets['chamber-case-brep'].sha256!=old,'chamber wall edit')
        check(chamber.report['requirements']['wall_thickness_mm']==7,'native dimension change rebuilds the actual case BREP')
        candidate=chamber.checked.model_copy(deep=True);chamber_report=chamber.report;_dispose(app,chamber)
        check(window.document.design==before,'parametric chamber cancellation preserves the CAD source')

        obstructed=Design(parts=[Part(id='blocker',name='Synthetic wall obstruction',geometry=dict(kind='cylinder',diameter=12,height=20),transform=dict(x=42,z=430))]).model_dump()
        blocked=opened(ChamberDialog(window,obstructed,requirements=_requirements()))
        _wait(app,lambda:blocked.checked is not None and not blocked.running,'blocked chamber preview')
        check(bool(blocked.interference['blocked']) and not blocked.apply_button.isEnabled(),'complete assembly case-wall interference blocks application')
        blocked.inspect_open.setChecked(True);check(not blocked.apply_button.isEnabled(),'hiding a door never bypasses real collision blocking')
        _dispose(app,blocked)

        hidden=ChamberDialog(window,obstructed,requirements=_requirements());dialogs.append(hidden)
        _wait(app,lambda:hidden.checked is not None and not hidden.running,'hidden asynchronous collision preview')
        check(not hidden.viewport.initialized and hidden.interference['blocked'] and not hidden.apply_button.isEnabled(),
              'hidden asynchronous completion does not initialize or render an unavailable native context')
        _dispose(app,hidden)

        document=Document();document.commit(raw,'Synthetic before chamber');initial=document.journal.data['cursor']
        context=dict(tool='chamber',chamber_requirements=chamber_report['requirements'],chamber_part_ids=chamber_report['parts'],chamber_drive_part_ids=[])
        document.commit(candidate,'Synthetic chamber creation',context);latest=document.journal.data['cursor']
        saved=path.with_name('engineering-chamber-history.cad.json');document.write(saved)
        restored=Document();restored.load(read_project(saved),saved);window.document=restored;window.selected_parts=['chamber-case']
        check(restored.design==candidate.model_dump() and len(restored.journal.data['entries'])==2,'embedded BREP and all chamber history settings survive file reopening')
        check(window.chamber_context()==context,'current history branch exposes saved parametric chamber settings')
        restored.commit(restored.journal.at(initial),'Cursor before chamber',cursor=initial)
        check(window.chamber_context() is None,'future chamber settings cannot leak through an earlier history cursor')
        restored.commit(restored.journal.at(latest),'Restore chamber cursor',cursor=latest)
        reopened=opened(ChamberDialog(window,restored.design,requirements=context['chamber_requirements'],replace_ids=context['chamber_part_ids']))
        _wait(app,lambda:reopened.checked is not None and not reopened.running,'reopened parametric chamber')
        check(reopened.apply_button.isEnabled() and reopened.inputs['wall'].value()==7 and len(reopened.checked.parts)==len(candidate.parts),
              'native reopened chamber restores dimensions without duplicating parts')
        _dispose(app,reopened)

        mounted_raw=deepcopy(restored.design)
        mounted_case=next(part for part in mounted_raw['parts'] if part['id']=='chamber-case')
        mounted_case['fixed']=False
        mounted_raw['mates'].append(dict(id='synthetic-case-mount',parent='frame',child='chamber-case',
            x=-150,y=mounted_case['transform']['y'],z=mounted_case['transform']['z']))
        mounted=Design.model_validate(mounted_raw);mounted_before=mounted.model_dump()
        edit=opened(ChamberDialog(window,mounted_before,requirements=context['chamber_requirements'],replace_ids=context['chamber_part_ids']))
        _wait(app,lambda:edit.checked is not None and not edit.running,'externally mounted chamber preview')
        edit.inputs['wall'].setValue(6)
        _wait(app,lambda:edit.checked is not None and edit.apply_button.isEnabled() and edit.report['requirements']['wall_thickness_mm']==6,'mounted same-center chamber resize')
        check(edit.checked.mates==mounted.mates,'native same-center resizing preserves an external chamber mount')
        edit.inputs['min-2'].setValue(edit.inputs['min-2'].value()+2)
        edit.inputs['max-2'].setValue(edit.inputs['max-2'].value()+2)
        _wait(app,lambda:not edit.running and edit.checked is None and '외부 조립 구속' in edit.status.text(),'mounted world-bounds mismatch rejection')
        check(not edit.apply_button.isEnabled() and mounted.model_dump()==mounted_before,
              'native requested bounds cannot disagree with a preserved external mount')
        _dispose(app,edit)

        path.write_text(json.dumps(dict(success=True,checks=checks,duration_s=time.monotonic()-started,
            synthetic_only=True,hardware_verified=False),ensure_ascii=False,indent=2),encoding='utf-8')
        window.document.dirty=False;window.close();app.quit()
    except Exception:
        for dialog in dialogs:
            if getattr(dialog,'alive',True):
                try:dialog.reject()
                except RuntimeError:pass
        path.write_text(json.dumps(dict(success=False,checks=checks,error=traceback.format_exc(),synthetic_only=True),ensure_ascii=False,indent=2),encoding='utf-8')
        window.document.dirty=False;window.close();app.exit(1)
