"""Readonly, explicit input/run controller. No Qt, file defaults or code IO."""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json,math,stat,threading,time
from pathlib import Path
from ..program_drive_adapter import DriveContract,ParameterRecord,fingerprint,drive_review_view_model

MAX_JSON_BYTES=256*1024


@dataclass(frozen=True)
class BoundJSON:
    path:Path
    payload:dict
    raw_sha256:str
    bytes:int


def read_input_json(path,kind):
    """Only explicitly chosen local JSON, bounded and strictly decoded."""
    if kind not in ('contract','parameters'):raise ValueError('Unknown input kind')
    path=Path(path)
    if str(path).startswith(('\\\\','//')):raise ValueError('Select a local JSON file; network paths are not read by this bounded review.')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode):raise ValueError('Select a regular JSON file.')
    if info.st_size>MAX_JSON_BYTES:raise ValueError('JSON input exceeds256KiB.')
    with path.open('rb') as stream:raw=stream.read(MAX_JSON_BYTES+1)
    if len(raw)>MAX_JSON_BYTES:raise ValueError('JSON input exceeds256KiB.')
    def invalid(value):raise ValueError('Nonfinite JSON number: '+value)
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate JSON key: '+key)
            result[key]=value
        return result
    value=json.loads(raw.decode('utf-8-sig'),parse_constant=invalid,object_pairs_hook=unique)
    if not isinstance(value,dict):raise ValueError('The JSON root must be an object.')
    model=DriveContract if kind=='contract' else ParameterRecord
    model.model_validate(value)
    return BoundJSON(path.resolve(),deepcopy(value),sha256(raw).hexdigest(),len(raw))


class BudgetCancel(threading.Event):
    def __init__(self,seconds=30.):
        super().__init__();self.deadline=time.monotonic()+seconds;self.timed_out=False
    def is_set(self):
        if time.monotonic()>=self.deadline:self.timed_out=True;self.set()
        return super().is_set()


@dataclass(frozen=True)
class RunTicket:
    generation:int
    document_identity:int
    design_fingerprint:str
    config_fingerprint:str
    design:dict
    attachment:dict
    contract:dict
    parameters:dict
    cancel:BudgetCancel


def unknown_result(status,code,message,counts=None):
    return {'ok':False,'status':status,'scope':'readonly declared virtual mean-motor scenario','actual_rpm':None,'actual_current_a':None,
            'actual_encoder_counts':None,'scenario':None,'physical_clock_verified':False,'actual_motion_qualified':False,'allow_hardware_motion':False,
            'findings':[{'code':code,'message':message}],'input_counts':counts or {},'code_executed':False,'Document_writes':0}


def safe_result_view(result,language='ko'):
    """Reject invalid worker payloads; never present actual/default0 values."""
    try:
        if any(result[key] is not None for key in ('actual_rpm','actual_current_a','actual_encoder_counts')) or result['allow_hardware_motion'] is not False:
            raise ValueError('The worker returned physical values/permission outside this declared scenario.')
        if result['physical_clock_verified'] is not False or result['actual_motion_qualified'] is not False or result['code_executed'] is not False or result['Document_writes']!=0:
            raise ValueError('The worker returned unsupported execution/physical qualification.')
        if result['ok']:
            if result['status']!='scenario_ready':raise ValueError('Inconsistent scenario status')
            points=result['scenario']['points']
            if not isinstance(points,list) or not 0<len(points)<=4002:raise ValueError('Invalid bounded scenario points')
            previous=-1.
            for row in points:
                for key in ('virtual_time_s','scenario_rpm','scenario_current_a','mean_voltage_v'):
                    value=row[key]
                    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Invalid/nonfinite scenario point')
                if row['virtual_time_s']<previous or row['virtual_time_s']<0:raise ValueError('Invalid virtual point time')
                previous=row['virtual_time_s']
                count=row['scenario_encoder_counts']
                if count is not None and type(count) is not int:raise ValueError('Invalid declared encoder count')
        elif result['scenario'] is not None:raise ValueError('Failed/cancelled result must not retain a curve')
        return drive_review_view_model(result,language)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        return drive_review_view_model(unknown_result('blocked','invalid_worker_result',str(exc)),language)


class ProgramDriveController:
    def __init__(self,document_provider,*,language='ko'):
        self.document_provider=document_provider;self.language=language;self.board_id=None;self.program_key=None
        self.contract=None;self.parameters=None;self.input_errors={};self.generation=0;self.active=None;self.closed=False
        self.result=self.initial_review()
    def current_design(self):return getattr(self.document_provider(),'design',None)
    def counts(self):
        raw=self.current_design() or {};workspace=raw.get('electrical') or {};devices=[c for c in workspace.get('components',[]) if c.get('kind') not in ('wire','switch')]
        return {'registered_devices':sum(bool(c.get('part_registration')) for c in devices),'wires':sum(c.get('kind')=='wire' for c in workspace.get('components',[])),
                'disabled_devices':sum(not c.get('analysis_enabled',True) for c in devices),'program_attachments':len(workspace.get('programs',[]))}
    def initial_review(self):
        return unknown_result('input_missing','not_calculated','보드·저장 코드·계약·모터 입력을 선택하세요. 아직 계산하지 않았습니다. 실제 RPM/clock은 미확인입니다.',self.counts())
    def invalidate(self,message='입력이 바뀌었습니다. 실행 버튼으로 새 검토를 시작하세요.'):
        if self.active:self.active.cancel.set()
        self.active=None;self.generation+=1;self.result=unknown_result('input_missing','inputs_changed',message,self.counts())
    def set_board(self,identifier):
        self.invalidate();self.board_id=identifier or None;self.program_key=None
    def set_program(self,key):self.invalidate();self.program_key=tuple(key) if key else None
    def boards(self):
        return [deepcopy(c) for c in ((self.current_design() or {}).get('electrical') or {}).get('components',[]) if c.get('kind')=='mcu' and c.get('part_registration')]
    def programs(self):
        return [deepcopy(p) for p in ((self.current_design() or {}).get('electrical') or {}).get('programs',[]) if self.board_id and p.get('board_component_id')==self.board_id]
    def load_file(self,kind,path):
        if kind not in ('contract','parameters'):raise ValueError('Unknown input kind')
        self.invalidate()
        try:
            bound=read_input_json(path,kind);setattr(self,kind,bound);self.input_errors.pop(kind,None);return True
        except (ValueError,TypeError,OSError,UnicodeError,RecursionError) as exc:
            setattr(self,kind,None);self.input_errors[kind]=str(exc)[:1600]
            self.result=unknown_result('blocked','invalid_'+kind,self.input_errors[kind],self.counts());return False
    def ready_inputs(self):return not self.closed and bool(self.board_id and self.program_key and self.contract and self.parameters)
    def config_fingerprint(self):
        return fingerprint({'board':self.board_id,'program':self.program_key,
            'contract':None if self.contract is None else {'path':str(self.contract.path),'sha':self.contract.raw_sha256,'payload':self.contract.payload},
            'parameters':None if self.parameters is None else {'path':str(self.parameters.path),'sha':self.parameters.raw_sha256,'payload':self.parameters.payload}})
    def files_still_bound(self):
        for kind in ('contract','parameters'):
            bound=getattr(self,kind)
            if bound is None or read_input_json(bound.path,kind).raw_sha256!=bound.raw_sha256:return False
        return True
    def begin(self):
        if self.closed:return None
        self.invalidate()
        if not self.ready_inputs():
            reasons=['선택 보드와 그 보드에 저장된 코드, exact 계약 JSON과 모터 입력 JSON이 모두 필요합니다.']
            if self.input_errors:reasons.extend(self.input_errors.values())
            self.result=unknown_result('input_missing','missing_explicit_inputs','\n'.join(reasons),self.counts());return None
        try:
            require_design=self.current_design()
            if not isinstance(require_design,dict):raise ValueError('Open a saved CAD design first.')
            matches=[p for p in self.programs() if (p.get('sha256'),p.get('name'),p.get('board_component_id'))==self.program_key]
            if len(matches)!=1:raise ValueError('Selected saved program is missing or ambiguous; choose it again.')
            if self.contract.payload['board_component_id']!=self.board_id or self.contract.payload['source_sha256']!=matches[0]['sha256']:
                raise ValueError('Selected board/program do not match the supplied exact contract.')
            if not self.files_still_bound():raise ValueError('A selected JSON changed since loading; explicitly load it again.')
            doc=self.document_provider();snapshot=deepcopy(require_design)
            ticket=RunTicket(self.generation,id(doc),fingerprint(snapshot),self.config_fingerprint(),snapshot,deepcopy(matches[0]),deepcopy(self.contract.payload),deepcopy(self.parameters.payload),BudgetCancel())
            self.active=ticket;self.result=unknown_result('running','declared_scenario_running','지원된 가상 시나리오를 검토 중입니다. 실제 값은 미확인입니다.',self.counts());return ticket
        except (ValueError,TypeError,KeyError,AttributeError,OSError,RecursionError) as exc:
            self.result=unknown_result('blocked','input_binding_failed',str(exc)[:1600],self.counts());return None
    def complete(self,ticket,result):
        if self.closed or self.active is not ticket or ticket.generation!=self.generation:return False
        self.active=None
        if ticket.cancel.is_set():
            self.result=unknown_result('cancelled','deadline' if ticket.cancel.timed_out else 'cancelled','검토 시간 한도를 넘었습니다.' if ticket.cancel.timed_out else '검토를 취소했습니다.',self.counts());return False
        try:
            current=self.current_design()
            if id(self.document_provider())!=ticket.document_identity or fingerprint(current)!=ticket.design_fingerprint or self.config_fingerprint()!=ticket.config_fingerprint or not self.files_still_bound():
                raise ValueError('설계·배선·코드·계약이 실행 후 바뀌었습니다. 이전 결과를 현재 결과로 표시하지 않습니다.')
        except (ValueError,TypeError,KeyError,AttributeError,OSError,UnicodeError,RecursionError) as exc:
            self.result=unknown_result('stale','stale_inputs',str(exc)[:1600],self.counts());return False
        view=safe_result_view(result,self.language)
        if view['status']=='blocked' and any(row.get('code')=='invalid_worker_result' for row in view['missing_or_blocking_reasons']):
            self.result=unknown_result('blocked','invalid_worker_result','잘못된 결과입니다. 파형과 실제 값을 표시하지 않습니다.',self.counts());return False
        if result.get('ok'):
            envelope=result.get('trace_envelope') or {}
            if envelope.get('source_sha256')!=ticket.attachment['sha256'] or envelope.get('workspace_sha256')!=ticket.contract['workspace_sha256'] or envelope.get('producer_source_sha256')!=ticket.contract['producer_source_sha256'] or result.get('parameter_record_sha256')!=ticket.contract['parameter_record_sha256'] or result.get('driver_profile')!=ticket.contract['driver_profile']:
                self.result=unknown_result('blocked','worker_binding_mismatch','이 결과는 선택한 소스·배선·모터 입력 계약과 연결되지 않습니다.',self.counts());return False
        self.result=deepcopy(result);return True
    def failed(self,ticket,message):return self.complete(ticket,unknown_result('blocked','worker_failed',message,self.counts()))
    def cancel(self):
        self.invalidate();self.result=unknown_result('cancelled','cancelled','검토를 취소했습니다. 설계·회로·코드는 변경하지 않았습니다.',self.counts())
    def close(self):self.cancel();self.closed=True
    def view(self):return safe_result_view(self.result,self.language)
