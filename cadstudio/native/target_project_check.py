"""One explicit actual-input frozen boundary; no model build or ordinary UI."""
def run(output,input_path):
    import os
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from pathlib import Path
    from hashlib import sha256
    from datetime import datetime,timezone
    import json,sys,time,traceback
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont,QFontDatabase,QImageWriter,QImage
    from PySide6.QtCore import QBuffer,QIODevice
    from .. import __version__,__build_id__
    from ..firmware_bundle import verify_bundle_binding,export_bundle_atomic,source_search_paths,MANIFEST_NAME,DEPENDENCIES_NAME,_reject_reparse
    from .document import Document,read_project
    from .firmware_dialog import FirmwareDialog
    output=Path(output).absolute();input_path=Path(input_path).absolute()
    root=output.parent;root.mkdir(parents=True,exist_ok=True)
    report=dict(success=False,version=__version__,build_id=__build_id__,frozen=bool(getattr(sys,'frozen',False)),
        runtime_executable=sys.executable,pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),
        ordinary_Windows_UI_verified=False,offscreen_Qt_widget_check=True,checks=[],screenshots=[],
        full_geometry_runs=0,HLR_runs=0,live_AI_calls=0,SDK_build_calls=0,SDK_payload_reads=0,
        generated_code_executed=False,hardware_calls=0,allow_motion=False,qualification=0)
    started=time.monotonic();dialog=None;app=None
    def write():
        report['check_count']=len(report['checks'])
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def check(value,title):
        if not value:raise AssertionError(title)
        report['checks'].append(title);write()
    def fingerprint(value):return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    def wait(predicate,seconds=20):
        deadline=time.monotonic()+seconds
        while not predicate():
            if time.monotonic()>=deadline:raise TimeoutError('Owned actual-input editor boundary did not complete')
            app.processEvents();time.sleep(.01)
    try:
        _reject_reparse(input_path);_reject_reparse(root)
        check(input_path.parent==root/'inputs','Input is the owned copy inside this output folder')
        raw=input_path.read_bytes()
        check(len(raw)==16738249 and sha256(raw).hexdigest()=='da079edab8874b25ef06477f9805e06a8c9ef775bd22a417875c36fa67500ffd','Exact da079 input bytes before read')
        report['input']=dict(path=str(input_path),bytes=len(raw),sha256=sha256(raw).hexdigest())
        raw_project=json.loads(raw)
        project=read_project(input_path)
        definition=project.design.model_dump(mode='json');history=project.history.model_dump(mode='json') if project.history else None
        check(len(project.design.parts)==239,'Actual 239 registered bodies parsed; no geometry generation')
        report['parts']=len(project.design.parts);report['assets']=len(project.design.assets)
        report['history_entries']=len(history['entries']) if history else 0
        check(history is not None,'Actual existing history retained')
        targets=[b for b in project.design.electrical.firmware_bundles if b.external_target and len(b.files)==32]
        check(len(targets)==1,'Exact one actual 32-file target bundle')
        bundle=targets[0]
        raw_bundle=next(b for b in raw_project['design']['electrical']['firmware_bundles'] if b['id']==bundle.id)
        check(bundle.model_dump(mode='json')==raw_bundle,'All stored target fields preserved by frozen parser')
        check(bundle.include_paths==['include','target','target/include'],'All three actual project header paths')
        check(bundle.entrypoint=='target/src/main.c','Actual target entrypoint retained')
        check(len(bundle.external_target.files)==151 and bundle.external_target.manifest_sha256=='7efe82f2baf608821ef9627f8f2800e434e49a95875abe1a599d89cc41ba369d','Actual 151 SDK metadata rows retained')
        check(verify_bundle_binding(bundle,project.design.electrical).status=='current','Actual stored circuit/board/pin binding current')
        report['bundle']=dict(id=bundle.id,entrypoint=bundle.entrypoint,include_paths=bundle.include_paths,
            files=[dict(path=f.path,role=f.role,sha256=f.sha256,bytes=len(f.content.encode('utf-8'))) for f in bundle.files],
            SDK_manifest_sha256=bundle.external_target.manifest_sha256,SDK_files=len(bundle.external_target.files),
            SDK_bytes=sum(f.bytes for f in bundle.external_target.files),binding_status='current')
        app=QApplication.instance() or QApplication(['actual-target-project-check'])
        app.setQuitOnLastWindowClosed(False);app.setStyle('Fusion')
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/malgun.ttf'
        report['font']=dict(path=str(font),sha256=sha256(font.read_bytes()).hexdigest(),process_local_id=QFontDatabase.addApplicationFont(str(font)))
        app.setFont(QFont('Malgun Gothic',9))
        from .widgets import apply_theme
        apply_theme(app)
        dialog=FirmwareDialog(project.design.electrical,language='ko',selected_component_id=bundle.binding.board_component_id,
            codex_config=dict(model='',effort='medium'))
        if dialog.bundle is None or dialog.bundle.id!=bundle.id:
            index=dialog.saved_bundles.findData(bundle.id);check(index>=0,'Actual stored bundle selectable')
            dialog.saved_bundles.setCurrentIndex(index)
        check(dialog.bundle is not None and dialog.bundle.id==bundle.id,'Actual target selected in editor')
        check(len(dialog._editors)==32,'Actual 32 source/linker/assembly editor tabs loaded')
        check([(p,dialog._editor_source(e),r) for p,e,r in dialog._editors]==[(f.path,f.content,f.role) for f in bundle.files],'Actual editor extraction preserves all file texts and roles')
        check(dialog._project_include_paths()==bundle.include_paths,'Header directory widget preserves actual paths')
        check(dialog._external_target==bundle.external_target and dialog.sdk_files.rowCount()==151,'SDK review widget loaded actual inventory')
        for i,item in enumerate(bundle.external_target.files):
            check([dialog.sdk_files.item(i,c).text() for c in range(3)]==[item.path,str(item.bytes),item.sha256],'SDK row '+str(i+1)+' metadata values exact')
        check(dialog._current_bundle().model_dump(mode='json')==raw_bundle,'Editor save/export candidate exactly matches stored 32-file target')
        dialog.resize(1280,900);dialog.show();dialog.tabs.setCurrentIndex(3);app.processEvents()
        buffer=QBuffer();buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        writer=QImageWriter(buffer,b'png');check(writer.write(dialog.grab().toImage()),'Actual target header/SDK offscreen PNG encoded')
        image_bytes=bytes(buffer.data());buffer.close();check(not QImage.fromData(image_bytes).isNull(),'Actual target PNG decoded')
        screenshot=root/'actual-target-header-SDK.png'
        with screenshot.open('xb') as stream:stream.write(image_bytes)
        report['screenshots'].append(str(screenshot));write()
        # The explicit editor Save runs only the existing static/pin source audit.
        # It calls no external compiler, SDK installer, generated code or hardware.
        dialog.accept();wait(lambda:dialog.task is None)
        check(dialog.accepted_workspace is not None,'Explicit actual editor Save completed: '+dialog.status.text())
        check(dialog.accepted_workspace.model_dump(mode='json')==definition['electrical'],'Editor Save preserves entire actual circuit and firmware metadata')
        doc=Document();doc.load(project,input_path)
        doc.design['electrical']=dialog.accepted_workspace.model_dump(mode='json')
        saved=root/'actual32-roundtrip.pcad';check(not saved.exists(),'Separate SaveAs output does not overwrite an existing file')
        doc.write(saved);reopened=read_project(saved)
        check(reopened.design.model_dump(mode='json')==definition,'Frozen separate Save/Reopen exact full design definition and assets')
        check(reopened.history.model_dump(mode='json')==history,'Frozen separate Save/Reopen exact entire history')
        check(reopened.prompt==project.prompt,'Frozen separate Save/Reopen exact stored prompt')
        reopened_bundle=next(b for b in reopened.design.electrical.firmware_bundles if b.id==bundle.id)
        check(reopened_bundle.model_dump(mode='json')==raw_bundle,'Frozen separate Save/Reopen exact 32-file target metadata')
        destination=root/'actual32-firmware-export'
        export_bundle_atomic(reopened_bundle,destination)
        export_records=[]
        for item in bundle.files:
            data=(destination/item.path).read_bytes()
            check(data==item.content.encode('utf-8') and sha256(data).hexdigest()==item.sha256,'Export exact '+item.path)
            export_records.append(dict(path=item.path,sha256=sha256(data).hexdigest(),bytes=len(data),role=item.role))
        check(json.loads((destination/MANIFEST_NAME).read_bytes())==raw_bundle,'Exported bundle manifest preserves all original fields')
        dependency=json.loads((destination/DEPENDENCIES_NAME).read_bytes())
        check(dependency['search_paths']==source_search_paths(bundle) and dependency['external_target']==bundle.external_target.model_dump(mode='json'),'Exported dependency metadata preserves paths and SDK inventory')
        exported={p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()}
        check(exported=={f.path for f in bundle.files}|{MANIFEST_NAME,DEPENDENCIES_NAME},'Exactly 32 code files and two metadata sidecars; no SDK payload')
        check(input_path.read_bytes()==raw,'Owned da079 input unchanged after every operation')
        report.update(saved_project=dict(path=str(saved),bytes=saved.stat().st_size,sha256=sha256(saved.read_bytes()).hexdigest()),
            export=dict(path=str(destination),files=export_records,total_files=len(exported)),
            full_design_semantic_sha256=fingerprint(definition),history_semantic_sha256=fingerprint(history),success=True)
    except Exception:
        report['error']=traceback.format_exc()[:8192]
    finally:
        if dialog is not None:dialog.reject()
        if app is not None:app.processEvents()
        report['elapsed_s']=time.monotonic()-started;report['finished_utc']=datetime.now(timezone.utc).isoformat();write()
    return 0 if report['success'] else 1
