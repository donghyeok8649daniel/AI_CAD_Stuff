"""Portable source geometry and official-application conversion helpers."""
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED
import cadquery as cq
from .kernel import KERNEL_LOCK, build, export
from .models import Project


def inventor_installed():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,'Inventor.Application\\CLSID'):return True
    except (ImportError,OSError):return False


def prepare_native_export(project,target,part_id=None):
    """Prepare exact geometry and a conversion job, without pretending STEP is native."""
    import json,shutil
    from uuid import uuid4
    target=Path(target).resolve()
    if target.suffix.lower() not in ('.f3d','.ipt'):raise ValueError('F3D 또는 IPT 경로를 선택하세요.')
    if target.exists():raise ValueError('같은 이름의 파일이 있습니다. 새 이름으로 저장하세요.')
    folder=target.parent/(target.stem+'-conversion-'+uuid4().hex[:6]);folder.mkdir()
    try:
        source=folder/'design.step'
        if target.suffix.lower()=='.ipt':
            with KERNEL_LOCK:
                parts=project.design.parts;index=next((i for i,p in enumerate(parts) if p.id==part_id),None)
                if index is None:raise ValueError('IPT로 저장할 부품을 선택하세요.')
                shape=build(project.design)[index]
                if not shape.Solids():raise ValueError('현재 IPT 변환은 솔리드 부품을 지원합니다.')
                cq.exporters.export(shape,str(source),exportType='STEP')
        else:export(project.design,source,'step')
        (folder/'source.cad.json').write_text(project.model_dump_json(indent=2),encoding='utf-8')
        job=dict(source=str(source),target=str(target));(folder/'job.json').write_text(json.dumps(job,ensure_ascii=False,indent=2),encoding='utf-8')
        integrations=Path(__file__).resolve().parent.parent/'integrations'
        if target.suffix.lower()=='.f3d':
            script=folder/'PromptCADImport';shutil.copytree(integrations/'Fusion/PromptCADImport',script,ignore=shutil.ignore_patterns('__pycache__'));(script/'job.json').write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
        else:shutil.copy2(integrations/'ConvertSingleToIpt.ps1',folder/'ConvertSingleToIpt.ps1')
        (folder/'README.md').write_text('변환 대상: '+str(target)+'\n\n'+(integrations/'README.md').read_text(encoding='utf-8'),encoding='utf-8')
        return folder
    except Exception:
        # This folder was just created above with an unpredictable name.
        if folder.resolve().parent==target.parent and folder.name.startswith(target.stem+'-conversion-'):shutil.rmtree(folder)
        raise


def convert_ipt_job(folder):
    import subprocess,json
    folder=Path(folder);job=json.loads((folder/'job.json').read_text(encoding='utf-8'))
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(folder/'ConvertSingleToIpt.ps1'),'-JobFile',str(folder/'job.json')],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=180)
    if result.returncode or not Path(job['target']).is_file():raise ValueError('Inventor 변환을 완료하지 못했습니다. Inventor 설치·라이선스를 확인하세요. 변환 준비 파일은 보존했습니다.')
    return Path(job['target'])


def conversion_package(design):
    project=design if isinstance(design,Project) else Project(design=design)
    design=project.design
    result=BytesIO()
    integrations=Path(__file__).resolve().parent.parent/'integrations'
    with tempfile.TemporaryDirectory(prefix='prompt-cad-convert-') as temp, ZipFile(result,'w',ZIP_DEFLATED) as archive:
        folder=Path(temp)
        step=folder/'design.step';export(design,step,'step')
        archive.write(step,'design.step')
        archive.writestr('design.cad.json',project.model_dump_json(indent=2))
        with KERNEL_LOCK:
            for part,shape in zip(design.parts,build(design)):
                path=folder/f'{part.id}.step'
                cq.exporters.export(shape,str(path),exportType='STEP')
                archive.write(path,f'parts/{part.id}.step')
        for path in integrations.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path,path.relative_to(integrations).as_posix())
    return result.getvalue()
