"""Offline entry: python -m cadstudio.pcb_cli COMMAND FILE [--output FILE]."""
import argparse
import json
from pathlib import Path
import sys
from .pcb import PCBProject,divider_example
from .pcb_plugin import execute,MANIFEST


def main(argv=None):
    parser=argparse.ArgumentParser(description='Prompt CAD PCB bounded data-only commands')
    parser.add_argument('command',choices=['example','manifest','schema',*MANIFEST['commands']])
    parser.add_argument('input',nargs='?');parser.add_argument('--output');parser.add_argument('--backend',default='builtin-linear')
    args=parser.parse_args(argv)
    try:
        if args.command=='example':result=divider_example().model_dump(mode='json')
        elif args.command=='manifest':result=MANIFEST
        elif args.command=='schema':result=PCBProject.model_json_schema()
        else:
            if not args.input:raise ValueError('PCB input file required.')
            target=Path(args.input)
            if target.stat().st_size>2*1024*1024:raise ValueError('PCB input exceeds 2 MiB.')
            project=PCBProject.model_validate_json(target.read_bytes())
            result=execute(args.command,project,**(dict(backend=args.backend) if args.command=='simulate' else {}))
        text=result if isinstance(result,str) else json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
        if args.output:Path(args.output).write_text(text,encoding='utf-8')
        else:print(text)
        return 0
    except (ValueError,OSError) as exc:
        error=dict(status='blocked',command=args.command,error=str(exc),automatic_fallback=False)
        print(json.dumps(error,ensure_ascii=False),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
