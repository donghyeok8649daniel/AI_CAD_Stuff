# 실제 모터 제품 선택과 배선 기준 · v2.22.0

확인일: **2026-10-07**. 카탈로그의 실제 모델 선택을 12개 늘리고, 기존 모델 3개의 외부 단자도를 추가했습니다. 사용자 CAD 형상·프로젝트·배선은 자동 변경하지 않습니다.

전체 전장 목록은 98 → **110개**, CAD 전장 등록 가능한 항목은 55 → **68개**입니다. 등록 가능 항목은 보드 핀맵 11개, 제품 외부 단자도 40개, 수동 단자 입력 제품 17개로 구분합니다. 제품군 탐색 링크 42개에는 임의 핀맵을 만들지 않습니다. **등록 가능은 실제 구동 또는 시뮬레이션 지원을 뜻하지 않습니다.**

## 새로 선택하는 12개 모델

| 제품 | 구분과 선택 기준 | 공식 제품 자료 | 안정적인 카탈로그 ID |
| --- | --- | --- | --- |
| Pololu #4845 | 12 V, 47:1 표기, 25D HP, 모터축 48 CPR | [#4845](https://www.pololu.com/product/4845) | `pololu_4845` |
| Pololu #4847 | 12 V, 99:1 표기, 25D HP, 모터축 48 CPR | [#4847](https://www.pololu.com/product/4847) | `pololu_4847` |
| Pololu #5725 | 24 V, 47:1 표기, 25D HP, 모터축 48 CPR | [#5725](https://www.pololu.com/product/5725) | `pololu_5725` |
| Pololu #4753 | 12 V, 실제 50:1, 37D, 모터축 64 CPR | [#4753](https://www.pololu.com/product/4753) | `pololu_4753` |
| StepperOnline 17HS16-2004S1 | NEMA 17, 바이폴라 4선, 각 상 2 A | [정확한 모델](https://www.omc-stepperonline.com/nema-17-bipolar-45ncm-64oz-in-2a-42x42x40mm-4-wires-w-1m-cable-connector-17hs16-2004s1) | `stepperonline_17hs16_2004s1` |
| StepperOnline 23HS22-2804S | NEMA 23, 바이폴라 4선, 각 상 2.8 A | [정확한 모델](https://www.omc-stepperonline.com/nema-23-bipolar-1-8deg-1-26nm-178-4oz-in-2-8a-2-5v-57x57x56mm-4-wires-23hs22-2804s) | `stepperonline_23hs22_2804s` |
| ROBOTIS XL430-W250-T | 6.5–12 V, TTL 반이중 패킷 버스 | [XL430 문서](https://emanual.robotis.com/docs/en/dxl/x/xl430-w250/) | `robotis_xl430_w250t` |
| ROBOTIS XM430-W350-T | 10–14.8 V, TTL형 3핀 | [XM430 문서](https://emanual.robotis.com/docs/en/dxl/x/xm430-w350/) | `robotis_xm430_w350t` |
| ROBOTIS XM430-W350-R | 10–14.8 V, RS-485형 4핀 | [XM430 문서](https://emanual.robotis.com/docs/en/dxl/x/xm430-w350/) | `robotis_xm430_w350r` |
| Concentric LACT6P-12V-10 | 12 V, 피드백형, 실제 150 mm 스트로크 | [Pololu #3647](https://www.pololu.com/product/3647) | `concentric_lact6p_12v_10` |
| Concentric LACT8P-12V-10 | 12 V, 피드백형, 실제 200 mm 스트로크 | [Pololu #3649](https://www.pololu.com/product/3649) | `concentric_lact8p_12v_10` |
| maxon EC-i 40 496655 | 36 V, 70 W, 3상 Hall BLDC | [정확한 모델](https://www.maxongroup.com/maxon/view/product/motor/ecmotor/EC-i/496655) | `maxon_ec_i40_496655` |

기존 [17HS19-2004S1](https://www.omc-stepperonline.com/nema-17-bipolar-59ncm-84oz-in-2a-42x48mm-4-wires-w-1m-cable-connector-17hs19-2004s1), [XL330-M288-T](https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/), [LACT10P-12V-10](https://www.pololu.com/product/3651)에도 정확한 제품 외부 단자도를 추가했습니다. XL330·LACT10P는 기존 수동 등록 항목이 외부 단자도 등록으로 바뀌고, 17HS19는 탐색 전용에서 단자도 등록 가능으로 바뀝니다.

## 부하 동작 전류를 자동으로 만들지 않는 이유

카탈로그에는 제조사의 무부하·정격·스톨 조건을 구분해서 표시합니다. 새 모터의 DC 소비전류 칸은 비워 두고, CAD에 연결할 때 계산 제외 상태로 시작합니다. DC 기어모터 선택도 무부하 전류나 스톨 전류를 정상 부하 전류로 채우지 않습니다.

- Pololu의 스톨 값은 이론적 외삽값입니다. 실제 부하·열·감속기 한계를 검토해야 합니다.
- 스테퍼의 A+/A−, B+/B−는 두 권선입니다. 각 상 정격과 드라이버의 DC 입력 전류는 다릅니다. 바이폴라 모델을 2단자 저항성 모터로 계산하지 않습니다.
- DYNAMIXEL은 디지털 패킷 버스로 제어합니다. stall 토크를 연속 토크로 쓰거나 DATA를 일반 RC 서보 PWM 핀으로 바꾸지 않습니다. 내부 센서에서 외부 A/B 핀을 추정하지 않습니다.
- BLDC의 연속 전류는 제조사 열 조건에 따른 모터 측 정격이며 배터리 소비전류가 아닙니다. 3상 정류·PWM·열 모델은 이 단자도에서 실행하지 않습니다.
- 선형 액추에이터는 제조사 duty와 하중 조건을 확인해야 합니다. 등록된 모델이 고속 연속 피로시험에 적합하다는 판정은 제공하지 않습니다.

## 단자 확인 자료와 배선 구분

Pololu의 네 새 제품은 각 제품 페이지의 `Using the encoder` 색상표를 개별 확인했습니다. 모터 빨강/검정 두 선과 엔코더 파랑 Vcc·초록 GND·노랑 A·흰색 B를 분리합니다. 검정 모터 선은 고정 접지가 아니며 엔코더 공급 범위 3.5–20 V는 모터 공칭 전압과 별개입니다. 24 V 모터를 선택해도 엔코더에 24 V를 자동 배선하지 않습니다. CPR은 모터축에서 A/B 양 채널의 모든 에지를 세는 기준으로 저장하고, 실제 감속비를 별도로 유지합니다.

스테퍼는 제품별 `Connection` 표와 [17HS16 도면](https://www.omc-stepperonline.com/download/17HS16-2004S1.pdf), [17HS19 도면](https://www.omc-stepperonline.com/download/17HS19-2004S1.pdf), [23HS22 도면](https://www.omc-stepperonline.com/download/23HS22-2804S.pdf)을 대조했습니다. 실물 커넥터 방향을 추정하지 않고 확인된 권선 이름과 전선 색상으로 표시합니다. 제조사는 17HE19와 17HS19의 배선 차이도 명시하므로 NEMA 규격만으로 핀맵을 공유하지 않습니다.

DYNAMIXEL의 `Connector Information`과 `Communication Circuit`을 사용합니다. TTL형과 RS-485형을 별도 모델로 저장합니다. XL330은 3.3 V TTL·5 V 호환으로 명시된 모델이며, XL430/XM430 TTL의 5 V 인터페이스 조건과 구분합니다. 실제 패킷·방향 제어·전압 호환은 연결도 저장만으로 검증되지 않습니다.

피드백 선형 액추에이터는 [Concentric LD Rev.20201208 PDF 5쪽](https://www.pololu.com/file/0J1238/LD-Linear-Actuator-Data-Sheet-201208.pdf)의 **mating-end view**를 확인했습니다. 2핀 모터 커넥터와 4핀 피드백 커넥터를 구분하고, 파랑 wiper·흰색 EXC−·노랑 EXC+·미사용 cavity를 보존합니다. P형의 극성에 따른 방향은 비피드백형과 다르며, 포텐셔미터를 모터 전원에 자동 연결하지 않습니다.

maxon은 [2025년 3월 카탈로그 309쪽](https://www.maxongroup.com/medias/sys_master/root/9406692130846/Cataloge-Page-EN-309.pdf)의 496655 열을 확인했습니다. 모터 4핀 커넥터와 Hall 센서 6핀 커넥터를 각각 표시하고 NC를 유지합니다. Hall은 정류 신호이며 quadrature 엔코더 A/B/Z로 분류하지 않습니다. 공칭 데이터는 이 판본과 현재 공식 제품 페이지가 일치하는 값이며, 이전 판본 수치를 섞지 않습니다.

모식도의 좌우 배치와 간격은 가독성을 위한 논리 좌표입니다. 제조사 PCB 외형·3D CAD·풋프린트의 실제 위치 또는 내부 회로 복제는 아닙니다.

## 검증

`tests/test_motor_catalog2220.py`는 30개 검사를 포함합니다. 15개 모델의 실제 CAD 부품 연결, 사용 가능한 외부 단자 저장과 프로젝트 재열기, 기존 형상·색·그룹 보존, 추가 등록 후 기존 회로 전력 유지, 임의 핀 거부를 확인합니다. TTL/RS-485 모델 변경은 기존 연결 제거 확인을 요구하고, 3상·바이폴라 모터의 허위 DC 계산 승격을 거부하는지 검사합니다. 새 제품 등록이 하드웨어·펌웨어 구동 시험을 대신하지는 않습니다.
