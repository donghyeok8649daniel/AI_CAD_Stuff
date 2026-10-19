"""Offline PCB commands and lossless capability-aware PCB/project export."""
import argparse
import json
from pathlib import Path
import sys
from .pcb import PCBProject,divider_example
from .pcb_plugin import execute,MANIFEST
from .pcb_compatibility import (CURRENT_PROFILE,PROFILES,PCBCompatibilityError,
    decode_compatible,write_compatible_export)
from .pcb_drill_review import DrillReviewError,decode_review_json
from .pcb_excellon_export import ExcellonExportError,decode_export_profile,prepare_declared_xnc,write_declared_xnc_new,unavailable

from .pcb_excellon_split import prepare_split_xnc,write_split_xnc_package_new,verify_split_xnc_package


def main(argv=None):
    parser=argparse.ArgumentParser(description='Prompt CAD PCB bounded data-only commands')
    parser.add_argument('command',choices=['example','manifest','schema','preflight','export','excellon_export','excellon_split_export','excellon_split_verify',*MANIFEST['commands']])
    parser.add_argument('input',nargs='?');parser.add_argument('--output');parser.add_argument('--backend',default='builtin-linear')
    parser.add_argument('--target-profile',default=CURRENT_PROFILE)
    parser.add_argument('--drill-gap-mm');parser.add_argument('--drill-edge-mm')
    parser.add_argument('--review-format');parser.add_argument('--units');parser.add_argument('--origin')
    parser.add_argument('--max-findings',type=int);parser.add_argument('--review-report')
    parser.add_argument('--excellon-profile')
    parser.add_argument('--excellon-package')
    args=parser.parse_args(argv)
    try:
        review_fields={'minimum_gap_mm':args.drill_gap_mm,'minimum_edge_mm':args.drill_edge_mm,'output_format':args.review_format,'units':args.units,'origin':args.origin,'max_findings':args.max_findings}
        supplied={key:value for key,value in review_fields.items() if value is not None}
        if args.command not in ('drill_review','drill_review_verify') and (supplied or args.review_report):raise ValueError('Drill-review options are not applied to another command.')
        if args.command not in ('excellon_prepare','excellon_export','excellon_split_prepare','excellon_split_export','excellon_split_verify') and args.excellon_profile:raise ValueError('Excellon profile is only consumed by explicit Excellon commands.')
        if args.excellon_package and args.command!='excellon_split_verify':raise ValueError('--excellon-package is only consumed by split package verification.')
        if args.command=='example':result=divider_example().model_dump(mode='json')
        elif args.command=='manifest':result={**MANIFEST,'file_compatibility_profiles':PROFILES}
        elif args.command=='schema':result=PCBProject.model_json_schema()
        else:
            if not args.input:raise ValueError('PCB input file required.')
            target=Path(args.input)
            if target.stat().st_size>2*1024*1024:raise ValueError('PCB CLI input exceeds 2 MiB; this command does not replace the CAD large-project reader.')
            raw,report=decode_compatible(target.read_bytes(),args.target_profile,
                expected_kind=None if args.command in ('preflight','compatibility','export') else 'pcb')
            if args.command in ('excellon_split_prepare','excellon_split_export','excellon_split_verify'):
                profile=None
                if args.excellon_profile:
                    profile_path=Path(args.excellon_profile)
                    if profile_path.stat().st_size>2*1024*1024:raise ValueError('Split export profile exceeds the2MiB CLI bound.')
                    profile=decode_export_profile(profile_path.read_bytes())
                if args.command=='excellon_split_prepare':result=prepare_split_xnc(raw,profile)
                elif args.command=='excellon_split_export':result=write_split_xnc_package_new(raw,profile,args.output) if args.output else unavailable('OUTPUT_REQUIRED','Use --output with a new package directory; parent must exist.')
                else:result=verify_split_xnc_package(raw,profile,args.excellon_package) if args.excellon_package else unavailable('PACKAGE_REQUIRED','Use --excellon-package for the completed package directory.')
                if result['status'] in ('UNAVAILABLE','PARTIAL_WRITE'):
                    print(json.dumps(result,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
                if args.command=='excellon_split_export':
                    print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0
                if args.output and Path(args.output).suffix.lower()!='.json':
                    print(json.dumps(unavailable('UNSUPPORTED_PREVIEW_OUTPUT_EXTENSION','Split previews and verification reports are JSON only; actual export uses a new package directory.'),ensure_ascii=False),file=sys.stderr);return 2
            elif args.command in ('excellon_prepare','excellon_export'):
                profile=None
                if args.excellon_profile:
                    profile_path=Path(args.excellon_profile)
                    if profile_path.stat().st_size>2*1024*1024:raise ValueError('Export profile exceeds the2MiB CLI bound.')
                    profile=decode_export_profile(profile_path.read_bytes())
                result=prepare_declared_xnc(raw,profile) if args.command=='excellon_prepare' else write_declared_xnc_new(raw,profile,args.output) if args.output else unavailable('OUTPUT_REQUIRED','Use --output with a new.xnc path; no implicit output is chosen.')
                if result['status']=='UNAVAILABLE':
                    print(json.dumps(result,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
                if args.command=='excellon_export':
                    print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0
                if args.output and Path(args.output).suffix.lower()!='.json':
                    print(json.dumps(unavailable('UNSUPPORTED_PREVIEW_OUTPUT_EXTENSION','Prepared data preview is JSON only; use excellon_export for actual.xnc text.'),ensure_ascii=False),file=sys.stderr);return 2
            elif args.command=='drill_review':
                if args.review_report:raise ValueError('Use drill_review_verify to consume a review file.')
                result=execute(args.command,raw,**supplied)
            elif args.command=='drill_review_verify':
                if supplied:raise ValueError('Verification uses the rules retained in the report, not replacement rule options.')
                if not args.review_report:raise ValueError('--review-report is required for verification.')
                review_path=Path(args.review_report)
                if review_path.stat().st_size>2*1024*1024:raise ValueError('Drill review exceeds the2MiB CLI input bound.')
                result=execute(args.command,raw,review_report=decode_review_json(review_path.read_bytes()))
            elif args.command in ('preflight','compatibility'):result=report
            elif args.command=='export':
                if not args.output:raise ValueError('Use --output with a new destination for a lossless export.')
                report=write_compatible_export(raw,args.output,args.target_profile)
                print(json.dumps(dict(status='exported',compatibility=report),ensure_ascii=False));return 0
            else:
                project=PCBProject.model_validate(raw)
                result=execute(args.command,project,**(dict(backend=args.backend) if args.command=='simulate' else {}))
        if args.command=='excellon_split_declaration_draft':
            if result.get('status')=='UNAVAILABLE':
                print(json.dumps(result,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
            if args.output and Path(args.output).suffix.lower()!='.json':
                print(json.dumps(unavailable('UNSUPPORTED_DRAFT_OUTPUT_EXTENSION','Declaration drafts are JSON only; they are not fabrication files.'),ensure_ascii=False),file=sys.stderr);return 2
        if args.command in ('drill_review','drill_review_verify'):
            if result.get('status')=='UNAVAILABLE':
                print(json.dumps(result,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
            if args.output and Path(args.output).suffix.lower()!='.json':
                from .pcb_drill_review import _unavailable
                print(json.dumps(_unavailable('UNSUPPORTED_OUTPUT_EXTENSION','Drill-review output is JSON only; no manufacturing filename fallback is used.'),ensure_ascii=False),file=sys.stderr);return 2
        text=result if isinstance(result,str) else json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)
        if args.output:
            # A report must not overwrite its input or any existing user file.
            if args.command in ('preflight','compatibility','drill_review','drill_review_verify','excellon_prepare','excellon_split_prepare','excellon_split_verify','excellon_split_declaration_draft'):
                with Path(args.output).open('x',encoding='utf-8') as stream:stream.write(text)
            else:Path(args.output).write_text(text,encoding='utf-8')
        else:print(text)
        return 0
    except ExcellonExportError as exc:
        print(json.dumps(exc.report,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
    except DrillReviewError as exc:
        print(json.dumps(exc.report,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
    except PCBCompatibilityError as exc:
        print(json.dumps(exc.report,ensure_ascii=False,allow_nan=False),file=sys.stderr);return 2
    except (ValueError,OSError) as exc:
        error=dict(status='blocked',command=args.command,error=str(exc),automatic_fallback=False)
        print(json.dumps(error,ensure_ascii=False),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
