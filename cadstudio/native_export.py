"""Portable source geometry and official-application conversion helpers."""
from io import BytesIO
from pathlib import Path
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED
import cadquery as cq
from .kernel import KERNEL_LOCK, build, export
from .models import Project


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
