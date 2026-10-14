"""Explicit local-build provenance for the source and frozen trace producer.

Source keeps the existing exact .py SHA gate. Frozen uses a signed per-build
verification receipt plus actual EXE/loaded code fingerprints. This is internal
integrity evidence, not Authenticode or physical/control qualification.
"""
import hashlib,json,sys,types
from pathlib import Path

SOURCE_SHA='fc78917683a9eda3e73794829eb50567500eea58f72ea8f71d4b104f84d54cad'
PROFILE='pololu2130_A_slow_decay_explicit_sleep_v1'
ALGORITHM='RSASSA-PKCS1-v1_5-SHA256'
SHA256_DER=bytes.fromhex('3031300d060960864801650304020105000420')
MAX_PROOF_BYTES=32*1024


def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def code_fingerprint(code):
    """Stable code data; filenames/interpreter string interning are excluded."""
    def constant(value):
        if isinstance(value,types.CodeType):return describe(value)
        if value is None or type(value) in (str,int,bool):return [type(value).__name__,value]
        if type(value) is float:return ['float',value.hex()]
        if type(value) is complex:return ['complex',value.real.hex(),value.imag.hex()]
        if type(value) is bytes:return ['bytes',value.hex()]
        if type(value) is tuple:return ['tuple',[constant(v) for v in value]]
        if type(value) is frozenset:return ['frozenset',sorted((constant(v) for v in value),key=lambda v:canonical(v))]
        if value is Ellipsis:return ['ellipsis']
        raise ValueError('Unsupported compiled constant type')
    def describe(c):
        return {'kind':'code','name':c.co_name,'qualname':c.co_qualname,'firstline':c.co_firstlineno,
                'argcount':c.co_argcount,'posonly':c.co_posonlyargcount,'kwonly':c.co_kwonlyargcount,'nlocals':c.co_nlocals,'stack':c.co_stacksize,'flags':c.co_flags,
                'code':c.co_code.hex(),'lines':c.co_linetable.hex(),'exceptions':c.co_exceptiontable.hex(),
                'names':list(c.co_names),'vars':list(c.co_varnames),'free':list(c.co_freevars),'cells':list(c.co_cellvars),'consts':[constant(v) for v in c.co_consts]}
    return hashlib.sha256(canonical(describe(code))).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def strict_proof_bytes(raw):
    if len(raw)>MAX_PROOF_BYTES:raise ValueError('provenance_record_too_large')
    def invalid(v):raise ValueError('nonfinite_provenance_number')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate_provenance_key')
            result[key]=value
        return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid)


def expected_encoding(data,key_bytes):
    digest=SHA256_DER+hashlib.sha256(data).digest();padding=key_bytes-len(digest)-3
    if padding<8:raise ValueError('invalid_RSA_key_size')
    return b'\x00\x01'+b'\xff'*padding+b'\x00'+digest


def validate_signed_proof(record,exe_sha,exe_bytes,module_sha,function_sha):
    from . import program_drive_trust_anchor as anchor
    from . import __build_id__
    if not isinstance(record,dict) or set(record)!= {'schema_version','algorithm','payload','signature_hex'} or type(record['schema_version']) is not int or record['schema_version']!=1 or record['algorithm']!=ALGORITHM:
        raise ValueError('unsupported_provenance_schema')
    payload=record['payload'];signature=record['signature_hex'];n=int(anchor.PUBLIC_MODULUS_HEX,16);k=(n.bit_length()+7)//8
    if not isinstance(signature,str) or len(signature)!=k*2 or any(c not in '0123456789abcdef' for c in signature):raise ValueError('invalid_provenance_signature')
    s=int(signature,16)
    if s>=n or pow(s,anchor.PUBLIC_EXPONENT,n).to_bytes(k,'big')!=expected_encoding(canonical(payload),k):raise ValueError('untrusted_provenance_signature')
    required={'schema_version','build_id','producer_module','producer_source_sha256','producer_module_code_sha256','simulate_function_code_sha256','source_freeze_sha256','executable_sha256','executable_bytes','bundle_verification_sha256','application_modules','driver_profile','source_profiles','contract_schemas','time_basis','duty_unit','scope'}
    if not isinstance(payload,dict) or set(payload)!=required or type(payload['schema_version']) is not int or payload['schema_version']!=1:raise ValueError('invalid_signed_payload_schema')
    for key in ('producer_source_sha256','producer_module_code_sha256','simulate_function_code_sha256','source_freeze_sha256','executable_sha256','bundle_verification_sha256'):
        value=payload[key]
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('missing_or_invalid_provenance_hash')
    if payload['build_id']!=anchor.BUILD_ID or payload['build_id']!=__build_id__:raise ValueError('provenance_build_mismatch')
    if payload['producer_module']!='cadstudio.program_simulation' or payload['producer_source_sha256']!=SOURCE_SHA or payload['producer_source_sha256']!=anchor.PRODUCER_SOURCE_SHA:
        raise ValueError('provenance_source_mismatch')
    if payload['producer_module_code_sha256']!=module_sha or module_sha!=anchor.PRODUCER_MODULE_CODE_SHA or payload['simulate_function_code_sha256']!=function_sha or function_sha!=anchor.SIMULATE_FUNCTION_CODE_SHA:
        raise ValueError('provenance_compiled_code_mismatch')
    if payload['executable_sha256']!=exe_sha or type(payload['executable_bytes']) is not int or payload['executable_bytes']!=exe_bytes:raise ValueError('provenance_executable_mismatch')
    if type(payload['application_modules']) is not int or payload['application_modules']<1:raise ValueError('invalid_provenance_module_count')
    if not isinstance(payload['contract_schemas'],dict) or any(type(v) is not int for v in payload['contract_schemas'].values()):raise ValueError('invalid_provenance_contract_schema_types')
    if payload['driver_profile']!=PROFILE or payload['source_profiles']!=['raspberry_python'] or payload['contract_schemas']!={'drive':1,'parameters':1,'trace':1} or payload['time_basis']!='declared_virtual_seconds' or payload['duty_unit']!='fraction_0_to_1' or payload['scope']!='local_review_build_integrity_only_not_physical_qualification':
        raise ValueError('provenance_profile_schema_mismatch')
    return dict(payload)


def assert_trace_producer(producer,simulate):
    """Called only at explicit scenario execution; no import/startup IO."""
    if getattr(sys,'frozen',False) is not True:
        if file_sha(producer.__file__)!=SOURCE_SHA:raise ValueError('trace_producer_source_changed_or_unavailable')
        return {'mode':'exact_source_file','producer_source_sha256':SOURCE_SHA}
    root=Path(sys._MEIPASS)
    path=root/'cadstudio-program-drive-provenance.json'
    with path.open('rb') as stream:raw=stream.read(MAX_PROOF_BYTES+1)
    record=strict_proof_bytes(raw)
    loader=producer.__loader__
    if producer.__name__!='cadstudio.program_simulation' or not callable(getattr(loader,'get_code',None)) or simulate.__module__!=producer.__name__:raise ValueError('unverified_frozen_producer_loader')
    module=loader.get_code(producer.__name__)
    if not isinstance(module,types.CodeType):raise ValueError('frozen_producer_code_unavailable')
    payload=validate_signed_proof(record,file_sha(sys.executable),Path(sys.executable).stat().st_size,code_fingerprint(module),code_fingerprint(simulate.__code__))
    # The signed verifier receipt binds this entire frozen source snapshot.
    freeze_path=root/'program-drive-source-freeze.json'
    if file_sha(freeze_path)!=payload['source_freeze_sha256']:raise ValueError('signed_source_freeze_missing_or_changed')
    if file_sha(root/'program-drive-bundle-verification.json')!=payload['bundle_verification_sha256']:raise ValueError('signed_bundle_verification_missing_or_changed')
    return {'mode':'verified_frozen_bundle','producer_source_sha256':SOURCE_SHA,'build_id':payload['build_id'],'executable_sha256':payload['executable_sha256'],'source_freeze_sha256':payload['source_freeze_sha256']}
