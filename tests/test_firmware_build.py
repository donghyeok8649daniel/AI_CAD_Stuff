from pathlib import Path
from hashlib import sha256
import sys
import time

import pytest

from cadstudio.firmware_build import check_firmware_bundle
from cadstudio.firmware_bundle import create_bundle


def work(catalog='rpi4b'):
    return {'nodes':['GND','V5'],'components':[{'id':'board','name':'Board','kind':'mcu',
        'a':'V5','b':'GND','catalog_id':catalog,'part_registration':True,'part_id':'cad_board',
        'pinout_catalog_id':catalog,'analysis_enabled':False}]}


def bundle(source='value = 1\n',target='raspberry_python',catalog='rpi4b',missing=(),files=None):
    path='main.py' if target=='raspberry_python' else 'main.c'
    return create_bundle('Syntax review',target,work(catalog),'board',
        files or [{'path':path,'content':source}],path,missing_parameters=missing)


def test_python_compile_checks_all_files_without_execution_or_import(tmp_path):
    marker=tmp_path/'must-not-exist'
    source=f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\nimport non_existing_hardware\n'
    candidate=bundle(source,files=[{'path':'main.py','content':source},{'path':'helpers.py','content':'def read():\n    return 0\n'}])
    report=check_firmware_bundle(candidate,workspace=work())
    assert report.status=='syntax_ok' and not marker.exists()
    assert len(report.checks)==3
    assert not report.executed_generated_code and not report.flashed_hardware and not report.full_target_build
    assert report.source_sha256['main.py']==sha256(source.encode()).hexdigest()


def test_python_syntax_diagnostic_has_file_line_and_current_source_sha():
    candidate=bundle('if True\n    pass\n')
    report=check_firmware_bundle(candidate,workspace=work())
    assert report.status=='failed'
    assert report.diagnostics[0].path=='main.py' and report.diagnostics[0].line==1
    assert report.diagnostics[0].code=='python_syntax'


def test_missing_hardware_parameters_are_pending_even_with_valid_python():
    report=check_firmware_bundle(bundle(missing=['Actual motor current limit']),workspace=work())
    assert report.status=='pending'
    assert any(item.code=='missing_parameter' for item in report.diagnostics)


def test_unprovided_workspace_is_not_silently_treated_as_current_wiring():
    report=check_firmware_bundle(bundle())
    assert report.status=='pending'
    assert any(item.code=='binding_not_checked' for item in report.diagnostics)


def test_stale_board_or_circuit_is_rejected_before_checks(monkeypatch):
    changed=work();changed['components'][0]['part_id']='different_part'
    report=check_firmware_bundle(bundle(),workspace=changed)
    assert report.status=='failed' and not report.checks
    assert report.diagnostics[0].code=='stale_binding'


def test_cancel_before_check_and_between_python_files():
    assert check_firmware_bundle(bundle(),cancelled=lambda:True).status=='cancelled'
    candidate=bundle(files=[{'path':'main.py','content':'pass\n'},{'path':'helper.py','content':'pass\n'}])
    calls=0
    def cancel():
        nonlocal calls
        calls+=1
        return calls>=3
    report=check_firmware_bundle(candidate,workspace=work(),cancelled=cancel)
    assert report.status=='cancelled'
    assert any(check.name=='main.py' for check in report.checks)
    assert not any(check.name=='helper.py' for check in report.checks)


def test_missing_stm32_toolchain_and_sdk_are_reported_without_launching(monkeypatch):
    import cadstudio.firmware_build as module
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:pytest.fail('Missing SDK must not start a compiler'))
    candidate=bundle('#include "stm32g4xx_hal.h"\nint main(void){return 0;}\n','stm32_hal','st_nucleo_g474re')
    report=check_firmware_bundle(candidate,workspace=work('st_nucleo_g474re'))
    assert report.status=='pending'
    assert {item.code for item in report.diagnostics}>={'toolchain_missing','sdk_header_missing'}


@pytest.mark.parametrize('source',['#include "/private/key.h"\nint main(void){return 0;}',
    '#include "../key.h"\nint main(void){return 0;}',
    '#define HEADER "/private/key.h"\n#include HEADER\nint main(void){return 0;}',
    '%:include "/private/key.h"\nint main(void){return 0;}',
    '#pragma GCC dependency "/private/key.h"\nint main(void){return 0;}',
    '#embed "/private/key.h"\nint main(void){return 0;}'])
def test_compiler_cannot_read_arbitrary_source_include_paths_or_hooks(source,monkeypatch):
    import cadstudio.firmware_build as module
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:pytest.fail('Unsafe source must not start a compiler'))
    report=check_firmware_bundle(bundle(source,'stm32_hal','nucleo_f446re'),workspace=work('nucleo_f446re'))
    assert report.status=='failed'
    assert any(item.severity=='error' for item in report.diagnostics)


def test_unsupported_compiler_wrappers_never_launched(tmp_path,monkeypatch):
    import cadstudio.firmware_build as module
    wrapper=tmp_path/'build.cmd';wrapper.write_text('echo unsafe')
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:pytest.fail('Wrapper must not launch'))
    report=check_firmware_bundle(bundle('int main(void){return 0;}','stm32_hal','nucleo_f446re'),
        workspace=work('nucleo_f446re'),compiler_path=wrapper)
    assert report.status=='pending' and report.diagnostics[0].code=='unsupported_toolchain'


@pytest.mark.parametrize('outcome,returncode,expected',[('complete',0,'pending'),('complete',1,'failed'),
    ('timeout',None,'pending'),('cancelled',None,'cancelled')])
def test_explicit_c_check_has_fixed_argv_cleanup_and_truthful_target_scope(tmp_path,monkeypatch,outcome,returncode,expected):
    import cadstudio.firmware_build as module
    compiler=tmp_path/('gcc.exe' if module.os.name=='nt' else 'gcc');compiler.write_text('placeholder, never executed')
    captured={}
    def run(argv,directory,actual_compiler,cancelled,timeout_s):
        captured.update(argv=argv,directory=directory)
        assert '-fsyntax-only' in argv and '-I' in argv
        assert not any(argument.startswith(('@','-fplugin','-specs')) for argument in argv)
        assert (directory/'main.c').exists()
        return outcome,returncode,'parse error' if returncode else ''
    monkeypatch.setattr(module,'_run_compiler',run)
    # The real subprocess execution path is covered separately with the system
    # Python process used as a harmless stand-in, never a generated program.
    report=check_firmware_bundle(bundle('int main(void){return 0;}','stm32_hal','nucleo_f446re'),
        workspace=work('nucleo_f446re'),compiler_path=compiler)
    assert report.status==expected and not report.full_target_build
    assert not captured['directory'].exists()
    assert str(compiler.resolve())==captured['argv'][0]


@pytest.mark.parametrize('timeout',[0,-1,float('nan'),float('inf'),121])
def test_check_timeout_is_bounded(timeout):
    with pytest.raises(ValueError):
        check_firmware_bundle(bundle(),timeout_s=timeout)


def test_owned_process_diagnostics_are_bounded_and_environment_hooks_removed(tmp_path,monkeypatch):
    import cadstudio.firmware_build as module
    original=module.subprocess.Popen; captured={}
    def start(argv,**kwargs):
        captured['env']=kwargs['env']
        return original(argv,**kwargs)
    monkeypatch.setattr(module.subprocess,'Popen',start)
    monkeypatch.setenv('CPATH','not-used')
    monkeypatch.setenv('GCC_EXEC_PREFIX','not-used')
    # Fixed test harness only; this is never firmware from a candidate.
    argv=[sys.executable,'-I','-c','import sys; sys.stdout.write("x" * 131072)']
    outcome,code,text=module._run_compiler(argv,tmp_path,Path(sys.executable),lambda:False,5)
    assert outcome=='complete' and code==0
    assert len(text)<module.MAX_DIAGNOSTIC_BYTES+100 and 'truncated' in text
    assert 'CPATH' not in captured['env'] and 'GCC_EXEC_PREFIX' not in captured['env']


@pytest.mark.parametrize('cancel',[False,True])
def test_owned_process_timeout_and_cancel_reap_the_child(tmp_path,monkeypatch,cancel):
    import cadstudio.firmware_build as module
    original=module.subprocess.Popen; processes=[]
    def start(argv,**kwargs):
        process=original(argv,**kwargs);processes.append(process)
        return process
    monkeypatch.setattr(module.subprocess,'Popen',start)
    began=time.monotonic()
    cancelled=(lambda:time.monotonic()-began>.1) if cancel else (lambda:False)
    argv=[sys.executable,'-I','-c','import time; time.sleep(20)']
    outcome,_,_=module._run_compiler(argv,tmp_path,Path(sys.executable),cancelled,.2)
    assert outcome==('cancelled' if cancel else 'timeout')
    assert time.monotonic()-began<5
    assert len(processes)==1 and processes[0].poll() is not None


def test_failed_job_containment_stops_owned_child_instead_of_continuing(tmp_path,monkeypatch):
    import cadstudio.firmware_build as module
    original=module.subprocess.Popen;processes=[]
    def start(argv,**kwargs):
        process=original(argv,**kwargs);processes.append(process)
        return process
    def reject(pid):
        raise ValueError('Test containment failure')
    monkeypatch.setattr(module.subprocess,'Popen',start)
    monkeypatch.setattr(module,'_CompilerJob',reject)
    with pytest.raises(ValueError,match='containment failure'):
        module._run_compiler([sys.executable,'-I','-c','import time; time.sleep(20)'],
            tmp_path,Path(sys.executable),lambda:False,5)
    assert processes[0].poll() is not None
