"""Headless entry point. No native window or physical device is constructed."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from .firmware_emulation import FirmwareImage, attach_elf, run_firmware


def main(argv=None):
    parser=argparse.ArgumentParser(description='G474 ELF를 CAD에 연결하거나 화면 없이 실행합니다.')
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--elf', type=Path)
    parser.add_argument('--board', default='')
    parser.add_argument('--save-project', type=Path)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--backend-dir', type=Path)
    parser.add_argument('--duration', type=float, default=0.01)
    parser.add_argument('--scenario', choices=['boot','drdy','timer_rollover','motor_drive','motor_stop','motor_guard','motor_limit'], default='boot')
    parser.add_argument('--observe-symbol',action='append',default=[])
    args=parser.parse_args(argv)
    fresh=False
    try:
        fresh=args.run_dir is not None and not args.run_dir.exists()
        return _execute(args,parser)
    except Exception as exc:
        # Frozen Windows executables have no console. Handle headless failures
        # here so the bootloader cannot create an error popup over the user UI.
        report=dict(status='blocked' if isinstance(exc,(ValueError,OSError,KeyError)) else 'fault',
                    errors=[str(exc)],exception_type=type(exc).__name__,physical_IO=False,native_UI_inputs=0,allow_motion=False)
        if fresh:
            try:
                args.run_dir.mkdir(parents=True,exist_ok=True)
                with (args.run_dir/'result.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
            except OSError:pass
        print(json.dumps(report,ensure_ascii=False))
        return 2


def _execute(args,parser):
    raw=json.loads(args.project.read_bytes())
    original=copy.deepcopy(raw)
    workspace=raw['design']['electrical']
    if args.elf:
        if not args.board: parser.error('--elf에는 --board가 필요합니다.')
        image=attach_elf(args.elf, workspace, args.board)
        before=copy.deepcopy(workspace.get('firmware_images'))
        existed='firmware_images' in workspace
        images=[i for i in workspace.get('firmware_images',[]) if i['board_component_id'] != image.board_component_id]
        images.append(image.model_dump(mode='json'))
        workspace['firmware_images']=images
        journal=raw['history']
        if journal['cursor'] != journal['head']: parser.error('작업 이력의 중간에서 ELF를 덮어쓰지 않습니다.')
        step='step-'+uuid4().hex
        journal['entries'].append(dict(id=step,parent=journal['cursor'],label='G474 전체 펌웨어 ELF 연결',
            created_at=datetime.now(timezone.utc).isoformat(),source='manual',
            changes=[dict(path=['electrical','firmware_images'],operation='set',existed=existed,before=before,after=copy.deepcopy(images))],
            context={'scope':'G474 ARM binary attachment','physical_flash':False,'GUI_inputs':0}))
        journal['cursor']=journal['head']=step
        # Only the images leaf and one matching journal entry may change.
        undo=copy.deepcopy(raw)
        if existed: undo['design']['electrical']['firmware_images']=before
        else: del undo['design']['electrical']['firmware_images']
        undo['history']=copy.deepcopy(original['history'])
        assert undo == original
    else:
        images=[i for i in workspace.get('firmware_images',[]) if not args.board or i['board_component_id']==args.board]
        if len(images)!=1: parser.error('저장된 ELF 대상 하나를 선택하세요.')
        image=FirmwareImage.model_validate(images[0])
    if args.save_project:
        if args.save_project.resolve()==args.project.resolve(): parser.error('원본 CAD를 덮어쓰지 않습니다. 새 파일을 지정하세요.')
        from .models import Project
        serialized=json.dumps(raw,ensure_ascii=False,separators=(',', ':'),allow_nan=False).encode('utf-8')
        Project.model_validate_json(serialized)
        args.save_project.parent.mkdir(parents=True,exist_ok=True)
        with args.save_project.open('xb') as stream: stream.write(serialized)
        print(json.dumps({'saved_project':str(args.save_project),'image_sha256':image.sha256},ensure_ascii=False),flush=True)
    if args.run_dir:
        result=run_firmware(workspace,image,output_dir=args.run_dir,backend_dir=args.backend_dir,duration_s=args.duration,scenario=args.scenario,design=raw['design'],observe_symbols=args.observe_symbol)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status']=='executed' else 2
    return 0


if __name__=='__main__': raise SystemExit(main())
