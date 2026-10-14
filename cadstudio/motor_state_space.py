"""Read-only state-space description of the existing averaged DC plant.

No time integration, imported source execution, file reads or CAD changes.
Numeric coefficients require the complete existing ParameterRecord contract.
"""
from copy import deepcopy
from math import isfinite, pi


STATE_NAMES = ('current_a', 'omega_rad_s', 'angle_rad')
STATE_UNITS = ('A', 'rad/s', 'rad')
INPUT_NAMES = ('mean_voltage_v', 'load_torque_nm')
INPUT_UNITS = ('V', 'N*m')
OUTPUT_NAMES = ('rpm', 'current_a', 'angle_rad')
OUTPUT_UNITS = ('rev/min', 'A', 'rad')
SYMBOLIC = {
    'A': [['-R/L', '-Ke/L', '0'], ['Kt/J', '-b/J', '0'], ['0', '1', '0']],
    'B': [['1/L', '0'], ['0', '-1/J'], ['0', '0']],
    'C': [['0', '60/(2*pi)', '0'], ['1', '0', '0'], ['0', '0', '1']],
    'D': [['0', '0'], ['0', '0'], ['0', '0']],
}
SYMBOL_PARAMETERS = {
    'R': 'resistance_ohm', 'L': 'inductance_h',
    'Kt': 'torque_constant_nm_per_a', 'Ke': 'back_emf_v_per_rad_s',
    'J': 'inertia_kg_m2', 'b': 'viscous_friction_nm_per_rad_s',
}
SCOPE = ('declared_linear_averaged_dc_plant_algebra_only_not_simulation_or_physical_measurement')


def validated_record(value):
    """Revalidate supplied in-memory input, including mutable BoundJSON payloads.

    No path is opened, and BoundJSON metadata is not treated as a fresh file
    verification. Even ParameterRecord instances are revalidated after dump.
    """
    from .program_drive_adapter import ParameterRecord, fingerprint
    from .native.program_drive_controller import BoundJSON, MAX_JSON_BYTES
    binding = None
    if isinstance(value, BoundJSON):
        if (type(value.bytes) is not int or not 0 < value.bytes <= MAX_JSON_BYTES
                or not isinstance(value.raw_sha256, str) or len(value.raw_sha256) != 64
                or any(c not in '0123456789abcdef' for c in value.raw_sha256)):
            raise ValueError('invalid_bound_parameter_metadata')
        payload = deepcopy(value.payload)
        binding = {'raw_sha256': value.raw_sha256, 'bytes': value.bytes,
                   'file_rechecked': False}
    elif isinstance(value, ParameterRecord):
        payload = value.model_dump(mode='python')
    elif type(value) is dict:
        payload = deepcopy(value)
    else:
        raise ValueError('supply_ParameterRecord_payload_or_BoundJSON_not_a_path')
    if type(payload) is not dict:
        raise ValueError('parameter_record_root_must_be_an_object')
    record = ParameterRecord.model_validate(payload)
    return record, fingerprint(payload), binding


def state_space_report(parameter_record=None):
    """Return symbolic matrices without inputs, or finite declared coefficients.

    u=[mean voltage V, opposing load torque N*m]. x=[i A, omega rad/s,
    theta rad]. y=[rpm, i A, theta rad]. No Kv conversion or defaults.
    """
    from .program_drive_adapter import UNITS, INITIAL_UNITS
    result = {
        'schema_version': 1, 'scope': SCOPE,
        'equations': ['dx/dt = A*x + B*u', 'y = C*x + D*u'],
        'state_names': list(STATE_NAMES), 'state_units': list(STATE_UNITS),
        'input_names': list(INPUT_NAMES), 'input_units': list(INPUT_UNITS),
        'output_names': list(OUTPUT_NAMES), 'output_units': list(OUTPUT_UNITS),
        'symbolic': deepcopy(SYMBOLIC), 'symbol_parameters': dict(SYMBOL_PARAMETERS),
        'numeric': None, 'parameter_record': None,
        'missing_parameters': list(UNITS), 'missing_initial_state': list(INITIAL_UNITS),
        'scenario_rpm': None, 'actual_rpm': None, 'actual_current_a': None,
        'time_integration_performed': False, 'code_executed': False,
        'physical_clock_verified': False, 'actual_motion_qualified': False,
        'allow_hardware_motion': False, 'Document_writes': 0,
    }
    if parameter_record is None:
        return result
    record, payload_sha, binding = validated_record(parameter_record)
    values = {key: row.value for key, row in record.values.items()}
    r, l, kt, ke, j, b = (values[SYMBOL_PARAMETERS[k]] for k in ('R', 'L', 'Kt', 'Ke', 'J', 'b'))
    matrices = {
        'A': [[-r/l, -ke/l, 0.], [kt/j, -b/j, 0.], [0., 1., 0.]],
        'B': [[1./l, 0.], [0., -1./j], [0., 0.]],
        'C': [[0., 60./(2.*pi), 0.], [1., 0., 0.], [0., 0., 1.]],
        'D': [[0., 0.], [0., 0.], [0., 0.]],
    }
    if any(not isfinite(cell) for matrix in matrices.values() for row in matrix for cell in row):
        raise ValueError('nonfinite_derived_motor_coefficient')
    result.update(numeric=matrices, missing_parameters=[], missing_initial_state=[],
                  parameter_record={
                      'record_id': record.record_id, 'qualification': record.qualification,
                      'evidence_reference': record.evidence_reference,
                      'motor_part_id': record.motor_part_id, 'shaft_reference': record.shaft_reference,
                      'motor_type': record.motor_type, 'payload_sha256': payload_sha,
                      'bound_input': binding,
                      'values': {key: row.model_dump() for key, row in record.values.items()},
                      'initial_state': {key: row.model_dump() for key, row in record.initial_state.items()},
                      'assumptions': record.assumptions,
                  })
    return result


def report_text(report, language='ko'):
    """Plain text presentation; coefficients are derived, never measured RPM."""
    english = language == 'en'
    text = [
        'Averaged DC motor state-space model' if english else 'DC 평균 모터 상태공간 모델',
        'dx/dt = A*x + B*u; y = C*x + D*u',
        'x = [i (A), omega (rad/s), theta (rad)]',
        'u = [mean voltage (V), opposing load torque (N*m)]',
        'y = [speed (rev/min), current (A), angle (rad)]',
        '',
    ]
    for key, rows in report['symbolic'].items():
        text += [key + ' (symbolic)' if english else key + ' (기호식)']
        text += ['[ ' + '    '.join(row) + ' ]' for row in rows]
        numeric = report['numeric']
        if numeric is not None:
            text += [key + ' (declared coefficients)' if english else key + ' (선언 입력의 계수)']
            text += ['[ ' + '    '.join(f'{cell:.9g}' for cell in row) + ' ]' for row in numeric[key]]
        text += ['']
    text += [
        'Coefficient units follow each derivative/state or output/input pair; mixed-unit matrices are not all 1/s.' if english else
        '계수 단위는 각 미분상태/상태 또는 출력/입력의 비에 따릅니다. 혼합 단위 행렬 전체를 1/s로 해석하지 마세요.',
        'R [ohm], L [H], Kt [N*m/A], Ke [V/(rad/s)], J [kg*m^2], b [N*m/(rad/s)].',
        'Positive load torque subtracts from acceleration; its declared record value is not a measured load.' if english else
        '양의 부하 토크는 가속도를 줄입니다. 저장된 부하 토크는 실측 하중으로 간주하지 않습니다.',
        '',
    ]
    record = report['parameter_record']
    if record is None:
        text += [
            'No input record: symbolic only. No numeric motor constants or RPM were guessed.' if english else
            '입력 기록 없음: 기호식만 표시합니다. 모터 상수나 RPM을 추정하지 않았습니다.',
            ('Required record values: ' if english else '필요한 기록 값: ') + ', '.join(report['missing_parameters']),
            ('Required initial state: ' if english else '필요한 초기 상태: ') + ', '.join(report['missing_initial_state']),
            'Supply all existing ParameterRecord fields, exact SI units and evidence; no partial record/defaults.' if english else
            '기존 ParameterRecord의 모든 필드·정확한 SI 단위·출처가 필요합니다. 부분 입력이나 기본값을 채우지 않습니다.',
        ]
    else:
        text += [
            ('Record: ' if english else '기록: ') + record['record_id'],
            ('Qualification: ' if english else '입력 구분: ') + record['qualification'],
            ('Evidence: ' if english else '근거: ') + record['evidence_reference'],
            ('Motor part: ' if english else '모터 부품: ') + record['motor_part_id'],
            ('Shaft reference: ' if english else '축 기준: ') + record['shaft_reference'],
            'Payload SHA-256: ' + record['payload_sha256'],
        ]
        for section in ('values', 'initial_state'):
            for name, row in record[section].items():
                text += [name + ': ' + f"{row['value']:.9g} " + row['unit']]
        if record['bound_input']:
            text += [
                'Chosen JSON raw SHA-256: ' + record['bound_input']['raw_sha256'],
                'File not re-read by this dialog.' if english else '이 창에서는 파일을 다시 읽지 않습니다.',
            ]
    text += ['',
        'Algebra only: no integration, simulated/actual RPM, source execution or CAD changes.' if english else
        '행렬 계수 검토만 합니다. 적분·가상/실제 RPM 계산·코드 실행·CAD 변경을 하지 않습니다.',
        'Ideal stiff voltage at motor terminals; existing declared mean DC assumptions only. No switching, BLDC/ESC/FOC, temperature, firmware/OS or hardware qualification.' if english else
        '모터 단자의 이상적인 강성 전압원과 기존 선언된 DC 평균 가정만 사용합니다. 스위칭·BLDC/ESC/FOC·발열·펌웨어/OS·실장 검증은 포함하지 않습니다.',
        'Actual RPM/current/clock: Unknown. Hardware motion is not permitted.' if english else
        '실제 RPM·전류·시간: 미확인. 실제 장비 구동 권한을 부여하지 않습니다.',
    ]
    return '\n'.join(text)
