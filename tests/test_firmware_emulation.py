"""ELF boundaries, stale wiring, persistence and process containment."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import struct
import threading

import pytest

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.firmware_bundle import create_bundle
from cadstudio.firmware_emulation import FirmwareImage, attach_elf, inspect_elf, run_firmware, validate_binding


def elf_bytes(code=b'\x00\xbf\xfe\xe7'):
    raw=bytearray(0x200+len(code))
    raw[:16]=b'\x7fELF\x01\x01\x01'+bytes(9)
    struct.pack_into('<HHIIIIIHHHHHH',raw,16,2,40,1,0x08000101,52,0,0x5000000,52,32,1,40,0,0)
    struct.pack_into('<IIIIIIII',raw,52,1,0x100,0x08000000,0x08000000,0x100+len(code),0x100+len(code),5,4)
    struct.pack_into('<II',raw,0x100,0x20010000,0x08000101)
    raw[0x200:]=code
    return bytes(raw)


def workspace():
    return ElectricalWorkspace.model_validate(dict(nodes=['GND','PWR','SIGNAL','OTHER'],components=[
        dict(id='board',name='G474',kind='mcu',a='PWR',b='GND',catalog_id='st_nucleo_g474re',
             pinout_catalog_id='st_nucleo_g474re',part_id='board_body',part_registration=True,
             analysis_enabled=False,signal_pins={}),
        dict(id='wire',name='lead',kind='wire',a='SIGNAL',b='OTHER',closed=True,length_mm=100,cross_section_mm2=0.5)]))


def image(tmp_path,work=None):
    file=tmp_path/'bounded.elf';file.write_bytes(elf_bytes())
    return attach_elf(file,work or workspace(),'board')


def test_valid_elf_inspection_and_exact_roundtrip(tmp_path):
    data=elf_bytes();info=inspect_elf(data)
    assert info['initial_sp']==0x20010000 and info['reset_pc']==0x08000101
    item=image(tmp_path)
    assert FirmwareImage.model_validate_json(item.model_dump_json()).bytes()==data
    assert item.sha256==sha256(data).hexdigest()


@pytest.mark.parametrize('offset,fmt,value',[(18,'H',62),(16,'H',3),(28,'I',0xFFFFFF00),
    (56,'I',0xFFFFFF00),(60,'I',0x40000000),(68,'I',0xFFFFFFFF),
    (0x100,'I',0x20010001),(0x104,'I',0x08000401),(0x104,'I',0x08000100),
    (24,'I',0x08000301),(76,'I',4)])
def test_corrupt_headers_memory_and_vectors_fail(offset,fmt,value):
    raw=bytearray(elf_bytes());struct.pack_into('<'+fmt,raw,offset,value)
    with pytest.raises(ValueError):inspect_elf(bytes(raw))


def test_tampered_bytes_and_path_names_fail(tmp_path):
    raw=image(tmp_path).model_dump();raw['content_base64']=base64.b64encode(elf_bytes()+b'x').decode()
    with pytest.raises(ValueError,match='SHA'):FirmwareImage.model_validate(raw)
    for name in ('../a.elf','C:\\a.elf','a\n.elf'):
        raw=image(tmp_path).model_dump();raw['name']=name
        with pytest.raises(ValueError):FirmwareImage.model_validate(raw)


def test_stale_wiring_and_source_fail_without_breaking_saved_load(tmp_path):
    work=workspace()
    bundle=create_bundle('G474 source','stm32_hal',work,'board',[dict(path='main.c',content='int main(void){for(;;){}}')],'main.c')
    work.firmware_bundles=[bundle];item=image(tmp_path,work)
    changed=work.model_dump(mode='json');changed['components'][1]['closed']=False
    changed['firmware_images']=[item.model_dump(mode='json')]
    loaded=ElectricalWorkspace.model_validate(changed)
    with pytest.raises(ValueError,match='배선'):validate_binding(loaded,item)
    changed=work.model_copy(deep=True);changed.firmware_bundles[0].notes='new source context'
    with pytest.raises(ValueError,match='소스'):validate_binding(changed,item)


def test_legacy_absent_empty_and_duplicate_images(tmp_path):
    old=workspace().model_dump(mode='json')
    assert 'firmware_images' not in old
    assert ElectricalWorkspace.model_validate(old).model_dump(mode='json')==old
    old['firmware_images']=[]
    assert ElectricalWorkspace.model_validate(old).model_dump(mode='json')==old
    old['firmware_images']=[image(tmp_path).model_dump(mode='json')]*2
    with pytest.raises(ValueError):ElectricalWorkspace.model_validate(old)


def test_project_save_reload_exact_undo_redo(tmp_path):
    from cadstudio.models import Design
    from cadstudio.native.document import Document,read_project
    design=Design.model_validate(dict(name='Runtime fixture',parts=[dict(id='board_body',name='G474',role='electrical',
        geometry=dict(kind='plate',length=70,width=60,thickness=2,hole_count=0))],electrical=workspace().model_dump(mode='json')))
    doc=Document();doc.commit(design,'Original');before=deepcopy(doc.design);first=doc.journal.path()[-1]['id']
    attached=design.model_dump(mode='json');attached['electrical']['firmware_images']=[image(tmp_path).model_dump(mode='json')]
    doc.commit(Design.model_validate(attached),'ELF');last=doc.journal.path()[-1]['id']
    file=tmp_path/'saved.pcad';doc.write(file);restored=read_project(file)
    assert restored.design.electrical.firmware_images[0].bytes()==elf_bytes()
    assert doc.journal.at(first)==before and doc.journal.at(last)==attached


def test_headless_entry_excludes_window_actions_and_preserves_older_flags():
    from native_desktop import parse_startup_args
    args=parse_startup_args(['--g474-project','input.pcad','--g474-run-dir','run'])
    assert args.open is None and args.g474_project==Path('input.pcad')
    with pytest.raises(SystemExit):parse_startup_args(['--g474-project','input.pcad','--g474-run-dir','run','--open','other.pcad'])
    with pytest.raises(SystemExit):parse_startup_args(['--g474-run-dir','run'])
    assert parse_startup_args(['--program-drive-package-check','check.json']).program_drive_package_check
    assert parse_startup_args(['--role-performance-check','check.json']).role_performance_check


def test_backend_missing_and_hash_mismatch_block(tmp_path):
    item=image(tmp_path)
    result=run_firmware(workspace(),item,output_dir=tmp_path/'missing',backend_dir=tmp_path/'no-backend')
    assert result['status']=='blocked' and result['physical_IO'] is False
    backend=tmp_path/'backend';backend.mkdir();(backend/'renode.exe').write_bytes(b'fake')
    (backend/'cad-runtime-manifest.json').write_text(json.dumps(dict(renode_exe_sha256='0'*64)))
    result=run_firmware(workspace(),item,output_dir=tmp_path/'wrong-sha',backend_dir=backend)
    assert result['status']=='blocked' and 'manifest' in result['errors'][0]


@pytest.mark.parametrize('duration',[0,-1,float('nan'),float('inf'),0.101])
def test_duration_bound_is_checked_before_process(tmp_path,duration):
    with pytest.raises(ValueError):run_firmware(workspace(),image(tmp_path),output_dir=tmp_path/'run',duration_s=duration)


@pytest.mark.parametrize('cancel',[False,True])
def test_timeout_and_cancel_terminate_only_owned_process(tmp_path,monkeypatch,cancel):
    import cadstudio.firmware_emulation as module
    backend=tmp_path/'backend';backend.mkdir();(backend/'renode.exe').write_bytes(b'fake')
    (backend/'cad-runtime-manifest.json').write_text(json.dumps(dict(renode_exe_sha256=sha256(b'fake').hexdigest())))
    calls=[]
    class Child:
        returncode=None
        def __init__(self,args,**kwargs):
            calls.append((args,kwargs));assert '--disable-gui' in args and kwargs['stdin']==module.subprocess.DEVNULL
        def poll(self):return self.returncode
        def terminate(self):self.returncode=-15;calls.append('terminate')
        def wait(self,*args):return self.returncode
    monkeypatch.setattr(module.subprocess,'Popen',Child)
    monkeypatch.setattr(module,'RENODE_EXE_SHA256',sha256(b'fake').hexdigest())
    event=threading.Event()
    if cancel:event.set()
    result=run_firmware(workspace(),image(tmp_path),output_dir=tmp_path/'run',backend_dir=backend,cancel_event=event,wall_timeout_s=1)
    assert result['status']==('cancelled' if cancel else 'timeout') and calls[-1]=='terminate'
    assert result['allow_motion'] is False


def test_offscreen_dialog_attachment_running_cancel_and_export(tmp_path,monkeypatch):
    # Construct only invisible Qt widgets; no user window/capture/activation.
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    import cadstudio.native.firmware_emulation_dialog as view
    app=QApplication.instance() or QApplication([])
    file=tmp_path/'input.elf';file.write_bytes(elf_bytes())
    monkeypatch.setattr(view.QFileDialog,'getOpenFileName',lambda *a: (str(file),''))
    dialog=view.FirmwareEmulationDialog(workspace(),language='ko')
    assert not dialog.isVisible() and not dialog.run_button.isEnabled()
    dialog.attach();assert dialog.images[0].bytes()==elf_bytes() and dialog.run_button.isEnabled()
    class Pool:
        def start(self,worker):self.worker=worker
    pool=Pool();monkeypatch.setattr(view.QThreadPool,'globalInstance',lambda:pool)
    dialog.run_image();assert not dialog.boards.isEnabled() and dialog.stop.isEnabled()
    dialog.reject();assert pool.worker.cancel.is_set() and dialog._running
    result=dict(status='cancelled',physical_IO=False,allow_motion=False)
    pool.worker.signals.finished.emit(result);app.processEvents()
    assert dialog.result==result and dialog.boards.isEnabled() and dialog.export.isEnabled()
    output=tmp_path/'export.json';monkeypatch.setattr(view.QFileDialog,'getSaveFileName',lambda *a: (str(output),''))
    dialog.export_result();assert json.loads(output.read_text(encoding='utf-8'))==result
    dialog.reject();dialog.deleteLater();app.processEvents()


def test_headless_missing_input_reports_error_without_importing_window(tmp_path):
    from cadstudio.firmware_emulation_cli import main
    output=tmp_path/'report'
    assert main(['--project',str(tmp_path/'missing.pcad'),'--run-dir',str(output)])==2
    report=json.loads((output/'result.json').read_text(encoding='utf-8'))
    assert report['status']=='blocked' and report['native_UI_inputs']==0 and report['physical_IO'] is False
