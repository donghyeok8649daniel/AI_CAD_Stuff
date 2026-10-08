"""Safe source-to-GPIO trace projection through the saved wiring graph.

This intentionally is not firmware/OS emulation. A strict source subset is
interpreted as GPIO actions; arbitrary code, callbacks and hardware reads are
rejected rather than evaluated. No physical motor/current/thermal constants
are guessed. Wiring and exact manufacturer pin identity define every target.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
import math
import operator
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .board_pins import board_pinout
from .electrical import ElectricalWorkspace
from .mcu_connections import connection_endpoints, pin_aliases
from .program_attachment import ProgramAttachment

MAX_ACTIONS = 20_000
MAX_EVENTS = 2_000


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ProgramIssue(_Model):
    severity: Literal['error', 'warning', 'pending']
    code: str
    message: str


class ProgramEvent(_Model):
    time_s: float
    pin: str
    duty: float = Field(ge=0, le=1)
    frequency_hz: float | None = None
    logic_voltage_v: float
    node: str | None = None
    targets: list[str] = Field(default_factory=list)


class ProgramSimulationResult(_Model):
    status: Literal['ready', 'blocked', 'fault', 'cancelled']
    attachment_sha256: str
    board_component_id: str = ''
    events: list[ProgramEvent] = Field(default_factory=list)
    issues: list[ProgramIssue] = Field(default_factory=list)
    duration_s: float = 0
    complete_program: Literal[False] = False
    scope: str = 'GPIO/PWM command trace and wiring connectivity; no firmware/OS, motor or thermal emulation.'


@dataclass(frozen=True)
class _Action:
    kind: str
    pin: str = ''
    value: float = 0
    frequency: float | None = None


@dataclass
class _Plan:
    setup: list[_Action] = field(default_factory=list)
    cycle: list[_Action] = field(default_factory=list)
    numbering: str = 'BCM'


class UnsupportedProgram(ValueError):
    pass


_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.BitOr: operator.or_, ast.BitAnd: operator.and_}
_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}


def _name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return _name(node.value) + '.' + node.attr
    raise UnsupportedProgram('동적으로 계산한 함수·객체는 지원하지 않습니다.')


def _value(node, env, depth=0):
    if depth > 32: raise UnsupportedProgram('식이 너무 복잡합니다.')
    if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int, float)):
        value = node.value
    elif isinstance(node, (ast.Name, ast.Attribute)):
        key = _name(node)
        if key not in env: raise UnsupportedProgram('상수 또는 지원된 핀 이름이 아닙니다: ' + key)
        value = env[key]
    elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        value = _BINARY[type(node.op)](_value(node.left, env, depth + 1), _value(node.right, env, depth + 1))
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not, ast.Invert)):
        raw = _value(node.operand, env, depth + 1)
        value = -raw if isinstance(node.op, ast.USub) else (+raw if isinstance(node.op, ast.UAdd) else (not raw if isinstance(node.op, ast.Not) else ~raw))
    elif isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARE:
        value = _COMPARE[type(node.ops[0])](_value(node.left, env, depth + 1), _value(node.comparators[0], env, depth + 1))
    else: raise UnsupportedProgram('하드웨어 읽기·동적 식·함수 실행은 지원하지 않습니다.')
    if not isinstance(value, (bool, int, float)) or not math.isfinite(value) or abs(value) > 1e9:
        raise UnsupportedProgram('상수 식 범위를 초과했습니다.')
    return value


def _expr(text, env):
    try: return _value(ast.parse(text, mode='eval').body, env)
    except (SyntaxError, ZeroDivisionError, TypeError, OverflowError, RecursionError) as exc:
        raise UnsupportedProgram('지원되지 않는 상수 식: ' + text[:100]) from exc


def _pin(value, prefix=''):
    if isinstance(value, str): return value
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 200:
        raise UnsupportedProgram('핀 번호는 정수 상수여야 합니다.')
    return prefix + str(value)


def _delay(value):
    if not math.isfinite(value) or not 0 <= value <= 60:
        raise UnsupportedProgram('지연은 0~60초 이내 상수여야 합니다.')
    return _Action('delay', value=value)


def _python_plan(source):
    try: tree = ast.parse(source)
    except (SyntaxError, RecursionError) as exc: raise UnsupportedProgram('Python 소스 구문을 확인하세요.') from exc
    if sum(1 for _ in ast.walk(tree)) > 15_000: raise UnsupportedProgram('소스 구문 수가 너무 많습니다.')
    plan = _Plan()
    env = {'True': True, 'False': False}
    gpio_names = set(); time_names = set(); sleep_names = set(); gpiozero_names = {}; devices = {}; pwm = {}
    compile_steps = 0
    gpio_numbering = None

    def call(node, actions):
        nonlocal gpio_numbering
        name = _name(node.func)
        if node.keywords: raise UnsupportedProgram('지원 호출에는 키워드 인수를 사용하지 마세요: ' + name)
        args = [_value(argument, env) for argument in node.args]
        if name in {alias + '.sleep' for alias in time_names} or name in sleep_names:
            if len(args) != 1: raise UnsupportedProgram('sleep 인수를 확인하세요.')
            actions.append(_delay(args[0])); return
        prefix, _, operation = name.rpartition('.')
        if prefix in gpio_names:
            if operation == 'setmode' and len(args) == 1:
                if args[0] not in (10, 11): raise UnsupportedProgram('GPIO 번호 방식은 BCM 또는 BOARD입니다.')
                if gpio_numbering is not None and gpio_numbering != args[0]: raise UnsupportedProgram('RPi.GPIO 번호 방식은 프로그램 중간에 변경할 수 없습니다.')
                if devices and args[0] == 10: raise UnsupportedProgram('gpiozero BCM 번호와 RPi.GPIO BOARD 번호를 혼합하지 않습니다.')
                gpio_numbering = args[0]
                plan.numbering = 'BOARD' if args[0] == 10 else 'BCM'; return
            if operation == 'setwarnings' and len(args) == 1: return
            if gpio_numbering is None: raise UnsupportedProgram('RPi.GPIO 호출 전에 setmode(GPIO.BCM 또는 GPIO.BOARD)를 지정하세요.')
            if operation == 'setup' and len(args) == 2:
                if args[1] != 0: raise UnsupportedProgram('GPIO 입력은 외부 입력 추적이 필요합니다. 임의 입력값을 만들지 않습니다.')
                actions.append(_Action('mode', _pin(args[0]), 1)); return
            if operation == 'output' and len(args) == 2:
                if args[1] not in (0, 1): raise UnsupportedProgram('GPIO 출력은 0 또는 1입니다.')
                actions.append(_Action('output', _pin(args[0]), args[1])); return
            if operation == 'cleanup' and not args:
                actions.append(_Action('cleanup')); return
            raise UnsupportedProgram('지원하지 않는 GPIO 호출: ' + name)
        if prefix in devices:
            if operation in ('on', 'off') and not args:
                actions.append(_Action('output', devices[prefix][0], 1 if operation == 'on' else 0)); return
        if prefix in pwm:
            if operation in ('start', 'ChangeDutyCycle') and len(args) == 1 and 0 <= args[0] <= 100:
                pin, freq = pwm[prefix]; actions.append(_Action('pwm_start' if operation == 'start' else 'pwm_duty', pin, args[0] / 100, freq)); return
            if operation == 'stop' and not args:
                pin, freq = pwm[prefix]; actions.append(_Action('pwm_stop', pin, 0, freq)); return
        raise UnsupportedProgram('지원하지 않는 호출: ' + name + ' (소스는 실행하지 않습니다.)')

    def body(statements, actions, allow_cycle=True):
        nonlocal compile_steps
        for index, statement in enumerate(statements):
            compile_steps += 1
            if compile_steps > MAX_ACTIONS: raise UnsupportedProgram('정적 반복의 처리 명령 수가 너무 많습니다.')
            if len(actions) > MAX_ACTIONS: raise UnsupportedProgram('명령 수가 너무 많습니다.')
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    if alias.name == 'RPi.GPIO':
                        key = alias.asname or 'RPi.GPIO'; gpio_names.add(key)
                        env.update({key + '.' + key2: val for key2, val in {'BCM':11, 'BOARD':10, 'OUT':0, 'IN':1, 'HIGH':1, 'LOW':0}.items()})
                    elif alias.name == 'time': time_names.add(alias.asname or 'time')
                    else: raise UnsupportedProgram('지원하지 않는 import: ' + alias.name)
            elif isinstance(statement, ast.ImportFrom):
                for alias in statement.names:
                    key = alias.asname or alias.name
                    if statement.module == 'time' and alias.name == 'sleep': sleep_names.add(key)
                    elif statement.module == 'gpiozero' and alias.name in ('LED', 'PWMLED', 'OutputDevice'):
                        gpiozero_names[key] = alias.name
                    else: raise UnsupportedProgram('지원하지 않는 import-from. GPIO·시간 명령만 처리합니다.')
            elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
                if isinstance(target, ast.Name) and isinstance(statement.value, ast.Call):
                    name = _name(statement.value.func)
                    args = [_value(arg, env) for arg in statement.value.args]
                    if statement.value.keywords: raise UnsupportedProgram('장치 생성의 추가 설정은 지원하지 않습니다.')
                    if name in gpiozero_names and len(args) == 1:
                        if plan.numbering == 'BOARD': raise UnsupportedProgram('gpiozero BCM 번호와 RPi.GPIO BOARD 번호를 혼합하지 않습니다.')
                        devices[target.id] = (_pin(args[0]), gpiozero_names[name]); actions.append(_Action('mode', devices[target.id][0], 1))
                    elif name in {alias + '.PWM' for alias in gpio_names} and len(args) == 2 and 0 < args[1] <= 1e6:
                        if gpio_numbering is None: raise UnsupportedProgram('RPi.GPIO PWM 생성 전에 setmode를 지정하세요.')
                        if any(pin == _pin(args[0]) for pin, frequency in pwm.values()): raise UnsupportedProgram('같은 GPIO의 중복 PWM 객체는 지원하지 않습니다.')
                        pwm[target.id] = (_pin(args[0]), args[1])
                    else: raise UnsupportedProgram('지원하지 않는 장치·함수 대입: ' + name)
                elif isinstance(target, ast.Name): env[target.id] = _value(statement.value, env)
                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id in devices and target.attr == 'value':
                    duty = _value(statement.value, env)
                    if not 0 <= duty <= 1: raise UnsupportedProgram('PWM duty는 0~1입니다.')
                    device_pin, device_kind = devices[target.value.id]
                    if device_kind != 'PWMLED' and duty not in (0, 1): raise UnsupportedProgram('디지털 gpiozero 장치의 value는 0 또는 1입니다.')
                    actions.append(_Action('output', device_pin, duty))
                else: raise UnsupportedProgram('지원하지 않는 대입문입니다.')
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call): call(statement.value, actions)
            elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str): pass
            elif isinstance(statement, ast.While) and allow_cycle:
                if not isinstance(statement.test, ast.Constant) or statement.test.value is not True or statement.orelse or index != len(statements) - 1:
                    raise UnsupportedProgram('반복은 파일 마지막 while True 블록만 지원합니다. 동적 분기는 입력 모델이 필요합니다.')
                body(statement.body, plan.cycle, False)
            elif isinstance(statement, ast.For) and isinstance(statement.target, ast.Name) and isinstance(statement.iter, ast.Call) and _name(statement.iter.func) == 'range' and not statement.orelse:
                args = [_value(arg, env) for arg in statement.iter.args]
                if not 1 <= len(args) <= 3 or any(type(arg) is not int for arg in args): raise UnsupportedProgram('range는 정수 상수로 지정하세요.')
                try: values = range(*args)
                except (TypeError, ValueError) as exc: raise UnsupportedProgram('range 인수를 확인하세요.') from exc
                if len(values) > 1000: raise UnsupportedProgram('정적 range 반복은 1000회 이내입니다.')
                for val in values: env[statement.target.id] = val; body(statement.body, actions, False)
            elif isinstance(statement, ast.If):
                body(statement.body if _value(statement.test, env) else statement.orelse, actions, False)
            elif isinstance(statement, ast.Pass): pass
            else: raise UnsupportedProgram('지원하지 않는 Python 구문: ' + type(statement).__name__)
    body(tree.body, plan.setup)
    return plan


def _c_plan(source, language):
    # Remove comments and include-only directives, never load header files.
    source = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
    env = {'HIGH':1, 'LOW':0, 'OUTPUT':1, 'INPUT':0, 'GPIO_PIN_SET':1, 'GPIO_PIN_RESET':0}
    env.update({f'A{i}':100+i for i in range(16)})
    for key, expression in re.findall(r'^\s*#define\s+(\w+)\s+([^\n]+)', source, re.M): env[key] = _expr(expression, env)
    source = re.sub(r'^\s*#(?:define|include)\b[^\n]*', '', source, flags=re.M)
    functions = {}; consumed = []
    for match in re.finditer(r'\b(?:void|int)\s+(setup|loop|main)\s*\(\s*(?:void)?\s*\)\s*\{', source):
        start = match.end(); depth = 1; end = start
        while depth and end < len(source):
            if source[end] == '{': depth += 1
            elif source[end] == '}': depth -= 1
            end += 1
        if depth or match.group(1) in functions: raise UnsupportedProgram('함수 블록을 확인하세요.')
        functions[match.group(1)] = source[start:end-1]; consumed.append((match.start(), end))
    remaining = source
    for start, end in reversed(consumed): remaining = remaining[:start] + ' ' * (end-start) + remaining[end:]
    def declarations(text):
        for item in text.split(';'):
            item = item.strip()
            if not item: continue
            match = re.fullmatch(r'(?:(?:const|static|unsigned)\s+)*(?:int|long|uint8_t|uint16_t|uint32_t|float|double)\s+(\w+)\s*=\s*(.+)', item)
            if not match: raise UnsupportedProgram('지원하지 않는 전역 코드·선언: ' + item[:100])
            env[match.group(1)] = _expr(match.group(2), env)
    declarations(remaining)
    plan = _Plan(numbering='HAL' if language == 'stm32_hal' else 'ARDUINO')
    def statements(text, actions):
        if '{' in text or '}' in text: raise UnsupportedProgram('C의 동적 분기·중첩 반복·콜백은 지원하지 않습니다.')
        for item in text.split(';'):
            item = item.strip()
            if not item: continue
            declaration = re.fullmatch(r'(?:(?:const|static|unsigned)\s+)*(?:int|long|uint8_t|uint16_t|uint32_t|float|double)\s+(\w+)\s*=\s*(.+)', item)
            if declaration: env[declaration.group(1)] = _expr(declaration.group(2), env); continue
            if item == 'return 0': continue
            match = re.fullmatch(r'(\w+)\s*\((.*)\)', item, re.S)
            if not match: raise UnsupportedProgram('지원하지 않는 C 명령: ' + item[:100])
            name = match.group(1); raw = [part.strip() for part in match.group(2).split(',') if part.strip()]
            if name in ('HAL_GPIO_WritePin', 'HAL_GPIO_TogglePin') and language == 'stm32_hal':
                if len(raw) != (3 if name == 'HAL_GPIO_WritePin' else 2): raise UnsupportedProgram('HAL GPIO 인수를 확인하세요.')
                port = re.fullmatch(r'GPIO([A-K])', raw[0]); number = re.fullmatch(r'GPIO_PIN_(\d{1,2})', raw[1])
                if not port or not number or int(number.group(1)) > 15: raise UnsupportedProgram('HAL 포트와 핀을 상수로 지정하세요.')
                pin = 'P' + port.group(1) + str(int(number.group(1)))
                val = _expr(raw[2], env) if len(raw) == 3 else 0
                if val not in (0, 1): raise UnsupportedProgram('HAL 출력값은 SET/RESET입니다.')
                actions.append(_Action('output' if len(raw) == 3 else 'toggle', pin, val)); continue
            args = [_expr(argument, env) for argument in raw]
            if name in ('delay', 'HAL_Delay') and len(args) == 1: actions.append(_delay(args[0]/1000))
            elif language == 'arduino' and name in ('digitalWrite', 'analogWrite', 'pinMode') and len(args) == 2:
                pin = _pin(args[0]-100, 'A') if args[0] >= 100 else _pin(args[0], 'D')
                if name == 'pinMode':
                    if args[1] != 1: raise UnsupportedProgram('입력 핀은 외부 입력 추적이 필요합니다.')
                    actions.append(_Action('mode', pin, 1))
                else:
                    maximum = 255 if name == 'analogWrite' else 1
                    if not 0 <= args[1] <= maximum: raise UnsupportedProgram('출력 범위를 확인하세요.')
                    actions.append(_Action('output', pin, args[1]/maximum))
            else: raise UnsupportedProgram('지원하지 않는 C 호출: ' + name)
    if language == 'arduino':
        if set(functions) != {'setup', 'loop'}: raise UnsupportedProgram('Arduino는 setup()/loop() 두 함수가 필요합니다.')
        statements(functions['setup'], plan.setup); statements(functions['loop'], plan.cycle)
    else:
        if set(functions) != {'main'}: raise UnsupportedProgram('STM32 GPIO 추적은 단일 main(void) 소스 블록을 사용하세요.')
        match = re.fullmatch(r'(.*?)\bwhile\s*\(\s*(?:1|true)\s*\)\s*\{(.*?)\}\s*(?:return\s+0\s*;)?\s*', functions['main'], re.S)
        if not match: raise UnsupportedProgram('HAL main의 마지막 while(1) GPIO/지연 블록을 확인하세요.')
        statements(match.group(1), plan.setup); statements(match.group(2), plan.cycle)
    return plan


def _compile(attachment):
    plan = _python_plan(attachment.source) if attachment.language == 'raspberry_python' else _c_plan(attachment.source, attachment.language)
    if len(plan.setup) + len(plan.cycle) > MAX_ACTIONS: raise UnsupportedProgram('프로그램 명령 수가 너무 많습니다.')
    if not any(action.kind in ('output', 'toggle', 'pwm_start', 'pwm_duty', 'pwm_stop') for action in plan.setup + plan.cycle):
        raise UnsupportedProgram('지원되는 GPIO/PWM 출력 명령이 없습니다.')
    if plan.cycle and not any(action.kind == 'delay' and action.value > 0 for action in plan.cycle):
        raise UnsupportedProgram('무한 반복에는 양수 지연이 필요합니다. 실제 CPU 실행 속도를 추정하지 않습니다.')
    return plan


def _resolve_pin(board, raw, numbering):
    if numbering == 'BCM': key = 'GPIO' + raw
    elif numbering == 'BOARD':
        pin = next((pin for pin in board.pins if pin.label.startswith('J8.' + raw + ' ·')), None)
        key = pin.key if pin else ''
    elif numbering == 'HAL':
        matching = [pin for pin in board.pins if pin.kind == 'signal' and (pin.key == raw or raw in pin.functions)]
        if len(matching) != 1: raise UnsupportedProgram('HAL GPIO에 대응하는 실제 헤더 핀이 유일하지 않습니다: ' + raw)
        key = matching[0].key
    else: key = raw
    pin = next((pin for pin in board.pins if pin.key == key and pin.kind == 'signal'), None)
    if pin is None: raise UnsupportedProgram('이 보드의 실제 신호 핀에 없는 코드 핀: ' + raw)
    return pin


def _network(workspace):
    adjacency = defaultdict(set)
    for item in workspace.components:
        if item.kind in ('wire', 'switch') and item.closed:
            adjacency[item.a].add(item.b); adjacency[item.b].add(item.a)
    def reachable(node):
        if node is None: return set()
        seen = {node}; pending = [node]
        while pending:
            for neighbor in adjacency[pending.pop()]:
                if neighbor not in seen: seen.add(neighbor); pending.append(neighbor)
        return seen
    return reachable


def simulate_program(raw, attachment: ProgramAttachment | dict, *, duration_s=10.0, cancel_event=None,
                     selected_component_id='') -> ProgramSimulationResult:
    """No manual mapping: source family and exact pins resolve one saved board.

    Board ambiguity remains visible rather than guessing which real device the
    user intended. Only independent GPIO commands are projected; unknown code
    rejects the whole projection, not merely the unsupported lines.
    """
    attachment = ProgramAttachment.model_validate(attachment)
    workspace = ElectricalWorkspace.model_validate(raw.model_dump() if hasattr(raw, 'model_dump') else raw)
    result = ProgramSimulationResult(status='blocked', attachment_sha256=attachment.sha256)
    def issue(severity, code, message):
        if not any(item.code == code and item.message == message for item in result.issues):
            result.issues.append(ProgramIssue(severity=severity, code=code, message=message))
    if not math.isfinite(duration_s) or not 0 < duration_s <= 60:
        raise ValueError('추적 시간은 0~60초 범위입니다.')
    try:
        plan = _compile(attachment)
        referenced = {action.pin for action in plan.setup + plan.cycle if action.pin}
        candidates = []
        for item in workspace.components:
            board = board_pinout(item.catalog_id)
            if item.kind != 'mcu' or board is None or item.pinout_catalog_id != item.catalog_id: continue
            family = item.catalog_id.lower()
            compatible = ((attachment.language == 'arduino' and 'arduino' in family)
                or (attachment.language == 'raspberry_python' and 'rpi' in family and any(pin.key == 'GPIO17' for pin in board.pins))
                or (attachment.language == 'stm32_hal' and any(pin.key.startswith('PA') or any(re.fullmatch(r'P[A-K]\d{1,2}', function) for function in pin.functions) for pin in board.pins)))
            if not compatible: continue
            try:
                for pin in referenced: _resolve_pin(board, pin, plan.numbering)
            except UnsupportedProgram: continue
            candidates.append((item, board))
        chosen = attachment.board_component_id or selected_component_id
        if chosen: candidates = [pair for pair in candidates if pair[0].id == chosen]
        if len(candidates) != 1:
            raise UnsupportedProgram('소스에 맞는 정확한 보드가 ' + str(len(candidates)) + '개입니다. 전장에 정확한 모델·핀맵을 등록하고 대상 보드를 하나 선택하세요.')
        component, board = candidates[0]; result.board_component_id = component.id
        reach = _network(workspace); endpoints = connection_endpoints(workspace)
        # A/B are the existing explicit board supply model. Physical pads, if
        # supplied, must also agree; no GPIO is silently turned into a rail.
        sources = [item for item in workspace.components if item.kind == 'battery' and item.closed and item.voltage_v > 0]
        if not any(source.a in reach(component.a) and source.b in reach(component.b) for source in sources):
            raise UnsupportedProgram('대상 보드의 전원·GND가 실제 배터리/전원 경로에 연결되지 않았습니다.')
        if not component.board_supply_pins:
            issue('pending', 'physical_supply_pads', '보드 A/B 전원 경로만 확인했습니다. 실제 전원 헤더·USB·레귤레이터 결선은 등록되지 않았습니다.')
        else:
            for key, node in component.board_supply_pins.items():
                physical = next(pin for pin in board.pins if pin.key == key)
                if physical.kind == 'ground' and component.b not in reach(node):
                    raise UnsupportedProgram('보드의 물리 GND 핀이 전원 반환 경로와 연결되지 않았습니다.')
        if board.logic_voltage_v is None: raise UnsupportedProgram('이 보드의 논리 전압 자료가 없습니다.')
        if attachment.language == 'stm32_hal':
            issue('pending', 'hal_initialization', 'HAL GPIO 명령만 추적합니다. 클록·GPIO 초기화·인터럽트·타이머·실제 펌웨어 실행은 검증하지 않습니다.')
        if any(action.frequency is None and 0 < action.value < 1 for action in plan.setup + plan.cycle if action.kind == 'output'):
            issue('pending', 'pwm_frequency', 'PWM duty 명령은 추적하지만 설정되지 않은 PWM 주파수·스위칭 파형은 추정하지 않습니다.')
        modes = set(); states = {}; pwm_started = set(); t = 0.0; actions_used = 0; fault = False
        def process(actions):
            nonlocal t, actions_used, fault
            for action in actions:
                if cancel_event is not None and cancel_event.is_set(): result.status = 'cancelled'; return False
                actions_used += 1
                if actions_used > MAX_ACTIONS or len(result.events) >= MAX_EVENTS:
                    issue('warning', 'trace_limit', '추적 데이터 한도에 도달했습니다. 현재까지의 명령만 표시합니다.'); return False
                if action.kind == 'delay': t += action.value; continue
                if t > duration_s: return False
                if action.kind == 'cleanup':
                    modes.clear(); states.clear(); pwm_started.clear()
                    issue('pending', 'released_gpio', 'GPIO cleanup 이후 핀은 출력 구동을 해제합니다. 부동 입력의 전압·안전 정지를 LOW로 가정하지 않습니다.')
                    continue
                pin = _resolve_pin(board, action.pin, plan.numbering)
                if action.kind == 'mode': modes.add(pin.key); continue
                if attachment.language != 'stm32_hal' and pin.key not in modes:
                    raise UnsupportedProgram('출력 모드 선언이 없는 GPIO: ' + pin.key)
                if action.kind == 'pwm_start': pwm_started.add(pin.key)
                elif action.kind == 'pwm_duty' and pin.key not in pwm_started:
                    raise UnsupportedProgram('PWM start 이전 또는 stop 이후의 duty 변경은 추적할 수 없습니다: ' + pin.key)
                elif action.kind == 'pwm_stop': pwm_started.discard(pin.key)
                if action.kind == 'toggle' and pin.key not in states:
                    raise UnsupportedProgram('초기 출력값이 알려지지 않은 HAL TogglePin은 추적할 수 없습니다: ' + pin.key)
                duty = (0 if states.get(pin.key, 0) else 1) if action.kind == 'toggle' else action.value
                if attachment.language == 'arduino' and 0 < duty < 1 and 'PWM' not in pin.functions:
                    raise UnsupportedProgram('이 Arduino 헤더는 PWM 출력 핀이 아닙니다: ' + pin.key)
                aliases = pin_aliases(component, pin.key)
                node = next((component.signal_pins[key] for key in aliases if key in component.signal_pins), None)
                if node is None: raise UnsupportedProgram('코드 출력 핀이 배선도에 연결되지 않았습니다: ' + pin.key)
                nodes = reach(node)
                receiver_ids = {item.id for item in workspace.components if item.kind != 'wire'}
                targets = [ep for ep in endpoints if ep.component_id != component.id and ep.component_id in receiver_ids and ep.node in nodes]
                if not targets: raise UnsupportedProgram('코드 출력 핀에 연결된 실제 수신 단자가 없습니다: ' + pin.key)
                if duty > 0 and ('GND' in nodes or component.b in nodes or any(source.b in nodes for source in sources)):
                    fault = True; issue('error', 'gpio_ground_short', pin.key + '의 HIGH/PWM 출력이 GND에 연결됩니다.')
                if any(source.a in nodes for source in sources):
                    fault = True; issue('error', 'gpio_supply_drive', pin.key + '이 배터리·외부 전원 출력과 직접 연결됩니다. GPIO를 전원 레일로 사용할 수 없습니다.')
                for previous, previous_duty in states.items():
                    previous_node = next((component.signal_pins[key] for key in pin_aliases(component, previous) if key in component.signal_pins), None)
                    if previous != pin.key and previous_node in nodes and abs(previous_duty-duty) > 1e-9:
                        fault = True; issue('error', 'gpio_contention', previous + '와 ' + pin.key + '가 같은 배선에서 다른 출력값을 구동합니다.')
                for target in targets:
                    receiver = next(item for item in workspace.components if item.id == target.component_id)
                    if receiver.kind in ('motor', 'actuator') and target.terminal in ('a', 'b'):
                        fault = True; issue('error', 'gpio_motor_power', pin.key + '이 모터 전력 단자에 직접 연결됩니다. 실제 드라이버의 제어 핀을 연결하세요.')
                    receiver_board = board_pinout(receiver.catalog_id)
                    if target.terminal.startswith('pin:') and receiver_board and receiver_board.logic_voltage_v is not None and board.logic_voltage_v > receiver_board.logic_voltage_v + .1:
                        fault = True; issue('error', 'logic_voltage', pin.key + ' 출력 논리 전압이 수신 보드의 논리 전압보다 높습니다. 핀별 허용 입력은 별도 확인하세요.')
                states[pin.key] = duty
                result.events.append(ProgramEvent(time_s=t, pin=pin.key, duty=duty, frequency_hz=action.frequency,
                    logic_voltage_v=board.logic_voltage_v, node=node,
                    targets=[target.component_id + '/' + target.terminal for target in targets]))
            return True
        keep = process(plan.setup)
        while keep and plan.cycle and t <= duration_s: keep = process(plan.cycle)
        result.duration_s = min(t, duration_s)
        if result.status != 'cancelled': result.status = 'fault' if fault else 'ready'
        issue('pending', 'physical_behavior', '배선 기반 GPIO/PWM 명령 추적입니다. MCU 실행 타이밍·입력 센서·모터 속도·실제 전류·과열·OS 동작은 이 코드 추적으로 검증하지 않습니다.')
    except (UnsupportedProgram, SyntaxError, ValueError, TypeError, RecursionError) as exc:
        result.status = 'blocked'; result.events.clear(); issue('error', 'unsupported_or_unwired', str(exc)[:1200])
    return result
