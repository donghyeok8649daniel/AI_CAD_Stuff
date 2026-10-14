"""Small explicit/offscreen integration check; no ordinary GUI or hardware claim."""
def run(output):
    import os
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from pathlib import Path
    from datetime import datetime,timezone
    from hashlib import sha256
    from types import SimpleNamespace
    import json,sys,time,traceback
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont,QFontDatabase,QImageWriter,QImage
    from PySide6.QtCore import Qt,QBuffer,QIODevice
    from PySide6.QtTest import QTest
    from .. import __version__,__build_id__
    from ..electrical import ElectricalWorkspace
    from ..firmware_bundle import FirmwareExternalTarget,create_bundle,verify_bundle_binding
    from ..firmware_generation import build_context
    from ..models import Design
    from .firmware_dialog import FirmwareDialog
    from .document import Document,read_project
    output=Path(output).absolute();output.parent.mkdir(parents=True,exist_ok=True)
    report=dict(success=False,version=__version__,build_id=__build_id__,frozen=bool(getattr(sys,'frozen',False)),
        runtime_executable=sys.executable,pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),
        ordinary_Windows_UI_verified=False,offscreen_Qt_widget_check=True,checks=[],screenshots=[],
        full_239_250_geometry_runs=0,live_AI_calls=0,generated_code_executed=False,SDK_calls=0,hardware_calls=0)
    app=QApplication.instance() or QApplication(['target-integration-check']);app.setFont(QFont('Malgun Gothic',9))
    app.setQuitOnLastWindowClosed(False)
    # Offscreen Windows does not enumerate the normal system font database on
    # this host. Load a system font into this process only; no font installation.
    font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/malgun.ttf'
    report['font']=dict(path=str(font_path),sha256=sha256(font_path.read_bytes()).hexdigest(),
        process_local_id=QFontDatabase.addApplicationFont(str(font_path)))
    app.setFont(QFont('Malgun Gothic',9))
    app.setStyle('Fusion')
    from .widgets import apply_theme
    apply_theme(app)
    dialogs=[];started=time.monotonic()
    def check(condition,message):
        if not condition:raise AssertionError(message)
        report['checks'].append(message)
    def wait(predicate,seconds=8):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>=deadline:raise TimeoutError('Owned widget callback did not complete')
            app.processEvents();time.sleep(.01)
        app.processEvents()
    try:
        path=Path(os.environ['CADSTUDIO_TARGET_CHECK_INVENTORY'])
        raw=path.read_bytes();check(len(raw)<=256*1024,'Bounded external metadata input')
        sdk=FirmwareExternalTarget.model_validate_json(raw)
        report['input_inventory']=dict(path=str(path),sha256=sha256(raw).hexdigest(),bytes=len(raw))
        work=ElectricalWorkspace.model_validate(dict(nodes=['GND','PWR'],components=[dict(id='board',name='G474 fixture',
            kind='mcu',a='PWR',b='GND',analysis_enabled=False,catalog_id='st_nucleo_g474re',
            pinout_catalog_id='st_nucleo_g474re',part_id='board_body',part_registration=True)]))
        files=[dict(path='main.c',content='#include "fatigue_board.h"\nint main(void) { return 0; }\n'),
            dict(path='target/include/fatigue_board.h',content='#pragma once\n'),
            dict(path='target/memory.ld',content='MEMORY {}\n',role='linker'),
            dict(path='target/startup.s',content='.section .text\n',role='assembly')]
        bundle=create_bundle('Small G474 fixture','stm32_hal',work,'board',files,'main.c',
            include_paths=['target/include'],external_target=sdk,notes='Source data only')
        raw=work.model_dump(mode='json');raw['firmware_bundles']=[bundle.model_dump(mode='json')]
        work=ElectricalWorkspace.model_validate(raw);before=work.model_dump(mode='json')
        for language in ('ko','en'):
            d=FirmwareDialog(work,language=language,selected_component_id='board',codex_config=dict(
                model='fixture-local-model',effort='medium',catalog=[dict(model='fixture-local-model',efforts=['medium'])]))
            dialogs.append(d);d.show();app.processEvents()
            check(d.bundle.id==bundle.id and d.sdk_files.rowCount()==len(sdk.files),'Loaded inventory rows '+language)
            check(d.include_paths.toPlainText()=='target/include','Loaded project header directory '+language)
            d.tabs.setCurrentIndex(next(i for i in range(d.tabs.count()) if d.tabs.tabText(i) in ('헤더 / 대상 SDK','Headers / target SDK')))
            app.processEvents()
            screenshot=output.parent/(output.stem+'-'+language+'.png');pixmap=d.grab()
            report.setdefault('render_diagnostics',[]).append(dict(language=language,visible=d.isVisible(),
                widget_size=[d.width(),d.height()],pixmap_size=[pixmap.width(),pixmap.height()],null=pixmap.isNull()))
            buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            writer=QImageWriter(buffer,b'png');encoded=writer.write(pixmap.toImage())
            report['render_diagnostics'][-1]['PNG_encoder_success']=encoded
            report['render_diagnostics'][-1]['PNG_encoder_error']=writer.errorString()
            check(encoded,'Offscreen PNG encode '+language)
            data=bytes(buffer.data());buffer.close()
            with screenshot.open('xb') as stream:stream.write(data)
            check(not QImage.fromData(data).isNull() and screenshot.read_bytes()==data,'Offscreen Qt tab render '+language)
            report['screenshots'].append(str(screenshot))
            d.include_paths.setPlainText('../outside')
            try:d._current_bundle();raise AssertionError('Unsafe include was accepted')
            except ValueError:pass
            check(d.workspace.model_dump(mode='json')==before,'Invalid include leaves caller intact '+language)
            # Invalid drafts are cached for review, not silently dropped during
            # selection changes and not allowed to become a saved project.
            d._cache_active();check(d._draft_cache[('board',bundle.id)]['include_paths']==['../outside'],'Invalid draft cache '+language)
            d.include_paths.setPlainText('target\ntarget/include')
            QTest.mouseClick(d.sdk_remove,Qt.MouseButton.LeftButton)
            check(d._external_target is None and d.sdk_files.rowCount()==0,'Explicit inventory detach '+language)
            d.import_target_inventory(path)
            check(d._external_target==sdk and d.sdk_files.rowCount()==len(sdk.files),'Bounded inventory import '+language)
            bad_path=output.parent/(output.stem+'-tampered-'+language+'.json')
            bad=sdk.model_dump();bad['manifest_sha256']='0'*64
            bad_path.write_text(json.dumps(bad),encoding='utf-8');d.import_target_inventory(bad_path)
            check(d._external_target==sdk and d.workspace.model_dump(mode='json')==before,'Rejected SDK hash leaves draft intact '+language)
            d._cache_active();restored=d._cached_bundle(d._draft_cache[('board',bundle.id)])
            check(restored.include_paths==['target','target/include'] and restored.external_target==sdk,'Cache forwarding '+language)
            # Offline authored transport exercises the worker boundary without
            # any subscription call or generated source execution.
            def transport(workspace,board,operation,model,**options):
                existing=options['existing_bundle']
                context=build_context(workspace,board,target='stm32_hal',existing_bundle=existing)
                assert context['project_include_paths']==['target','target/include']
                assert context['external_target_inventory']['manifest_sha256']==sdk.manifest_sha256
                return SimpleNamespace(bundle=existing,message='Offline fixture revision',pending_checks=['Target build pending'])
            d.generation_transport=transport;d.operation.setPlainText('Review preserved target data')
            QTest.mouseClick(d.generate_button,Qt.MouseButton.LeftButton);wait(lambda:d.task is None)
            check(d._current_bundle().external_target==sdk,'Generation worker preserves target data '+language)
            d.check_build();wait(lambda:d.task is None)
            check(d.build_report is not None and d.build_report.status=='pending' and not d.build_report.full_target_build,'Source check remains pending '+language)
            destination=output.parent/(output.stem+'-export-'+language)
            d.export_bundle(destination);wait(lambda:d.task is None)
            check((destination/'target/memory.ld').read_bytes()==b'MEMORY {}\n','Editor exports linker bytes '+language)
            check((destination/'target/startup.s').read_bytes()==b'.section .text\n','Editor exports assembly bytes '+language)
            check(json.loads((destination/'firmware-dependencies.json').read_bytes())['external_target']['manifest_sha256']==sdk.manifest_sha256,'Exported SDK binding '+language)
            d.accept();wait(lambda:d.task is None)
            check(d.accepted_workspace is not None,'Explicit dialog save '+language)
            saved=d.accepted_workspace.firmware_bundles[0]
            check(saved.include_paths==['target','target/include'] and saved.external_target==sdk,'Saved include/SDK data '+language)
            check(d.workspace.model_dump(mode='json')==before,'Original circuit untouched '+language)
        # Cancel the changed generation boundary with an active owned worker.
        d=FirmwareDialog(work,selected_component_id='board',codex_config=dict(model='fixture-local-model',effort='medium'))
        dialogs.append(d)
        def slow(workspace,board,operation,model,**options):
            options['control'].cancelled.wait(3);options['control'].check()
        d.generation_transport=slow;d.operation.setPlainText('Cancelable fixture')
        d.generate();check(d.task is not None,'Cancelable generation started')
        task=d.task;d.cancel_task();wait(lambda:not task.thread.is_alive())
        check(d.bundle.external_target==sdk and d.workspace.model_dump(mode='json')==before,'Cancellation preserves target and caller')
        # Only a new, small typed project; no parent geometry/history loaded.
        accepted=dialogs[0].accepted_workspace
        design=Design.model_validate(dict(name='Local integration fixture',parts=[dict(id='board_body',name='Board envelope',role='electrical',
            geometry=dict(kind='plate',length=85,width=56,thickness=2,hole_count=0))],electrical=work.model_dump(mode='json')))
        doc=Document();doc.commit(design,'Before');raw=design.model_dump(mode='json');raw['electrical']=accepted.model_dump(mode='json')
        doc.commit(Design.model_validate(raw),'Target edit');pcad=output.parent/(output.stem+'-fixture.pcad');doc.write(pcad)
        loaded=read_project(pcad);doc.load(loaded,pcad);entries=doc.journal.path()
        check(loaded.design.electrical.firmware_bundles[0].external_target==sdk,'Typed Save/Open inventory')
        doc.commit(doc.journal.at(entries[0]['id']),'Undo',cursor=entries[0]['id'])
        check(doc.project().design.electrical.firmware_bundles[0].include_paths==['target/include'],'Exact history Undo')
        doc.commit(doc.journal.at(entries[-1]['id']),'Redo',cursor=entries[-1]['id'])
        check(doc.project().design.electrical.firmware_bundles[0].include_paths==['target','target/include'],'Exact history Redo')
        report['project']=str(pcad)
        # One small new curve fixture checks integrated drawing endpoints and
        # labels; no real FT03/FT04/whole assembly is imported or regenerated.
        import cadquery as cq
        from ..models import Part
        from ..imported import encode_shape
        from ..drawings import sheet,DrawingSettings
        shape=cq.Solid.makeCylinder(13.7,11.4);asset=encode_shape(shape,'owned-small-circle')
        design=Design(parts=[Part(id='curve',name='Small circle',geometry=dict(kind='imported',asset_id='curve'))],assets={'curve':asset})
        page=sheet(design,DrawingSettings(part_id='curve'))
        for view in page['provenance']['views'][:3]:
            for dimension in view['dimensions']:
                expected=11.4 if dimension['axis']=='Z' else 27.4
                check(abs(dimension['value_mm']-expected)<1e-6,'Integrated exact cardinal '+view['name']+' '+dimension['axis'])
                check(page['paths'][dimension['path_index']]['points']==dimension['paper_endpoints_mm'],'Integrated dimension endpoint binding')
        check(not page['provenance']['manufacturing_dimension_accuracy_verified'],'No manufacturing accuracy promotion')
        report['success']=True
    except Exception:
        report['error']=traceback.format_exc()[:8192]
    finally:
        for dialog in dialogs:
            dialog.reject()
        app.processEvents()
        report['elapsed_s']=time.monotonic()-started;report['finished_utc']=datetime.now(timezone.utc).isoformat()
        report['check_count']=len(report['checks'])
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['success'] else 1
