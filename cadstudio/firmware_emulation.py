"""Portable ELF inputs and bounded G474 machine-code execution in Renode.

Uploaded ARM instructions run on the emulated Cortex-M4F, never on the host.
This module does not import Qt, open serial devices, invoke a compiler, or
approve a physical machine. Clock/peripheral coverage is stated in each run.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator, model_serializer
from .firmware_drive import VirtualDriveSpec, MOTOR_SCENARIOS, validate_drive, drive_commands, validate_trace

MAX_ELF_BYTES = 8 * 1024 * 1024
PROFILE = 'stm32g474_hsi16_v1'
RENODE_EXE_SHA256 = '67c2c21eb977181a50a19acbf582c4204d8177d2b4ae0bac4c3d3d51da7a7b4e'
RENODE_MANIFEST_SHA256 = 'fc1192727651cb8ed5dee556419932a1c36db78c87f645857f06c4cb73bdbf56'
FLASH = (0x08000000, 0x08080000)
RAM = ((0x20000000, 0x20018000), (0x10000000, 0x10008000))


def inspect_elf(raw: bytes) -> dict:
    if not 52 <= len(raw) <= MAX_ELF_BYTES or raw[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('ELF32 little-endian ARM 실행파일을 선택하세요.')
    values = struct.unpack_from('<HHIIIIIHHHHHH', raw, 16)
    kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = values
    if (kind, machine, version, ehsize, phsize) != (2, 40, 1, 52, 32) or not 1 <= phnum <= 64:
        raise ValueError('ARM ET_EXEC ELF 헤더 또는 program header가 올바르지 않습니다.')
    if phoff < 52 or phoff + phnum * 32 > len(raw):
        raise ValueError('ELF program header가 파일 범위를 벗어났습니다.')
    segments = []
    ranges = []
    vector = None
    for i in range(phnum):
        ptype, offset, vaddr, paddr, filesz, memsz, permission, align = struct.unpack_from('<IIIIIIII', raw, phoff+i*32)
        if ptype != 1:
            continue
        if filesz > memsz or offset + filesz > len(raw) or memsz > 0x80000:
            raise ValueError('ELF load segment 크기가 올바르지 않습니다.')
        if not memsz:
            continue
        if not any(lo <= vaddr and vaddr+memsz <= hi for lo, hi in (FLASH, *RAM)):
            raise ValueError('ELF load segment가 G474 Flash/RAM 범위를 벗어났습니다.')
        if any(vaddr < end and start < vaddr+memsz for start, end in ranges):
            raise ValueError('ELF load segment가 겹칩니다.')
        ranges.append((vaddr, vaddr+memsz))
        if filesz and not (FLASH[0] <= paddr and paddr+filesz <= FLASH[1]):
            raise ValueError('ELF 초기화 이미지의 load 주소는 G474 Flash여야 합니다.')
        if vaddr == FLASH[0] and filesz >= 8:
            vector = struct.unpack_from('<II', raw, offset)
        segments.append(dict(vaddr=vaddr, paddr=paddr, file_offset=offset, filesz=filesz, memsz=memsz, flags=permission))
    if vector is None:
        raise ValueError('0x08000000의 reset vector가 필요합니다.')
    sp, reset = vector
    if sp % 8 or not any(lo < sp <= hi for lo, hi in RAM) or not reset & 1 or not FLASH[0] <= reset & ~1 < FLASH[1]:
        raise ValueError('G474 reset SP/Thumb PC가 올바르지 않습니다.')
    if not entry & 1 or not any(s['flags'] & 1 and s['vaddr'] <= entry & ~1 < s['vaddr']+s['memsz'] for s in segments):
        raise ValueError('ELF entrypoint가 실행 가능한 Thumb Flash segment에 없습니다.')
    if not any(s['flags'] & 1 and s['vaddr'] <= reset & ~1 < s['vaddr']+s['filesz'] for s in segments):
        raise ValueError('Reset PC가 파일에 있는 실행 가능 segment에 없습니다.')
    symbols = {}
    if shnum:
        if shsize != 40 or shnum > 4096 or shoff+40*shnum > len(raw):
            raise ValueError('ELF section header가 올바르지 않습니다.')
        sections = [struct.unpack_from('<IIIIIIIIII', raw, shoff+i*40) for i in range(shnum)]
        for section in sections:
            _, stype, _, _, offset, size, link, _, _, entsize = section
            if stype != 2:
                continue
            if entsize != 16 or size % 16 or offset+size > len(raw) or link >= shnum:
                raise ValueError('ELF symbol table이 올바르지 않습니다.')
            strings = sections[link]
            if strings[1] != 3 or strings[4]+strings[5] > len(raw):
                raise ValueError('ELF string table이 올바르지 않습니다.')
            names = raw[strings[4]:strings[4]+strings[5]]
            for pos in range(offset, offset+size, 16):
                name, address, length, info, other, index = struct.unpack_from('<IIIBBH', raw, pos)
                if not index or name >= len(names):
                    continue
                end = names.find(b'\x00', name)
                if end < 0:
                    raise ValueError('ELF symbol 이름에 종료 문자가 없습니다.')
                key = names[name:end].decode('utf-8', errors='replace')
                if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,100}', key):
                    symbols[key] = {'address': address, 'size': length, 'type': info & 15}
    return dict(entry=entry, reset_pc=reset, initial_sp=sp, segments=segments, symbols=symbols, flags=flags)


class FirmwareImage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(default_factory=lambda: 'elf_'+uuid4().hex, pattern=r'^elf_[a-f0-9]{32}$')
    name: str = Field(min_length=1, max_length=160)
    target: Literal['stm32g474re'] = 'stm32g474re'
    profile: Literal['stm32g474_hsi16_v1'] = PROFILE
    board_component_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9_-]+$')
    content_base64: str = Field(min_length=1, max_length=((MAX_ELF_BYTES+2)//3)*4)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    wiring_binding: dict
    source_bundle_id: str = Field(default='', max_length=100)
    source_bundle_sha256: str = Field(default='', pattern=r'^([a-f0-9]{64})?$')
    virtual_drive: VirtualDriveSpec | None = None

    @model_serializer(mode='wrap')
    def compatible_drive(self,handler):
        data=handler(self)
        if 'virtual_drive' not in self.model_fields_set and self.virtual_drive is None:data.pop('virtual_drive',None)
        return data

    def bytes(self):
        try:
            return base64.b64decode(self.content_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError('ELF base64가 올바르지 않습니다.') from exc

    @model_validator(mode='after')
    def valid_image(self):
        if Path(self.name).name != self.name or '\\' in self.name or '/' in self.name or any(ord(c)<32 for c in self.name):
            raise ValueError('ELF 이름에는 파일명만 저장하세요.')
        raw = self.bytes()
        if hashlib.sha256(raw).hexdigest() != self.sha256:
            raise ValueError('ELF 내용과 SHA-256이 일치하지 않습니다.')
        inspect_elf(raw)
        return self


def source_fingerprint(bundle):
    raw = bundle.model_dump(mode='json') if hasattr(bundle, 'model_dump') else bundle
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def attach_elf(path, workspace, board_component_id):
    from .electrical import ElectricalWorkspace
    from .firmware_bundle import create_binding
    workspace = ElectricalWorkspace.model_validate(workspace.model_dump() if hasattr(workspace, 'model_dump') else workspace)
    board = next((c for c in workspace.components if c.id == board_component_id), None)
    if board is None or board.kind != 'mcu' or board.catalog_id != 'st_nucleo_g474re' or board.pinout_catalog_id != board.catalog_id:
        raise ValueError('실제 핀맵이 등록된 NUCLEO-G474RE 보드를 선택하세요.')
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_ELF_BYTES+1)
    bundles = [b for b in workspace.firmware_bundles if b.binding.board_component_id == board_component_id]
    if len(bundles) > 1:
        raise ValueError('보드의 소스 묶음이 여러 개입니다. 연결을 명확히 하세요.')
    return FirmwareImage(name=path.name, board_component_id=board_component_id,
        content_base64=base64.b64encode(raw).decode('ascii'), sha256=hashlib.sha256(raw).hexdigest(),
        wiring_binding=create_binding(workspace, board_component_id).model_dump(mode='json'),
        source_bundle_id=bundles[0].id if bundles else '',
        source_bundle_sha256=source_fingerprint(bundles[0]) if bundles else '')


def validate_binding(workspace, image):
    from .electrical import ElectricalWorkspace
    from .firmware_bundle import create_binding
    workspace = ElectricalWorkspace.model_validate(workspace.model_dump() if hasattr(workspace, 'model_dump') else workspace)
    image = FirmwareImage.model_validate(image)
    board = next((c for c in workspace.components if c.id == image.board_component_id), None)
    if board is None or board.catalog_id != 'st_nucleo_g474re' or board.pinout_catalog_id != board.catalog_id:
        raise ValueError('ELF 대상 G474 보드/핀맵이 변경됐습니다.')
    if create_binding(workspace, image.board_component_id).model_dump(mode='json') != image.wiring_binding:
        raise ValueError('ELF를 연결한 뒤 배선·보드·핀맵이 변경됐습니다. 다시 연결하세요.')
    if image.source_bundle_id:
        bundle = next((b for b in workspace.firmware_bundles if b.id == image.source_bundle_id), None)
        if bundle is None or source_fingerprint(bundle) != image.source_bundle_sha256:
            raise ValueError('ELF에 연결된 소스 묶음이 변경됐습니다. 빌드를 확인하고 다시 연결하세요.')
    return workspace, image


def runtime_root():
    # The portable app carries its own pinned backend next to the native EXE.
    return Path(sys.executable).resolve().parent / 'emulators' / 'renode'


def _monitor_path(path):
    value = Path(path).resolve().as_posix()
    if any(c in value for c in '\r\n\x00"'):
        raise ValueError('에뮬레이터 경로에 제어 문자/따옴표가 있습니다.')
    return '"'+value+'"'


def run_firmware(workspace, image, *, output_dir, backend_dir=None, duration_s=0.01, scenario='boot', design=None, observe_symbols=(), cancel_event=None, wall_timeout_s=45):
    workspace, image = validate_binding(workspace, image)
    if not math.isfinite(duration_s) or not 0 < duration_s <= 0.1 or not math.isfinite(wall_timeout_s) or not 1 <= wall_timeout_s <= 120:
        raise ValueError('가상 실행 시간은 0 초과 0.1초 이하, timeout은 1~120초입니다.')
    motor=scenario in MOTOR_SCENARIOS
    spec=validate_drive(design,image) if motor and design is not None else None
    if motor and spec is None:raise ValueError('CAD 가상 구동에는 전체 설계 및 명시 구동 계약이 필요합니다.')
    if scenario not in ('boot','drdy','timer_rollover',*MOTOR_SCENARIOS) or (scenario not in ('boot',*MOTOR_SCENARIOS) and duration_s<0.006):
        raise ValueError('시나리오는 boot/drdy/timer_rollover이며 입력 검사는 6ms 이상 실행하세요.')
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    backend = Path(backend_dir).resolve() if backend_dir else runtime_root()
    executable = backend/'renode.exe'
    assets = Path(__file__).resolve().parent/'emulation'
    profile = assets/'stm32g474_hsi16.repl'
    report = dict(status='blocked', image_sha256=image.sha256, board_component_id=image.board_component_id,
        profile=image.profile, cpu='Cortex-M4F', virtual_duration_s=(0.005+spec.duration_s if motor else duration_s), scenario=scenario, virtual_stimuli=[],
        native_UI_inputs=0, physical_IO=False, qualification=0, allow_motion=False,
        full_binary_loaded=False, reset_executed=False, main_entered=False, main_loop_entered=False,
        diagnostics={}, warnings=[], errors=[], output_dir=str(output),
        limitations=['HSI16 16 MHz virtual peripheral profile; not cycle-accurate hardware timing.',
            'DMA priority arbitration and analog/motor/thermal behavior are not validated.',
            'Source association is recorded; an ELF is not proven compiled from source solely by attachment.',
            'Original firmware decides whether ADC acquisition or drive control starts.'])
    def save():
        (output/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not executable.is_file() or not profile.is_file():
        report['errors'].append('Bundled Renode/backend profile is unavailable.'); save(); return report
    manifest = backend/'cad-runtime-manifest.json'
    if not manifest.is_file():
        report['errors'].append('Renode backend provenance manifest is missing.'); save(); return report
    try:
        manifest_bytes=manifest.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest()!=RENODE_MANIFEST_SHA256:
            report['errors'].append('Renode backend manifest differs from the supported pinned dependency set.');save();return report
        pinned = json.loads(manifest_bytes.decode('utf-8'))
    except (ValueError, OSError):
        report['errors'].append('Renode backend manifest cannot be read.'); save(); return report
    if not isinstance(pinned,dict) or not isinstance(pinned.get('runtime_files',{}),dict):
        report['errors'].append('Renode backend manifest schema is invalid.');save();return report
    if pinned.get('renode_exe_sha256')!=RENODE_EXE_SHA256:
        report['errors'].append('Renode backend manifest does not name the supported portable release.');save();return report
    if hashlib.sha256(executable.read_bytes()).hexdigest() != pinned.get('renode_exe_sha256'):
        report['errors'].append('Renode backend binary does not match its manifest.'); save(); return report
    for relative,expected in pinned.get('runtime_files',{}).items():
        dependency=(backend/relative).resolve()
        if not dependency.is_relative_to(backend) or not dependency.is_file() or hashlib.sha256(dependency.read_bytes()).hexdigest()!=expected:
            report['errors'].append('Renode runtime dependency does not match its manifest: '+relative);save();return report
    raw = image.bytes()
    info = inspect_elf(raw)
    elf = output/'firmware.elf'; elf.write_bytes(raw)
    fields = [('pc','cpu GetRegister 15'), ('icsr','sysbus ReadDoubleWord 0xE000ED04'), ('rcc_cfgr','sysbus ReadDoubleWord 0x40021008'), ('timer2','sysbus ReadDoubleWord 0x40000024'),
              ('gpiob_odr','sysbus.gpiob ReadDoubleWord 0x14')]
    for name in ('uwTick', 'SystemCoreClock'):
        symbol = info['symbols'].get(name)
        if symbol and symbol['size'] == 4 and any(lo <= symbol['address'] < hi-3 for lo,hi in RAM):
            fields.append((name, f'sysbus ReadDoubleWord {symbol["address"]}'))
    if len(observe_symbols)>32 or len(set(observe_symbols))!=len(observe_symbols):raise ValueError('관찰할 고유 32-bit symbol은 최대32개입니다.')
    for name in observe_symbols:
        symbol=info['symbols'].get(name)
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,100}',name) or not symbol or symbol['size']!=4 or not any(lo<=symbol['address']<hi-3 for lo,hi in (FLASH,*RAM)):
            raise ValueError('유효한 32-bit ELF symbol을 선택하세요: '+str(name))
        fields.append(('symbol_'+name,f'sysbus ReadDoubleWord {symbol["address"]}'))
    diagnostic = info['symbols'].get('ft_diagnostics')
    if diagnostic and diagnostic['size'] >= 20 and 0x20000000 <= diagnostic['address'] < 0x20017fa0:
        for name, offset in [('core_hz',0),('adc_faults',4),('controller_faults',8),('qualification',12),('state_flags',16)]:
            fields.append((name, f'sysbus ReadDoubleWord {diagnostic["address"]+offset}'))
    commands = ['mach create "cad-g474"', f'machine LoadPlatformDescription {_monitor_path(profile)}',
        f'sysbus LoadELF {_monitor_path(elf)}', 'cpu VectorTableOffset 0x08000000', 'cpu PerformanceInMips 16',
        'emulation SetGlobalAdvanceImmediately true', 'cpu LogFunctionNames true true',
        f'emulation RunFor "{(duration_s if scenario=="boot" else 0.005):.9f}"']
    if scenario=='drdy':
        commands += ['gpioc OnGPIO 7 true','gpioc OnGPIO 7 false']
        report['virtual_stimuli']=['PC7 high -> low after 5ms boot; synthetic DRDY edge, no ADC conversion model.']
    elif scenario=='timer_rollover':
        commands += ['timer2 WriteDoubleWord 0x24 0xFFFFFF00']
        report['virtual_stimuli']=['TIM2 CNT=0xFFFFFF00 after 5ms boot; synthetic near-overflow setup.']
    if motor:
        mailbox=info['symbols'].get('cad_drive_mailbox')
        if not mailbox or mailbox['size']!=36 or not any(lo<=mailbox['address']<hi-35 for lo,hi in RAM):
            raise ValueError('가상 구동 ELF에는 검증 가능한 cad_drive_mailbox가 필요합니다.')
        config=info['symbols'].get('cad_drive_config')
        segment=next((s for s in info['segments'] if config and s['vaddr']<=config['address'] and config['address']+16<=s['vaddr']+s['filesz']),None)
        if not config or config['size']!=16 or segment is None:raise ValueError('ELF 가상 구동 상수 cad_drive_config가 필요합니다.')
        actual=struct.unpack_from('<4I',raw,segment['file_offset']+config['address']-segment['vaddr'])
        expected=(round(spec.screw_lead_mm_per_rev*1000),spec.synthetic_counts_per_screw_rev,round(spec.max_displacement_mm*1000),2000)
        if actual!=expected:raise ValueError('가상 구동 계약의 리드·카운터·범위·속도가 실제 ELF 상수와 다릅니다.')
        commands += drive_commands(spec,mailbox['address'],scenario)
        report['virtual_stimuli']=['Synthetic TIM1 counter and declared CAD-only GPIO fault bits; physical sensor scale/polarity unverified.']
        report['virtual_drive_model']=spec.model_dump(mode='json')
        report['virtual_drive_elf_constants']=dict(lead_um=actual[0],synthetic_counts_per_rev=actual[1],envelope_um=actual[2],max_command_um_s=actual[3])
        report['limitations'].append('Virtual velocity servo and injected encoder counts; not a physical Maxon/ESCON/linear-sensor calibration.')
    elif scenario!='boot': commands += [f'emulation RunFor "{duration_s-0.005:.9f}"']
    collector = ['import json', 'data = {}']
    for name, command in fields:
        if name=='pc': expression="self.Machine['sysbus.cpu'].GetRegister(15).RawValue"
        else:
            address=0x48000414 if name=='gpiob_odr' else int(command.split()[-1],0)
            expression=f"self.Machine['sysbus'].ReadDoubleWord({address})"
        collector.append(f'data[{name!r}] = int({expression})')
    snapshot = output/'snapshot.json'
    collector.append(f"with open({snapshot.as_posix()!r}, 'w') as stream:")
    collector.append("    json.dump({'completed': True, 'diagnostics': data"+(", 'virtual_trace': virtual_trace, 'virtual_faults': virtual_faults" if motor else '')+"}, stream)")
    # A monitor without a console deliberately discards Python print output.
    # Collect paused CPU/register state to a fresh file before quitting instead.
    commands += ['python """\n'+'\n'.join(collector)+'\n"""']
    commands += ['log "CAD_RUN_FINISHED"', 'quit']
    script = output/'run.resc'; script.write_text('\n'.join(commands), encoding='utf-8')
    # --config selects the config file, but history has a separate default
    # global user path. Keep this run's monitor history in its fresh output.
    # Renode ShellProvider: [general] history-path overrides HistorySavePath.
    (output/'renode.config').write_text(
        '[general]\nhistory-path = '+(output/'history').resolve().as_posix()+'\n',
        encoding='utf-8')
    env = os.environ.copy(); env['RENODE_CI_MODE'] = 'YES'
    args = [str(executable), '--disable-gui', '--hide-analyzers', '-p', '-P', '-1',
        '--config', str(output/'renode.config'), str(script)]
    started = time.monotonic()
    log = output/'renode.log'
    with log.open('wb') as stream:
        try:
            process = subprocess.Popen(args, cwd=backend, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except OSError as exc:
            report['errors'].append('Renode process could not start: '+str(exc)); save(); return report
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    report['status']='cancelled'; break
                if time.monotonic()-started > wall_timeout_s:
                    report['status']='timeout'; break
                if log.stat().st_size > 64*1024*1024:
                    report['status']='fault'; report['errors'].append('Execution log exceeded 64 MiB.'); break
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(5)
    text = log.read_text(encoding='utf-8', errors='replace')
    report['elapsed_wall_s']=round(time.monotonic()-started,3)
    report['process_exit_code']=process.returncode
    report['log_sha256']=hashlib.sha256(log.read_bytes()).hexdigest()
    report['full_binary_loaded']='Setting initial values: PC =' in text
    initial=re.search(r'Setting initial values: PC = 0x([0-9a-fA-F]+), SP = 0x([0-9a-fA-F]+)',text)
    report['reset_vector_matches']=bool(initial and int(initial.group(1),16)&~1==info['reset_pc']&~1 and int(initial.group(2),16)==info['initial_sp'])
    functions = sorted(set(re.findall(r'Entering function ([A-Za-z_][A-Za-z_0-9]*)', text)))
    report['functions_entered']=functions
    report['reset_executed']='Reset_Handler' in functions or report['reset_vector_matches']
    report['main_entered']='main' in functions
    report['main_loop_entered']='ft_board_loop' in functions
    report['scenario_checks']={}
    if scenario=='drdy': report['scenario_checks']['EXTI9_5_IRQHandler']='EXTI9_5_IRQHandler' in functions
    if scenario=='timer_rollover': report['scenario_checks']['TIM2_IRQHandler']='TIM2_IRQHandler' in functions
    if any(not passed for passed in report['scenario_checks'].values()):
        report['errors'].append('Requested virtual interrupt scenario was not observed.')
    faults=[name for name in functions if name in ('HardFault_Handler','BusFault_Handler','UsageFault_Handler','MemManage_Handler')]
    if faults:report['errors'].append('CPU fault handlers entered: '+', '.join(faults))
    all_warnings=[line.strip() for line in text.splitlines() if '[WARNING]' in line]
    report['warnings']=all_warnings[:100];report['warning_count']=len(all_warnings)
    report['errors'] += [line.strip() for line in text.splitlines() if '[ERROR]' in line or 'Unhandled exception' in line or 'There was an error' in line][:100]
    snapshot_ok=False
    if snapshot.is_file():
        try:
            state=json.loads(snapshot.read_text(encoding='utf-8'))
            snapshot_ok=state.get('completed') is True and set(state['diagnostics']) == {name for name,_ in fields} and all(type(v) is int for v in state['diagnostics'].values())
            if snapshot_ok: report['diagnostics']=state['diagnostics']
            if snapshot_ok and motor:
                trace,trace_errors=validate_trace(state,spec,scenario)
                report['virtual_motion_trace']=trace;report['errors']+=trace_errors
                report['virtual_motion_enabled']=any(row['virtual_enable'] for row in trace)
                report['actual_motor_rpm']=None;report['actual_motor_current_a']=None
        except (ValueError, KeyError, TypeError): snapshot_ok=False
    if not snapshot_ok and report['status'] not in ('cancelled','timeout'):
        report['errors'].append('Paused CPU/register snapshot is missing or incomplete.')
    # Tagged DMA priority does not model arbitration latency. Other warnings
    # (unmapped I/O, unsupported SPI mode, etc.) make execution incomplete.
    expected_dma=re.compile(r'.*dma1: Unhandled write to offset 0x(?:8|1C)\. Unhandled bits: \[(?:12|13|12, 13)\] when writing value 0x[0-9A-Fa-f]+\. Tags: Priority level \(PL\) \(0x[1-3]\)\.$')
    bad_warnings = [line for line in all_warnings if not expected_dma.fullmatch(line)]
    if bad_warnings:report['errors'].append('Unsupported peripheral/register access or emulator warning prevented complete execution.')
    if report['status'] not in ('cancelled','timeout','fault'):
        complete = process.returncode == 0 and 'CAD_RUN_FINISHED' in text and snapshot_ok and report['full_binary_loaded'] and report['reset_vector_matches'] and not report['errors'] and not bad_warnings
        report['status']='executed' if complete else 'fault'
    report['firmware_allow_motion'] = bool((report['diagnostics'].get('state_flags',0)>>16)&255) if 'state_flags' in report['diagnostics'] else None
    report['physical_timing_verified']=False
    if report['diagnostics'].get('rcc_cfgr',0) & 0xFCF0:
        report['status']='fault';report['errors'].append('Final RCC dividers do not match the HSI16 peripheral profile.')
    if report['diagnostics'].get('icsr',0) & 0x1FF in (3,4,5,6):
        report['status']='fault';report['errors'].append('CPU remains in a fault exception.')
    save()
    return report
