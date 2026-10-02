"""Owned offline Windows UI/geometry checks for power paths, specs and reuse."""
from copy import deepcopy
import json,time,traceback,math
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest


def run(app,w,path):
    from ..models import Design,Part
    from ..electrical import ElectricalWorkspace,evaluate_electrical
    from ..mechanical_catalog import get_clearance_hole,get_catalog_entry,format_ai_spec
    from ..kernel import preview
    from .power_path_dialog import PowerPathDialog
    from .mechanical_catalog_dialog import MechanicalCatalogDialog
    from .electrical_schematic import ElectricalSchematicDialog
    from .inspect_tools import HoleDialog
    from .fastener_check_dialog import FastenerCheckDialog
    from .document import read_project
    path.parent.mkdir(parents=True,exist_ok=True)
    report={'checks':[],'live_ai_calls':0};dialogs=[];errors=[]
    def check(value,title):
        if not value:raise AssertionError(title)
        report['checks'].append(title)
    def wait(predicate):
        end=time.monotonic()+60
        while not predicate():
            app.processEvents();QTest.qWait(10)
            if errors:raise AssertionError(errors[-1])
            if time.monotonic()>end:raise TimeoutError('UI verification')
        app.processEvents()
    def apply(data,title):
        w.apply_design(data,title);wait(lambda:not w.busy)
    try:
        app.setQuitOnLastWindowClosed(False);w.show_error=errors.append
        check(w.document.design is None,'native application begins empty')
        check(all(key in w.actions for key in ('power_path','mechanical_catalog','fastener_check','electrical')),
              'searchable native menus expose power-path and standards tools')
        raw=Design(parts=[Part(id='plate',name='Support',role='structure',geometry=dict(kind='plate',
                         length=40,width=40,thickness=8,hole_count=0)),
                         Part(id='board',name='Board',role='electrical',geometry=dict(kind='cylinder'),
                              transform=dict(x=65))]).model_dump()
        apply(raw,'Base');actor=w.viewport.actors['plate'][0];before=deepcopy(w.document.design)
        raw=deepcopy(before);raw['parts'][0].update(name='Renamed support',color='#abcdef')
        apply(raw,'Rename and color')
        check(w.viewport.actors['plate'][0] is actor,'metadata update retains VTK geometry actors')
        check(w.result['meshes'][0]['name']=='Renamed support' and w.result['meshes'][0]['color']=='#abcdef',
              'cached geometry carries the new name and color')
        w.undo();wait(lambda:not w.busy)
        check(w.viewport.actors['plate'][0] is actor and w.document.design==before,
              'undo preserves actor and restores complete metadata')
        w.redo();wait(lambda:not w.busy)
        check(w.viewport.actors['plate'][0] is actor and w.document.design['parts'][0]['name']=='Renamed support',
              'redo preserves actor and metadata history')

        dialog=PowerPathDialog(w,ElectricalWorkspace(),w.document.design['parts']);dialogs.append(dialog)
        dialog.show();app.processEvents()
        check(not dialog.apply_button.isEnabled(),'missing operating voltage current and wire dimensions block apply')
        dialog.name.setText('Controller supply');dialog.source_voltage.setValue(5)
        dialog.source_internal_r.setValue(.2);dialog.feed_length.setValue(300);dialog.feed_area.setValue(.5)
        dialog.return_length.setValue(400);dialog.return_area.setValue(.5)
        dialog.load_kind.setCurrentIndex(dialog.load_kind.findData('mcu'))
        dialog.load_voltage.setValue(5);dialog.load_current.setValue(.2)
        dialog.load_part.setCurrentIndex(dialog.load_part.findData('board'))
        app.processEvents();check(dialog.build is not None and dialog.apply_button.isEnabled(),
                                 'explicit operating inputs produce a valid preview')
        built=dialog.build
        check(len(built.workspace.components)==5 and len(set(built.ids.values()))==5,
              'source switch feed load and return have distinct persistent IDs')
        check(built.report.load_voltage_v<5 and 0<built.report.current_a<.2,
              'battery and two wire drops lower actual DC load voltage and current')
        check(abs(built.report.balance_error_w)<1e-9 and built.report.battery_internal_loss_w>0,
              'DC energy balance includes battery internal loss')
        check(all(c.status=='unverified' for c in built.report.capacities),
              'missing current limits stay unverified')
        dialog.feed_catalog.setCurrentIndex(dialog.feed_catalog.findData('belden_9918'))
        app.processEvents();built=dialog.build
        feed=next(c for c in built.workspace.components if c.id==built.ids['feed'])
        check(feed.catalog_id=='belden_9918' and feed.source_url.startswith('https://www.belden.com/'),
              'manufacturer wire selection preserves exact SKU and official source')
        check(feed.max_current_a is None,'free-air wire rating is never silently used as harness capacity')
        check(abs(feed.resistivity_ohm_mm2_per_m/feed.cross_section_mm2-
                  get_catalog_entry('belden_9918').wire_spec.dcr_ohm_per_m)<1e-6,
              'selected wire DC resistance uses its documented per-metre value')
        dialog.source_enabled.setChecked(False);app.processEvents()
        check(dialog.build.report.state=='source_off' and abs(dialog.build.report.current_a)<1e-12,
              'source OFF previews zero delivered current')
        dialog.source_enabled.setChecked(True);dialog.switch_closed.setChecked(False);app.processEvents()
        check(dialog.build.report.state=='switch_open' and abs(dialog.build.report.current_a)<1e-12,
              'open series switch interrupts the path')
        dialog.switch_closed.setChecked(True);dialog.feed_capacity.setValue(.01);app.processEvents()
        check(any(c.status=='over_entered_limit' for c in dialog.build.report.capacities),
              'entered current capacity overload is visible before applying')
        dialog.feed_capacity.setValue(0);app.processEvents();built=dialog.build
        dialog.grab().save(str(path.with_name('power-path2160.png')))
        schematic=ElectricalSchematicDialog(w,built.workspace,built.result);dialogs.append(schematic)
        schematic.show();app.processEvents()
        check(set(built.ids.values())<=set(schematic.branch_layout),
              'separate schematic draws the whole power loop')
        check(len(schematic.node_positions)==len(built.workspace.nodes),
              'schematic bus nodes match the saved electrical network')
        schematic.grab().save(str(path.with_name('power-schematic2160.png')))
        data=deepcopy(w.document.design);data['electrical']=built.workspace.model_dump()
        apply(data,'Power path')
        check(w.viewport.actors['plate'][0] is actor,'adding a circuit retains existing CAD actors')
        check(w.document.design['electrical']['components'][-2]['part_id']=='board',
              'power path stores the chosen CAD load link')
        w.document.write(path.with_suffix('.cad.json'));loaded=read_project(path.with_suffix('.cad.json'))
        check(loaded.design.electrical is not None and len(loaded.design.electrical.components)==5,
              'power path and provenance reopen from a CAD project')
        w.undo();wait(lambda:not w.busy)
        check(not w.document.design.get('electrical'),'undo removes only the new power path')
        w.redo();wait(lambda:not w.busy)
        check(len(w.document.design['electrical']['components'])==5,'redo restores the complete path')

        catalog=MechanicalCatalogDialog(w,query='1759017');dialogs.append(catalog)
        catalog.show();app.processEvents()
        check(catalog.table.rowCount()==1 and catalog.selected().catalog_id=='phoenix_mstb_2',
              'exact connector SKU finds a unique source-backed record')
        check('1.4' in catalog.details.toPlainText() and catalog.sources.count()>=1,
              'connector PCB hole dimension and official source are visible')
        check('2026-10-03' in format_ai_spec(catalog.selected()),'AI spec includes retrieval date')
        catalog.grab().save(str(path.with_name('mechanical-catalog2160.png')))
        catalog.query.setText('not-a-real-sku');app.processEvents()
        check(not catalog.use_button.isEnabled(),'unknown product never generates fabricated specs')
        face=next(f for f in w.result['meshes'][0]['faces'] if f.get('normal')==[0,0,1])
        hole=HoleDialog(w,w.document.design,'plate',face);dialogs.append(hole)
        hole.show();hole.set_standard(get_clearance_hole('M4'))
        wait(lambda:hole.checked is not None and not hole.running and not hole.timer.isActive())
        measured=preview(hole.checked)
        check(abs(measured['meshes'][0]['volume']-(40*40*8-math.pi*2.25**2*8))<1e-6,
              'ISO clearance size produces the expected real through-hole volume')
        check(hole.standard_record()['nominal_diameter_mm']==4.5 and
              hole.standard_record()['standard']=='ISO 273:1979',
              'hole provenance preserves the source and nominal standard size')
        apply(hole.checked.model_dump(),'Standard hole')
        check(w.viewport.actors['plate'][0] is not actor,'real hole edits rebuild and verify geometry')
        check(not w.result['stats']['collisions'],'final sample parts have no volume interference')
        unchanged=deepcopy(w.document.design)
        bolts=FastenerCheckDialog(w);dialogs.append(bolts);bolts.show();app.processEvents()
        check(not bolts.force.text() and not bolts.bolt_count.text() and not bolts.safety_factor.text(),
              'bolt review starts without invented load or safety factor')
        bolts.calculate()
        check(bolts.check_result is None and not bolts.copy_button.isEnabled(),
              'missing physical loads cannot produce a bolt strength result')
        bolts.thread.setCurrentIndex(bolts.thread.findData('M6'))
        bolts.force.setText('6000');bolts.bolt_count.setText('4');bolts.safety_factor.setText('2')
        bolts.calculate()
        check(bolts.check_result is None,'equal-load and applicable-head assumptions must be explicit')
        bolts.equal_sharing.setChecked(True);bolts.head_geometry.setChecked(True);bolts.calculate()
        check(bolts.check_result is not None and bolts.check_result.within_proof_reference,
              'entered equal-share static axial load compares with source-backed bolt proof load')
        check('Bossard' in bolts.output.toPlainText() and '11600' in bolts.output.toPlainText(),
              'bolt result displays its source and M6 class 8.8 proof-load reference')
        bolts.grab().save(str(path.with_name('fastener-check2160.png')))
        bolts.force.setText('100000');bolts.calculate()
        check(bolts.check_result is not None and not bolts.check_result.within_proof_reference,
              'excessive entered axial bolt load is reported before construction')
        bolts.thread.setCurrentIndex(bolts.thread.findData('M8'));bolts.calculate()
        check(bolts.check_result is None,'M8 hot-dip-galvanized reduced-load exception requires confirmation')
        check(w.document.design==unchanged,'bolt review never mutates CAD or certifies the full assembly')

        from ..power_paths import PowerInputRequired
        from .ai_task import AITask
        provider=w.provider.currentIndex()
        blocked=w.provider.blockSignals(True)
        w.provider.setCurrentIndex(w.provider.findData('codex'))
        task=AITask(lambda *_:None);w.ai_task=task
        w.ai_failed((task,PowerInputRequired(('load_current_a',))))
        app.processEvents()
        check(w.ai_task is None and '전원 수치 입력 필요' in w.ai_result.toPlainText(),
              'native AI panel stops once and asks for missing power operating inputs')
        check('✓' in w.codex_status.text() and w.document.design==unchanged,
              'input request retains Codex connection status and current CAD design')
        w.provider.setCurrentIndex(provider)
        w.provider.blockSignals(blocked)
        check(not errors,'no application or worker errors')
        report['success']=True
    except Exception:
        report.update(success=False,error=traceback.format_exc())
    finally:
        for dialog in reversed(dialogs):dialog.reject()
        QThreadPool.globalInstance().waitForDone(10000)
        w.document.dirty=False;w.close()
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        app.exit(0 if report.get('success') else 1)
