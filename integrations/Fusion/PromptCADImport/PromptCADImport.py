"""Run inside Autodesk Fusion: import a STEP into a NEW document and export F3D."""
import os
import json
import traceback
import adsk.core
import adsk.fusion


def run(context):
    ui=None
    try:
        app=adsk.core.Application.get();ui=app.userInterface
        job_path=os.path.join(os.path.dirname(__file__),'job.json')
        if os.path.isfile(job_path):
            with open(job_path,encoding='utf-8') as stream:job=json.load(stream)
            source_path=os.path.abspath(job['source']);filename=os.path.abspath(job['target'])
            if not source_path.lower().endswith('.step') or not os.path.isfile(source_path):raise RuntimeError('변환할 STEP 파일이 없습니다.')
            if not filename.lower().endswith('.f3d') or os.path.exists(filename):raise RuntimeError('새 F3D 저장 경로를 지정하세요. 기존 파일은 덮어쓰지 않습니다.')
        else:
            source=ui.createFileDialog();source.title='Prompt CAD — 변환할 STEP 선택';source.filter='STEP files (*.step;*.stp)'
            if source.showOpen()!=adsk.core.DialogResults.DialogOK:return
            source_path=source.filename
            target=ui.createFileDialog();target.title='Fusion 아카이브 저장';target.filter='Fusion archive (*.f3d)'
            target.initialDirectory=os.path.dirname(source.filename)
            target.initialFilename=os.path.splitext(os.path.basename(source.filename))[0]+'.f3d'
            if target.showSave()!=adsk.core.DialogResults.DialogOK:return
            filename=target.filename
        if not filename.lower().endswith('.f3d'):filename+='.f3d'
        manager=app.importManager
        document=manager.importToNewDocument(manager.createSTEPImportOptions(source_path))
        if not document:raise RuntimeError('STEP 가져오기에 실패했습니다.')
        design=adsk.fusion.Design.cast(document.products.itemByProductType('DesignProductType'))
        if not design:raise RuntimeError('Fusion 설계 제품을 찾지 못했습니다.')
        options=design.exportManager.createFusionArchiveExportOptions(filename)
        if not design.exportManager.execute(options) or not os.path.isfile(filename):
            raise RuntimeError('Fusion 아카이브 내보내기에 실패했습니다.')
        ui.messageBox('F3D 저장 완료:\n'+filename+'\n\n솔리드 형상 변환입니다. 원본 치수·구속은 함께 내보낸 .cad.json에 보관됩니다.')
    except Exception:
        if ui:ui.messageBox('Prompt CAD 변환 오류:\n'+traceback.format_exc())
