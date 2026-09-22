"""Run inside Autodesk Fusion: import a STEP into a NEW document and export F3D."""
import os
import traceback
import adsk.core
import adsk.fusion


def run(context):
    ui=None
    try:
        app=adsk.core.Application.get();ui=app.userInterface
        source=ui.createFileDialog();source.title='Prompt CAD — 변환할 STEP 선택';source.filter='STEP files (*.step;*.stp)'
        if source.showOpen()!=adsk.core.DialogResults.DialogOK:return
        target=ui.createFileDialog();target.title='Fusion 아카이브 저장';target.filter='Fusion archive (*.f3d)'
        target.initialDirectory=os.path.dirname(source.filename)
        target.initialFilename=os.path.splitext(os.path.basename(source.filename))[0]+'.f3d'
        if target.showSave()!=adsk.core.DialogResults.DialogOK:return
        filename=target.filename
        if not filename.lower().endswith('.f3d'):filename+='.f3d'
        manager=app.importManager
        document=manager.importToNewDocument(manager.createSTEPImportOptions(source.filename))
        if not document:raise RuntimeError('STEP 가져오기에 실패했습니다.')
        design=adsk.fusion.Design.cast(document.products.itemByProductType('DesignProductType'))
        if not design:raise RuntimeError('Fusion 설계 제품을 찾지 못했습니다.')
        options=design.exportManager.createFusionArchiveExportOptions(filename)
        if not design.exportManager.execute(options) or not os.path.isfile(filename):
            raise RuntimeError('Fusion 아카이브 내보내기에 실패했습니다.')
        ui.messageBox('F3D 저장 완료:\n'+filename+'\n\n솔리드 형상 변환입니다. 원본 치수·구속은 함께 내보낸 .cad.json에 보관됩니다.')
    except Exception:
        if ui:ui.messageBox('Prompt CAD 변환 오류:\n'+traceback.format_exc())
