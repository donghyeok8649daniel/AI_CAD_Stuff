"""Collect installed distribution notices, plus the upstream OCP/OCCT notices."""
from importlib import metadata
from pathlib import Path
import shutil
import sys
import urllib.request
root=Path(__file__).resolve().parent.parent
target=root/'licenses';target.mkdir(exist_ok=True)
manifest=[]
for dist in sorted(metadata.distributions(),key=lambda d:d.metadata['Name'].lower()):
    name=dist.metadata['Name'];version=dist.version
    manifest.append(f'{name}=={version}')
    for filename in dist.files or []:
        if any(token in filename.name.lower() for token in ('license','copying','copyright','notice')):
            source=Path(dist.locate_file(filename))
            if source.is_file() and source.suffix not in {'.py','.pyc','.pyd','.dll'}:
                dest=target/f'{name}-{version}'/filename.name
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
for name,url in {
    'OCP-LICENSE.txt':'https://raw.githubusercontent.com/CadQuery/OCP/master/LICENSE',
    'OCCT-LICENSE_LGPL_21.txt':'https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_9_3/LICENSE_LGPL_21.txt',
    'OCCT-LGPL_EXCEPTION.txt':'https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_9_3/OCCT_LGPL_EXCEPTION.txt',
}.items():
    with urllib.request.urlopen(url,timeout=30) as response:(target/name).write_bytes(response.read())
python_license=Path(sys.base_prefix)/'LICENSE.txt'
if python_license.exists():shutil.copy2(python_license,target/'Python-LICENSE.txt')
shutil.copy2(root/'static/vendor/LICENSE',target/'Threejs-LICENSE.txt')
(target/'distribution-versions.txt').write_text('\n'.join(manifest)+'\n',encoding='utf-8')
print(f'Collected {len(list(target.rglob("*")))} notice entries.')
