from __future__ import annotations

from hashlib import sha256
import threading

import pytest

from cadstudio.electrical import ElectricalWorkspace
from cadstudio.program_attachment import attach_source, read_program, ProgramAttachment, MAX_SOURCE_BYTES
from cadstudio.program_simulation import simulate_program


def wiring(catalog='arduino_uno_r3', pin='D9', receiver_kind='load'):
    return ElectricalWorkspace.model_validate({'nodes':['GND','PWR','OUT','DRIVER','MOTOR'], 'components':[
        {'id':'battery','name':'Battery','kind':'battery','a':'PWR','b':'GND','voltage_v':5},
        {'id':'board','name':'Board','kind':'mcu','a':'PWR','b':'GND','catalog_id':catalog,
         'analysis_enabled':False,'pinout_catalog_id':catalog,'signal_pins':{pin:'OUT'}},
        {'id':'driver','name':'Driver','kind':receiver_kind,'a':'MOTOR','b':'GND','analysis_enabled':False,
         'terminal_pins':{'PWM':'DRIVER'}},
        {'id':'cable','name':'Cable','kind':'wire','a':'OUT','b':'DRIVER','analysis_enabled':False,
         'wire_endpoints':[{'component_id':'board','terminal':'pin:'+pin}, {'component_id':'driver','terminal':'port:PWM'}]},
    ]})


ARDUINO = '''const int pwmPin=9;
void setup(){pinMode(pwmPin, OUTPUT);}
void loop(){analogWrite(pwmPin,128); delay(500); digitalWrite(pwmPin,LOW); delay(500);}
'''
RPI = '''import RPi.GPIO as GPIO
import time
GPIO.setmode(GPIO.BCM)
GPIO.setup(17, GPIO.OUT)
while True:
    GPIO.output(17, GPIO.HIGH)
    time.sleep(.5)
    GPIO.output(17, GPIO.LOW)
    time.sleep(.5)
'''


def test_arduino_source_automatically_routes_saved_physical_wire_without_manual_map():
    workspace = wiring(); before = workspace.model_dump()
    result = simulate_program(workspace, attach_source('drive.ino', ARDUINO), duration_s=2)
    assert result.status == 'ready' and result.complete_program is False
    assert result.board_component_id == 'board'
    assert result.events[0].pin == 'D9' and result.events[0].duty == pytest.approx(128/255)
    assert result.events[0].targets == ['driver/port:PWM']
    assert result.events[1].time_s == .5 and result.events[1].duty == 0
    assert workspace.model_dump() == before
    assert {issue.code for issue in result.issues} >= {'physical_behavior','pwm_frequency'}


def test_raspberry_bcm_and_board_numbering_resolve_same_manufacturer_pin():
    workspace = wiring('rpi4b','GPIO17')
    bcm = simulate_program(workspace, attach_source('controller.py', RPI), duration_s=1)
    physical_source = RPI.replace('GPIO.BCM','GPIO.BOARD').replace('(17,','(11,')
    physical = simulate_program(workspace, attach_source('controller.py', physical_source), duration_s=1)
    assert bcm.status == physical.status == 'ready'
    assert bcm.events == physical.events


def test_gpiozero_simple_signal_plan_and_sleep_alias():
    source = '''from gpiozero import LED
from time import sleep as nap
led=LED(17)
while True:
    led.on()
    nap(.1)
    led.off()
    nap(.1)
'''
    result = simulate_program(wiring('rpi3bplus','GPIO17'),attach_source('gpio.py',source),duration_s=.5)
    assert result.status == 'ready' and len(result.events) >= 4


def test_raspberry_pwm_records_explicit_frequency_and_duty():
    source = '''import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setup(17,GPIO.OUT)
pwm=GPIO.PWM(17,1000)
pwm.start(25)
pwm.ChangeDutyCycle(50)
pwm.stop()
'''
    result = simulate_program(wiring('rpi4b','GPIO17'),attach_source('pwm.py',source))
    assert result.status == 'ready'
    assert [event.duty for event in result.events] == [.25,.5,0]
    assert all(event.frequency_hz == 1000 for event in result.events)


def test_non_pwm_arduino_and_digital_gpiozero_never_claim_pwm():
    source=ARDUINO.replace('pwmPin=9','pwmPin=13')
    assert simulate_program(wiring(pin='D13'),attach_source('drive.ino',source)).status=='blocked'
    source='from gpiozero import LED\nled=LED(17)\nled.value=.5\n'
    assert simulate_program(wiring('rpi4b','GPIO17'),attach_source('led.py',source)).status=='blocked'


@pytest.mark.parametrize('tail', [
    '\nimport os\nos.system("anything")', '\nGPIO.input(17)',
    '\nopen("private.txt").read()', '\nexec("print(1)")',
    '\nwhile GPIO.input(17):\n    GPIO.output(17,1)',
])
def test_unsupported_or_arbitrary_source_is_rejected_whole_not_executed(tail):
    simple = 'import RPi.GPIO as GPIO\nGPIO.setmode(GPIO.BCM)\nGPIO.setup(17,GPIO.OUT)\nGPIO.output(17,1)\n'
    result = simulate_program(wiring('rpi4b','GPIO17'),attach_source('unsafe.py',simple+tail))
    assert result.status == 'blocked' and result.events == []


def test_ambiguous_exact_boards_require_selected_target_not_silent_guess():
    workspace = wiring(); data = workspace.model_dump()
    second = dict(data['components'][1],id='board2',name='Second')
    data['components'].append(second)
    ambiguous = simulate_program(data,attach_source('drive.ino',ARDUINO))
    selected = simulate_program(data,attach_source('drive.ino',ARDUINO),selected_component_id='board')
    assert ambiguous.status == 'blocked' and selected.status == 'ready'


def test_unknown_unmapped_pin_open_wire_and_no_power_remain_blocked():
    attachment = attach_source('drive.ino',ARDUINO)
    for modification in ('unknown_pin','unmapped','open_wire','unpowered'):
        data = wiring().model_dump()
        if modification == 'unknown_pin': data['components'][1]['signal_pins'] = {'D8':'OUT'}
        elif modification == 'unmapped': data['components'][1]['signal_pins'] = {}
        elif modification == 'open_wire': data['components'][3]['closed'] = False
        else: data['components'][0]['closed'] = False
        result = simulate_program(data,attachment)
        assert result.status == 'blocked' and not result.events


def test_gpio_high_short_to_ground_flags_fault():
    data = wiring().model_dump(); data['components'][3]['b']='GND'; data['components'][3].pop('wire_endpoints')
    result = simulate_program(data,attach_source('drive.ino',ARDUINO))
    assert result.status == 'fault'
    assert 'gpio_ground_short' in {issue.code for issue in result.issues}


def test_gpio_cannot_power_motor_directly():
    data = wiring(receiver_kind='motor').model_dump()
    data['components'][2]['a']='DRIVER'; data['components'][3]['wire_endpoints'][1]['terminal']='a'
    result = simulate_program(data,attach_source('drive.ino',ARDUINO))
    assert result.status == 'fault' and any(issue.code=='gpio_motor_power' for issue in result.issues)


def test_gpio_contention_is_reported():
    data = wiring().model_dump(); data['components'][1]['signal_pins']['D8']='OUT'
    source='void setup(){pinMode(9,OUTPUT);pinMode(8,OUTPUT);digitalWrite(9,HIGH);digitalWrite(8,LOW);} void loop(){delay(100);}'
    result=simulate_program(data,attach_source('short.ino',source))
    assert result.status == 'fault' and any(issue.code=='gpio_contention' for issue in result.issues)


def test_cancel_and_no_delay_loop_are_bounded():
    event=threading.Event();event.set()
    result=simulate_program(wiring(),attach_source('drive.ino',ARDUINO),cancel_event=event)
    assert result.status=='cancelled' and not result.events
    source='void setup(){pinMode(9,OUTPUT);}void loop(){digitalWrite(9,HIGH);}'
    assert simulate_program(wiring(),attach_source('spin.ino',source)).status=='blocked'


def test_nested_empty_static_loops_are_bounded_before_simulation():
    source='import RPi.GPIO as GPIO\nGPIO.setmode(GPIO.BCM)\nGPIO.setup(17,GPIO.OUT)\nGPIO.output(17,1)\nfor i in range(1000):\n    for j in range(1000):\n        unused=1\n'
    result=simulate_program(wiring('rpi4b','GPIO17'),attach_source('bounded.py',source))
    assert result.status=='blocked' and not result.events


def test_program_source_portable_sha_limits_and_binary_protection(tmp_path):
    attachment=attach_source('설계.ino',ARDUINO)
    assert ProgramAttachment.model_validate(attachment.model_dump())==attachment
    bad=attachment.model_dump();bad['sha256']='0'*64
    with pytest.raises(ValueError):ProgramAttachment.model_validate(bad)
    path=tmp_path/'huge.ino';path.write_bytes(b'x'*(MAX_SOURCE_BYTES+1))
    with pytest.raises(ValueError):read_program(path)
    path=tmp_path/'main.py';path.write_bytes(b'\xff\xfe')
    with pytest.raises(ValueError):read_program(path)
    assert attachment.sha256==sha256(ARDUINO.encode()).hexdigest()


def test_stm32_hal_documented_header_gpio_commands_but_no_fake_full_firmware():
    from cadstudio.board_pins import board_pinout
    board=board_pinout('nucleo_f401re')
    actual=next(pin for pin in board.pins if pin.kind=='signal' and any(function.startswith('PA') for function in pin.functions))
    pin=actual.key
    number=next(function[2:] for function in actual.functions if function.startswith('PA'))
    source=f'int main(void){{while(1){{HAL_GPIO_WritePin(GPIOA,GPIO_PIN_{number},GPIO_PIN_SET);HAL_Delay(50);HAL_GPIO_TogglePin(GPIOA,GPIO_PIN_{number});HAL_Delay(50);}}}}'
    result=simulate_program(wiring('nucleo_f401re',pin),attach_source('main.c',source),duration_s=.25)
    assert result.status=='ready' and result.events[0].pin==pin
    assert any(issue.code=='hal_initialization' for issue in result.issues)
    bad=source.replace('HAL_Delay(50)','HAL_TIM_PWM_Start(&htim1,TIM_CHANNEL_1)',1)
    assert simulate_program(wiring('nucleo_f401re',pin),attach_source('main.c',bad)).status=='blocked'


@pytest.mark.parametrize('source',[
    'import RPi.GPIO as GPIO\nGPIO.setup(17,GPIO.OUT)\nGPIO.output(17,1)',
    'import RPi.GPIO as GPIO\nGPIO.setmode(GPIO.BCM)\nGPIO.setmode(GPIO.BOARD)\nGPIO.setup(11,GPIO.OUT)\nGPIO.output(11,1)',
    'import RPi.GPIO as GPIO\nGPIO.setmode(GPIO.BCM)\nGPIO.setup(17,GPIO.OUT)\npwm=GPIO.PWM(17,1000)\npwm.ChangeDutyCycle(50)',
    'from gpiozero import LED\nled=LED(17)\nled.on()\nled.close()',
])
def test_missing_mode_started_pwm_and_release_semantics_never_guessed(source):
    result=simulate_program(wiring('rpi4b','GPIO17'),attach_source('state.py',source))
    assert result.status=='blocked' and not result.events


def test_pwm_stop_inside_repeating_loop_prevents_false_next_iteration_pass():
    source='''import RPi.GPIO as GPIO
import time
GPIO.setmode(GPIO.BCM)
GPIO.setup(17,GPIO.OUT)
p=GPIO.PWM(17,1000)
p.start(0)
while True:
    p.ChangeDutyCycle(50)
    p.stop()
    time.sleep(.1)
'''
    assert simulate_program(wiring('rpi4b','GPIO17'),attach_source('state.py',source)).status=='blocked'
