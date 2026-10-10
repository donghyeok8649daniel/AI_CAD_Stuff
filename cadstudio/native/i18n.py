"""Local UI catalogue. User-entered text and CAD documents are never translated."""
import json
import re
from pathlib import Path
from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QAbstractButton,QComboBox,QGroupBox,QLineEdit,QPlainTextEdit,QTabWidget,QTableWidget,QTreeWidget
from shiboken6 import isValid


PAIRS = '''전장 작업…|Electrical workspace…
선택한 연결 수정|Update selected motion link
운동 값은 허용 범위의 유한한 숫자여야 합니다.|Motion values must be finite numbers within the allowed range.
운동 값에 숫자를 입력하세요.|Enter a number for the motion value.
비율 / 오프셋을 반영하려면 연결 추가 또는 선택한 연결 수정을 누르세요.|To apply the ratio / offset, add a link or update the selected link.
설계 명령 / AI|Design commands / AI
실물 사진 / 증상 · 전장 진단…|Electrical photo / symptom diagnosis…
Codex 펌웨어 생성 / 검토…|Codex firmware · generate / review…
코드 업로드 · 배선 자동 시뮬레이션…|Upload code · automatic wiring simulation…
쇼트 / 정격 / 발열 점검…|Short / ratings / heat check…
회로도에서 이 부품 찾기|Find this part in the circuit
기존 회로 부품과 CAD 대응 설정…|Link an existing circuit component to this CAD body…
회로 부품 / CAD 대응 변경|Change circuit / CAD association
전장 변경 저장 · AI 요청 준비|Save electrical changes · prepare AI
진행 중인 AI 작업이 있습니다. 완료하거나 취소한 뒤 배선 요청을 준비하세요.|An AI task is running. Finish or cancel it before preparing a wiring request.
전장 등록 / 배선 상태…|Electrical registration / wiring status…
전장 작업 / 부품 등록 · 배선 편집|Electrical workspace / registration and wiring
부품 재질 / 물성 목록…|Part material / property catalog…
하중 측정 / 교정 연결…|Force acquisition / calibration…
시편 습도 챔버 / 편집…|Specimen humidity chamber / edit…
시편 습도 챔버|Specimen humidity chamber
챔버 치수 / 밀봉 인터페이스 편집|Edit chamber dimensions / sealing interfaces
선택 시편의 재질값 가져오기|Import selected specimen material values
전면 도어 분리해 내부 보기 · 표시만|Inspect with front door hidden · display only
챔버 이름 / 구성품 접두사|Chamber name / component ID prefix
시편·그립 전체 운동 보호 영역|Protected swept bounds of specimen / grips
본체 · 설치 여유|Housing / installation clearance
힘 계측 · 로드셀 / ADC / 온습도|Force acquisition · load cell / ADC / environment
배선·용량·대역폭 검토|Check wiring / capacity / bandwidth
설계에 계측 설정 저장|Save acquisition settings to design
계측 경로 / 사양|Acquisition chain / specifications
검토 결과|Assessment results
선택 / 미확인|Select / unknown
로드셀 여자 전원|Load-cell excitation source
로드셀|Load cell
ADC 수집|Acquisition ADC
수집 MCU / MPU|Acquisition MCU / MPU
계측 사양…|Measurement specifications…
목표 반복 주파수 (Hz)|Planned cyclic frequency (Hz)
ADC 별도 CLKIN 발진 부품|Separate ADC CLKIN oscillator
발진 부품의 실제 출력 단자|Oscillator's physical output terminal
목표 최대 하중 (N)|Planned maximum force (N)
주기당 샘플 검토 기준 (규격값 아님)|Samples per cycle criterion (not a standard)
계측 기록 검토|Acquisition recording assessment
힘 폐루프 검토 · 실물 검증 필수|Force feedback assessment · hardware validation required
ADC 역할 = 수집 보드 실제 핀|ADC role = physical acquisition board pin
환경 기록 센서 (선택)|Environmental recording sensors (optional)
선택 센서 온습도 사양…|Selected sensor humidity / temperature specifications…
실측점으로 N/count 교정|Calibrate N/count from measured points
교정 미확인으로 되돌리기|Reset to uncalibrated
미확인|Unknown
피로시험 조건 / 데이터 양식…|Fatigue test protocol / data template…
피로시험 조건 / 데이터 양식|Fatigue test protocol / data template
피로시험 준비 패키지 저장|Save fatigue experiment package
시편 STEP + 시험 조건 + 실측 CSV 양식|Specimen STEP + protocol + measurement CSV template
아직 정하지 않은 하중·속도·왕복거리는 비워두세요. 입력값은 장비 성능이 아닌 시험 계획이며 설계를 변경하지 않습니다.|Leave undecided load, frequency and stroke blank. These are planned settings, not machine ratings. The design is unchanged.
인장·압축 반복|Cyclic tension / compression
미정 · 방식 확인 필요|Undecided · validate the method
미정 · 비워두기|Undecided · leave blank
재료 배치 / 상태|Material batch / condition
목표 최대 하중 · N|Planned maximum force · N
목표 반복 속도 · Hz|Planned frequency · Hz
목표 왕복거리 · peak-to-peak mm|Planned peak-to-peak stroke · mm
시험 방식|Test method
실측 초·Hz와 연구 모델 시간은 자동 변환하지 않습니다. 크로스헤드 변위를 시편 변형률로 대신하지 않습니다. 웨이퍼의 시험·고정구 검증은 별도로 필요합니다.|Physical seconds/Hz are not automatically mapped to model time. Crosshead displacement is not gauge strain. Wafer tests and fixtures require separate validation.
입력값을 확인하세요. 치수는 양수이며 미정은 비워둡니다. 웨이퍼의 시험 방식은 미정이어야 합니다.|Check the inputs. Use positive numbers or leave undecided values blank. The wafer method must remain undecided.
부품 역할 / 기본색…|Part role / default color…
부품 역할 / 기본색|Part role / default color
미지정 · 기존 색상|Unspecified · existing color
구조 / 보호 · 흰색|Structure / guard · white
전장 / 센서 · 노란색|Electrical / sensor · yellow
구동 / 하중 전달 · 초록색|Drive / load transfer · green
시편 · 회색|Specimen · gray
선택 부품에 역할 기본색도 적용|Also apply the role color to selected parts
선택을 끄면 직접 지정한 색상은 그대로 유지합니다.|Uncheck to preserve custom colors.
현재 색상 유지|Keep current colors
역할에 맞는 기본 색상을 선택하세요. 재질·물성과 관절 상태 표시는 별도로 유지됩니다.|Choose a color by role. Materials, properties and joint status remain separate.
Codex 연결·사용량 새로고침|Refresh Codex connection / usage
Codex 주간 · 잔여량 확인 전|Codex weekly · not checked
Codex 주간 · 조회 중…|Codex weekly · checking…
Codex 주간 · 잔여량 확인 불가|Codex weekly · remaining usage unavailable
잔여율·초기화 시각은 기존 로그인 사용 버튼으로 새로고침합니다.|Refresh remaining usage and reset time using the existing login button.
계정 전체에서 공유하는 Codex 사용량입니다. 실제 남은 토큰 개수는 제공되지 않습니다. 새로고침으로 확인하며 자동 구매나 한도 초기화는 하지 않습니다.|Codex usage is shared across the account. An exact remaining token count is unavailable. Refresh to check; this never purchases credits or resets limits.
AI로 간섭 수정 계속|Continue AI interference repair
미리보기 / 수정|Preview / repair
검증 통과 후 적용 가능|Apply after validation passes
전체 초안 보기|Show the whole draft
간섭이 남은 초안입니다. 원본은 그대로이며, 수정 후 검증을 통과하면 적용할 수 있습니다.|This draft has interference. The original is unchanged; apply after repair and validation.
추가 수정 지시 (선택) · 예: 시편 치수는 유지하고 클램프 홈을 넓혀줘|Optional instructions: e.g. keep the specimen dimensions and widen the clamp slot
기어 모듈|Gear module
잇수|Tooth count
압력각|Pressure angle
쌍의 피치원 백래시|Pair pitch-circle backlash
▸ 출력할 부품 선택|▸ Choose parts to print
▾ 출력할 부품 선택|▾ Choose parts to print
▸ 프린터 / 자동 배치 설정|▸ Printer / automatic layout settings
▾ 프린터 / 자동 배치 설정|▾ Printer / automatic layout settings
출력할 부품 선택|Choose parts to print
프린터 / 자동 배치 설정|Printer / automatic layout settings
실제 스퍼 기어 구동…|Physical spur gear drive…
스퍼 기어 구동 설계|Spur gear drive design
모듈|Module
입력 잇수|Input teeth
출력 잇수|Output teeth
기어 두께|Gear thickness
기어 쌍 백래시|Gear pair backlash
일체형 축 지름|Integral shaft diameter
일체형 축 길이|Integral shaft length
축 지름 여유|Diametral shaft clearance
배치할 부품|Part to arrange
바닥 중심 X|Bed center X
바닥 중심 Y|Bed center Y
부품 X 회전|Part X rotation
부품 Y 회전|Part Y rotation
부품 Z 회전|Part Z rotation
부품을 드래그해서 바닥에 배치|Drag parts on the build plate
상면에서 배치|Arrange from top view
전체 자동 배치 / 방향 초기화|Auto arrange all / reset orientation
지지 형상 확인 · 현재 자세|Support geometry checked · current pose
구조 미확인|Structure unverified
간섭 / 구조 오류|Interference / structural error
소프트웨어 3D · 안정 모드|Software 3D · safe mode
그래픽 시작 진단…|Graphics startup diagnostics…
그래픽 시작 진단|Graphics startup diagnostics
진단 폴더 열기|Open diagnostics folder
관절 축 · 구멍 동심 정렬…|Align joint shaft / bore axes…
관절 축 · 구멍 동심 정렬|Align joint shaft / bore axes
현재 축 방향 위치 / 회전 각도 유지|Keep current axial position / rotation
축 방향 뒤집기|Reverse axis direction
기준 부품 · 구멍 / 원통|Parent bore / cylinder
이동 부품 · 축 / 원통|Child shaft / cylinder
파일(&F)|&File
편집(&E)|&Edit
모델링(&M)|&Model
조립(&A)|&Assembly
보기(&V)|&View
도움말(&H)|&Help
새 설계|New design
열기…|Open…
저장|Save
다른 이름으로 저장…|Save as…
최근 자동저장 복구…|Recover autosave…
내보내기|Export
CAD 부품 가져오기 · STEP / IGES / STL…|Import CAD · STEP / IGES / STL…
STEP · CAD 교환|STEP · CAD exchange
STL · 메시|STL · mesh
F3D · Fusion 변환|F3D · via Fusion
IPT · Inventor 부품 변환|IPT · via Inventor
Fusion / Inventor 변환 패키지|Fusion / Inventor conversion package
예제 열기|Open example
종료|Exit
실행 취소|Undo
다시 실행|Redo
선택 부품 삭제|Delete selected parts
복사|Copy
잘라내기|Cut
붙여넣기|Paste
전체 선택|Select all
선택 해제|Clear selection
그룹|Group
그룹 해제|Ungroup
그룹 선택|Group selection
회전 Esc|Orbit Esc
범위 B|Box B
관절 J|Joints J
이동 M|Move M
선택만 보기|Isolate
모두 보기|Show all
분해 보기|Explode
부품별 내보내기|Export parts
선택 부품별 내보내기|Export selected parts
파일 형식|File format
배치|Placement
현재 조립 위치 유지|Keep assembly positions
부품별 원점 · XY 중심 / 바닥 Z=0|Local origin · center XY / floor Z=0
저장 위치 선택|Choose save location
분해 보기 · 원래 조립 위치 유지|Exploded view · original assembly preserved
보기 전용 · 조립 구속과 저장된 위치는 바뀌지 않습니다. 닫으면 원래 설계로 돌아갑니다.|View only. Assembly constraints and stored positions are preserved. Close to return.
X 방향으로 펼치기|Explode along X
Y 방향으로 펼치기|Explode along Y
Z 방향으로 펼치기|Explode along Z
부품 간 추가 간격|Additional spacing
조립 상태|Assembled
새 스케치 · XY|New sketch · XY
면 스케치|Sketch on face
스케치 편집 · Shift+E|Edit sketch · Shift+E
작업 평면 · 오프셋 / 기울기…|Work plane · offset / angle…
스윕 편집…|Sweep…
로프트 편집…|Loft…
곡면 만들기…|Surface…
3D 필렛 / 모따기…|3D fillet / chamfer…
3D 돌출 / 깊이 편집 · E|Extrude / edit depth · E
변수 / 연결 치수 · U|Parameters / linked dimensions · U
실제 관절 구조…|Physical joint hardware…
면으로 조인트|Joint from faces
관절 구동|Drive joint
로봇 치수|Robot dimensions
기준점으로 연결…|Joint from anchors…
시편 설계|Specimen design
관절 운동 한계 / 모션 연결…|Joint limits / motion links…
축 / 구멍 공차…|Shaft / bore tolerances…
간섭 검사…|Interference…
축 만들기|Create shaft
선택 부품 색상…|Part color…
3D 프린터 · 전체 여유 / 공차…|3D printer · project allowances…
전장부품 장착 자리…|Electronics mounting seat…
도구 찾기…|Find tool…
도구 찾기 · Ctrl+K|Find tool · Ctrl+K
모델에 맞춤|Fit model
모서리 표시|Show edges
사용 방법 · 단축키 매뉴얼|User guide / shortcuts
업데이트 확인…|Check for updates…
버전 / 앱 정보…|Version / about…
작업 공간|Workspace
설계|Model
조립|Assembly
시편|Specimen
XY 평면|XY plane
XZ 평면|XZ plane
YZ 평면|YZ plane
사용자 작업 평면…|Custom work plane…
스케치 작성|Create sketch
3D 도구|3D tools
부품 추가|Add part
설계 명령|Design prompt
설계 브라우저|Design browser
속성 / 선택|Properties / selection
피처 / 작업 타임라인|Feature / operation timeline
설계 명령 / AI|Design prompt / AI
모든 분기 / 상세|All branches / details
자동 선택|Auto select
점 선택|Points
선 / 모서리|Edges
면 선택|Faces
체적 / 부품|Bodies / parts
스케치 영역|Sketch regions
등각 1|Iso 1
상면 2|Top 2
정면 3|Front 3
측면 4|Right 4
새 설계 · XY 원점|New design · XY origin
선택 대상 · Shift+1~6|Selection filter · Shift+1–6
드래그: 회전 · Shift: 추가 선택 · Esc: 선택 해제 / 회전 · 아래 XYZ: 클릭 / 드래그로 시점 변경|Drag: orbit · Shift: add selection · Esc: clear / orbit · XYZ: click / drag to navigate
설계 요청|Design request
모델 · 대기 설정|Model / timeout
설계 초안 생성|Generate draft
검증된 초안 적용|Apply validated draft
생성 취소|Cancel generation
AI 생성 취소|Cancel AI
오프라인 치수 명령 · 키 불필요|Offline dimensions · no key
Codex · ChatGPT 구독|Codex · ChatGPT subscription
OpenAI · 유료 API|OpenAI · paid API
로컬 AI · Ollama|Local AI · Ollama
OpenAI 연결 · API 키 발급…|Connect OpenAI / get API key…
Codex 연결 · ChatGPT로 로그인…|Connect Codex / ChatGPT sign-in…
Codex 연결 · ChatGPT 구독…|Connect Codex / ChatGPT subscription…
로컬 AI 설치 / 모델 다운로드|Install local AI / download models
모델 이름|Model name
API 키 · 이번 실행 동안만 사용|API key · this session only
Astra 모델 선택|Select Astra model
추론 · 빠르게|Reasoning · fast
추론 · 균형|Reasoning · balanced
추론 · 깊게|Reasoning · deep
AI 최대 대기 · 3분|AI timeout · 3 minutes
AI 최대 대기 · 5분|AI timeout · 5 minutes
AI 최대 대기 · 10분|AI timeout · 10 minutes
AI 최대 대기 · 20분|AI timeout · 20 minutes
AI 최대 대기 · 무제한 (취소 가능)|AI timeout · unlimited (cancellable)
만들 형상과 치수, 바꿀 부분을 입력하세요.\n예: 선택한 구멍을 지름 6 mm로 줄여줘.|Describe the shape, dimensions or changes.\nExample: Change the selected hole diameter to 6 mm.
생성 진행과 검증 결과가 여기에 표시됩니다.|Generation progress and validation results appear here.
현재 선택: 없음 · 새 형상 또는 전체 설계 명령|No selection · request a new shape or edit the whole design
새 스케치에서 시작하거나 부품을 추가하세요.|Start a sketch or add a part.
확인|OK
취소|Cancel
닫기|Close
적용|Apply
설계에 적용|Apply to design
이름|Name
종류|Type
치수|Dimensions
길이|Length
폭|Width
높이|Height
두께|Thickness
지름|Diameter
직경|Diameter
반지름|Radius
깊이|Depth
각도|Angle
중심 X|Center X
중심 Y|Center Y
간격|Spacing
색상|Color
재질|Material
기준점|Anchor
부모 부품|Parent part
자식 부품|Child part
부모 기준점|Parent anchor
자식 기준점|Child anchor
조립 구속|Assembly joint
강체 · 0 자유도|Rigid · 0 DOF
회전 · RZ|Revolute · RZ
슬라이더 · Z|Slider · Z
원통 · Z + RZ|Cylindrical · Z + RZ
핀 슬롯 · X + RZ|Pin slot · X + RZ
평면 · X + Y + RZ|Planar · X + Y + RZ
볼 · RX + RY + RZ|Ball · RX + RY + RZ
면으로 조인트 만들기|Joint from faces
회전 관절 · 1 자유도|Revolute · 1 DOF
강체 고정 · 0 자유도|Rigid · 0 DOF
직선 이동 · 1 자유도|Slider · 1 DOF
회전 + 직선 이동 · 2 자유도|Cylindrical · 2 DOF
핀 슬롯 · 2 자유도|Pin slot · 2 DOF
평면 · 3 자유도|Planar · 3 DOF
볼 · 3 자유도|Ball · 3 DOF
면 사이 간격|Face gap
축 주위 각도|Angle about axis
두 면을 서로 마주 보게 연결|Face surfaces toward each other
부모가 최상위 부품이면 조립 기준으로 고정|Ground parent if it is a root component
연결된 부품 선택|Select connected parts
관절 구동 · 간섭 확인|Drive joint / check interference
고급 구속 / 오프셋 편집|Edit joint / offsets
이 관절에 실제 축 / 하우징 구조 추가|Add physical shaft / housing to this joint
실제 회전 관절 구조|Physical revolute joint
새 회전 관절 조립 만들기|Create new revolute assembly
축 지름|Shaft diameter
부시 내경 − 축 지름|Bushing bore − shaft diameter
하우징 길이|Housing length
부시 두께|Bushing wall
하우징 벽 두께|Housing wall
플랜지 두께|Flange thickness
장착 구멍 지름|Mounting hole diameter
축 방향 여유|Axial clearance
새 조립 X|New assembly X
새 조립 Y|New assembly Y
새 조립 Z|New assembly Z
3D 프린터 · 전체 여유 / 공차|3D printer · project allowances
프로젝트 전체의 연결된 치수를 함께 갱신합니다. 적용 전 실제 형상과 변경 치수를 확인하세요. 단위 mm.|Update linked dimensions throughout the project. Review the actual geometry and changed dimensions before applying. Units: mm.
프린터 보정 사용|Enable printer allowances
프린터 / 프로필|Printer / profile
재료|Material
구멍 지름 확대 +|Bore diameter increase +
축 외경 축소 −|Shaft diameter reduction −
새 관절 축방향 여유|New joint axial clearance
검토용 지름 허용편차 ±|Diameter deviation for review ±
PLA 시작값 · 0.2|PLA start · 0.2
모든 값 0|Set all to zero
적용 / 대상|Apply / target
현재 Ø|Current Ø
적용 후 Ø|Result Ø
축|Shaft
구멍|Bore
전체 연결|Link all
연결 해제|Unlink
선택 부품만|Selected parts only
프로필 저장|Save profile
프로필 불러오기|Load profile
지름 +0.2는 한쪽 반경 +0.1입니다. 축 Ø10 / 구멍 Ø10에 기본값을 적용하면 구멍 Ø10.2가 됩니다. ±허용편차는 형상을 바꾸지 않는 검토값입니다. 시험 출력으로 보정하세요.|Diameter +0.2 means radius +0.1 per side. A nominal 10 mm bore becomes 10.2 mm with the default. Review deviations do not change geometry. Calibrate with test prints.
전장부품 장착 자리|Electronics mounting seat
배터리·MCU·액추에이터의 실측 치수로 자리와 체결/전선 구멍을 만듭니다. 입력 치수는 선택 면 좌표입니다.|Create seats and mounting / cable holes from measured battery, MCU or actuator dimensions. Coordinates are local to the selected face.
사각 자리|Rectangular seat
원형 자리|Circular seat
부품 자리 파기|Cut component seat
4개 체결 구멍|Four mounting holes
전선 통과 구멍|Cable pass-through
부품 폭 / 지름|Component width / diameter
부품 길이|Component length
자리 깊이|Seat depth
자리 전체 여유|Total seat clearance
체결 구멍 간격 X|Mounting pitch X
체결 구멍 간격 Y|Mounting pitch Y
체결 구멍 지름|Mounting hole diameter
전선 구멍 지름|Cable hole diameter
전선 위치 X|Cable position X
전선 위치 Y|Cable position Y
구멍 뚫기|Hole
전체 관통|Through all
구멍 유형|Hole type
직선 구멍|Plain hole
원통 자리파기 · Counterbore|Counterbore
접시머리 · Countersink|Countersink
길이 측정 · mm|Measure length · mm
두 꼭짓점 사이 거리|Distance between two vertices
모서리 길이|Edge length
부품 간섭 검사|Part interference
스케치 종료|Finish sketch
스케치 취소|Cancel sketch
선|Line
원|Circle
사각형|Rectangle
호|Arc
스플라인|Spline
점|Point
수평|Horizontal
수직|Vertical
평행|Parallel
직교|Perpendicular
접선|Tangent
동일|Equal
고정|Fix
일치|Coincident
중점|Midpoint
대칭|Symmetry
치수 구속|Dimension constraint
보조선|Construction
자동 구속|Auto constraints
격자|Grid
스냅|Snap
돌출|Extrude
절삭|Cut
필렛|Fillet
모따기|Chamfer
삭제|Delete
추가|Add
값 / 식|Value / expression
계산값|Evaluated value
연결 치수|Linked dimension
식|Expression
변수 추가|Add parameter
선택 변수 삭제|Delete selected parameter
선택 연결 해제 · 현재 값 유지|Unlink selection · keep current value
부품 속성에서 연결한 식|Expressions linked in part properties
원통|Cylinder
판|Plate
링크|Link
브래킷|Bracket
원통형 시편|Round specimen
판형 시편|Flat specimen
나사산|Thread
설계에 적용하지 않고 닫기|Close without applying
IPT 내보내기|Export IPT
F3D 내보내기|Export F3D
Inventor 부품 · IPT|Inventor part · IPT
Fusion 아카이브 · F3D|Fusion archive · F3D
IPT 변환|Convert IPT
변환 준비|Prepare conversion
준비 폴더 열기|Open prepared folder
저장 위치|Save location
새 파일로 저장할 경로|Path for a new file
저장 위치를 선택하세요.|Choose a save location.
설치된 Inventor로 선택 부품을 변환합니다.|Convert the selected part using installed Inventor.
Inventor가 감지되지 않았습니다. 변환 준비 파일을 만든 뒤 Inventor가 설치된 PC에서 변환할 수 있습니다.|Inventor was not detected. Prepare files here and convert on a PC with Inventor installed.
Fusion에서 실행할 변환 스크립트와 STEP을 함께 준비합니다. Fusion의 스크립트 및 애드인에서 폴더를 등록하고 실행하면 지정한 F3D로 저장합니다.|Prepare a STEP and conversion script. Add the folder in Fusion Scripts and Add-ins, then run it to save the F3D.
실제 파일은 Autodesk 앱이 생성합니다. 원본 스케치·구속·피처 기록은 함께 저장하는 CAD 프로젝트에 보존하며 Autodesk 타임라인으로 재구성하지 않습니다.|Autodesk creates the final file. Original sketches, constraints and feature history remain in the included CAD project; they are not rebuilt as an Autodesk timeline.
언어 설정을 저장하지 못했습니다.|Could not save language preference.
프린터 전용 변수는 3D 프린터 전체 여유 / 공차 창에서 변경하세요.|Change printer parameters in the 3D printer allowances dialog.
장착 자리를 만들 평평한 면을 먼저 선택하세요.|Select a planar face for the mounting seat first.
작업을 완료하지 못했습니다|Operation could not be completed
작업 오류|Operation error
프로젝트 저장|Save project
현재 설계의 변경 내용을 저장할까요?|Save changes to the current design?
기준 면 선택됨|Reference face selected
이제 움직일 다른 부품의 평면을 클릭하세요.|Now select a planar face on the moving part.
면 선택 취소|Cancel face selection
먼저 기준 부품의 평평한 면을 클릭하세요.|Select a planar face on the reference part first.
면 조인트에는 평평한 면을 선택하세요.|Select a planar face for the joint.
두 번째 면은 다른 부품에서 선택하세요.|Select the second face on a different part.
치수를 입력하면 실제 CAD 형상을 미리 봅니다.|Enter dimensions to preview the actual CAD geometry.
형상 · 조립 구속 · 간섭 확인 중…|Checking geometry, assembly joints and interference…
구멍을 시작할 평평한 면을 먼저 클릭하세요.|Select a planar face to start the hole.
CAD 형상 계산 중…|Computing CAD geometry…
'''
EN=dict(line.split('|',1) for line in PAIRS.splitlines() if '|' in line)
EN.update({
    '부품 이름':'Part name','전체 길이':'Overall length','평행부 길이':'Gauge length','그립 직경':'Grip diameter','목 직경':'Gauge diameter',
    '전이 길이 (한쪽)':'Transition length (one side)','그립 폭':'Grip width','목 폭':'Gauge width','플랫 깊이':'Flat depth',
    '구멍 직경':'Hole diameter','구멍 중심 간격':'Hole center spacing','구멍 수':'Hole count','X 구멍 간격':'Hole pitch X','Y 구멍 간격':'Hole pitch Y',
    '구멍 가장자리 거리':'Hole inset','내경 (0 = 막힘)':'Bore diameter (0 = solid)','선택 부품만 보기 / 돌아오기':'Isolate this part / restore',
    '도면 / 해석':'Drawing / analysis','작업 기록 · 클릭: 상세 · 더블클릭: 해당 단계로 복원':'History · click: details · double-click: restore this step',
    '현재 연결 가능한 원형 치수가 없습니다. 프로필을 저장한 뒤 부품이나 구멍을 추가하세요.':'No supported circular dimensions yet. Save the profile, then add parts or holes.',
    '스케치':'Sketch','스케치 편집':'Edit sketch','구속 ▾':'Constraints ▾','치수 D':'Dimension D','돌출 E':'Extrude E','되돌리기':'Undo','다시':'Redo','맞춤':'Fit',
    '입력 X':'Input X','입력 Y':'Input Y','좌표로 점 입력':'Enter point by coordinates','그리기 완료 ↵':'Finish drawing ↵','선택 없음':'Nothing selected','보조선으로 작성':'Construction geometry',
    '격자 교점 · 선과 격자의 교점 스냅':'Snap to grid and curve/grid intersections','선·곡선 위 / 교점·중점·원점 스냅':'Snap to curves, intersections, midpoints and origin',
    '선을 그릴 때 추천':'Drawing inference','자동 · 접선/법선/평행/수직':'Auto · tangent/normal/parallel/perpendicular','접선 추천':'Tangent inference','법선 추천':'Normal inference','평행 추천':'Parallel inference','수직 추천':'Perpendicular inference','방향 추천 끄기':'Disable direction inference',
    '자유 배치 G':'Free placement G','해제':'Ungroup','그룹 Ctrl+G':'Group Ctrl+G','구속':'Constraints','변형':'Modify','돌출 적용':'Apply extrusion',
    '프로파일':'Profile','작업':'Operation','돌출 · 더하기':'Extrude · add','안쪽으로 파내기':'Cut inward','기본 스케치 편집':'Edit base sketch','이동 / 회전 · M':'Move / rotate · M','●  부품 색상 변경':'●  Change part color','재질 / 물성':'Material / properties',
    '이 부품 STEP / STL 내보내기':'Export this part · STEP / STL','스케치 그룹 · 돌출 / 절삭 공용':'Sketch group · extrusion / cut','선택 요소 / 영역 그룹화':'Group selected entities / regions','그룹 요소 선택 · 이동 / 복사':'Select group entities · move / copy','그룹 돌출':'Extrude group','그룹 절삭':'Cut group','그룹 해제 · 요소 유지':'Ungroup · keep entities',
    '격자 표시':'Show grid','좌표축 표시':'Show axes','격자 한 칸의 실제 길이 · mm':'Actual length of one grid cell · mm',
    '제품 스펙 · URL 가져오기…':'Product specs · import URL…','제품 URL에서 스펙 가져오기…':'Import specs from product URL…',
    '제품 스펙 · 출처 가져오기':'Product specifications / source',
    '공식 제조사 또는 구매 페이지 URL을 넣으세요. 치수 후보와 근거를 확인한 뒤 적용합니다. 로그인·쿠키 없이 공개 HTML만 읽습니다.':'Enter a manufacturer or retailer product URL. Review dimension candidates and evidence before applying. Only public HTML is read; no login or cookies.',
    '스펙 불러오기':'Fetch specs','원문 열기':'Open source','선택 치수 가져오기':'Use selected dimensions','AI 요청으로 보내기':'Prepare AI request',
    '제품 변형·치수 순서·장착 도면을 원문과 비교하세요. 자동 적용하지 않습니다.':'Check the product variant, dimension order and mounting drawing against the source. Nothing is applied automatically.',
    '제품 페이지 읽는 중… 닫으면 결과를 적용하지 않습니다.':'Reading product page… Close to discard the result.',
    '목록에서 체크한 치수만 보정합니다. 체크 해제는 원래 치수/식 복원, 보정 사용 해제는 연결 유지입니다. 일반 부품·원형 구멍을 지원합니다. 나사·가져온 메시·연결 스케치·구속 스케치는 원본 도구에서 편집하세요.':'Only checked dimensions are compensated. Uncheck a row to restore its nominal value/formula; disable allowances to retain the links. Basic bodies and circular holes are supported. Edit threads, imported meshes and linked/constrained sketches at their source.',
    '새 관절의 축방향 여유는 생성 시 기본값입니다. 기존 관절 위치는 바꾸지 않습니다. 프린터 전체 오차를 자동 측정하거나 표준 공차 등급을 인증하지 않습니다.':'Axial clearance is the default for new joints; existing joint positions stay unchanged. This does not automatically measure printer errors or certify tolerance grades.',
    '자리 전체 여유 0.2 mm는 양쪽 0.1 mm입니다. 원형 자리는 폭을 지름으로 사용합니다. 체결/전선 구멍은 관통하며 프린터 보정에 연결됩니다.':'A total seat clearance of 0.2 mm is 0.1 mm per side. Circular seats use width as diameter. Mounting/cable holes go through the body and link to printer allowances.',
    '실제 제품의 치수·구멍 간격은 직접 입력하세요. 커넥터 돌출, 배선 굽힘, 발열·배터리 팽창 공간은 별도 확인해야 합니다. 체결 강도나 전기적 안전 인증 기능은 아닙니다.':'Enter the actual product dimensions and mounting pitch. Check connector protrusions, cable bends, heat and battery expansion space separately. This does not certify fastening strength or electrical safety.',
    '가져온 1번 치수 → 폭, 2번 → 길이. 치수 순서를 확인하세요. 제품 높이를 자리 깊이로 자동 적용하지 않습니다.':'Dimension 1 → width; dimension 2 → length. Check the axis order. Product height is not automatically used as pocket depth.',
})


EN.update({
    '격자 · 축 모양':'Grid / axes appearance','격자 · 축 색상 / 밝기 / 선 굵기…':'Grid / axes colors, brightness, width…','격자 색':'Grid color','X축 색':'X-axis color','Y축 색':'Y-axis color','Z축 색':'Z-axis color','격자 밝기':'Grid brightness','축 밝기':'Axes brightness','격자 선 굵기':'Grid line width','축 선 굵기':'Axes line width','기본 모양으로':'Restore defaults','모양 저장':'Save appearance','3D 프린팅':'3D printing','3D 프린팅 · STL 미리보기…':'3D printing / STL preview…',
    '3D 프린팅 · STL 미리보기':'3D printing / STL preview', '이 미리보기로 STL 저장':'Save this preview as STL',
    '부품 간격':'Part spacing','STL 메시 오차':'STL mesh tolerance',
    '정밀 · 0.025 mm':'Fine / 0.025 mm','표준 · 0.05 mm':'Standard / 0.05 mm','가벼움 · 0.1 mm':'Coarse / 0.1 mm','고정밀 · 0.01 mm':'Extra fine / 0.01 mm',
    '출력 X 회전':'Print X rotation','출력 Y 회전':'Print Y rotation','출력 Z 회전':'Print Z rotation',
    '출력 영역 X':'Build volume X','출력 영역 Y':'Build volume Y','출력 영역 Z':'Build volume Z',
    '질의응답':'Questions','초안 생성':'Generate','질문 보내기':'Ask AI','미리보기 / 적용':'Preview / apply',
    'AI 설계 · 적용 전 비교':'AI design / before and after','변경 후 · AI 초안':'After / AI draft','변경 전 · 현재 설계':'Before / current design',
    '확인 · 설계에 적용':'Apply to design','돌아가기':'Back',
    '마지막 확인 자세로 이동':'Use last checked pose',
    'Codex 연결 상태 확인':'Check Codex connection','Codex · 연결 확인 전':'Codex / not checked',
    'Codex · 연결 확인 중…':'Codex / checking…','Codex · 연결 확인 실패':'Codex / check failed',
    '✓ Codex 연결 완료':'✓ Codex connected','Codex · 연결 재확인 필요':'Codex / recheck connection',
    '회전 지름 여유 · 부시 − 축':'Rotating fit / bush minus shaft',
    '삽입 지름 여유 · 하우징 − 부시':'Insertion fit / housing minus bush',
    '삽입 지름 여유 · 플랜지/칼라 − 축':'Insertion fit / flange/collar minus shaft',
})

EN.update({
    '연구 저장소 · AI 참고자료…':'Research repository / AI references…',
    '연구 저장소 · AI 참고자료':'Research repository / AI references',
    'GitHub 연구자료 · 파일 첨부…':'GitHub research / Attach files…',
    '참고자료 없음':'No reference materials',
    'GitHub 연구 저장소':'GitHub research repository',
    '로컬 파일 첨부':'Local files',
    '저장소':'Repository','브랜치 / 태그':'Branch / tag','GitHub 토큰':'GitHub token',
    '비워 두면 기본 브랜치':'Leave blank for the default branch',
    '비공개 저장소: Contents 읽기 토큰 · 이번 실행 동안만 사용':'Private repository: Contents read token / this session only',
    '연결 · 문서 목록 새로고침':'Connect / Refresh documents',
    '기존 Git 로그인 사용':'Use existing Git sign-in',
    '읽기 토큰 발급 ↗':'Create read token ↗',
    '문서 경로 검색 · 예: README, specimen, material':'Filter document paths: README, specimen, material',
    '선택 문서를 참고자료에 추가':'Add selected documents',
    '저장소 연결 해제':'Disconnect repository',
    '파일 선택…':'Choose files…','선택 자료 삭제':'Remove selected reference',
    '자료 모두 비우기':'Clear references','자료 사용':'Use references','조회 취소':'Cancel lookup',
    '연구 저장소에서 필요한 문서를 선택하세요. 첨부 내용은 다음 설계·질문과 함께 선택한 AI 서비스로 전송됩니다.':'Select documents from your research repository. Attached content is sent to the selected AI service with your next design or question.',
    '공개 저장소는 토큰 없이 연결합니다. 비공개 저장소는 해당 저장소의 Contents: Read 권한만 필요합니다. 저장소를 변경하거나 코드를 실행하지 않습니다.':'Public repositories need no token. Private repositories need Contents: Read permission. Repositories are never modified and code is never executed.',
    'PDF·TXT·MD·CSV·JSON·YAML·TOML·텍스트 코드 파일을 첨부할 수 있습니다. PDF는 텍스트만 읽으며 스캔·도면·그림은 해석하지 않습니다.':'Attach PDF, TXT, MD, CSV, JSON, YAML, TOML or text source code. PDF text only; scans, drawings and images are not interpreted.',
    'AI가 읽을 자료 · 최대 8개 / 합계 60,000자 · 파일당 앞부분 20,000자':'AI references / up to 8 files, 60,000 characters total, first 20,000 characters per file',
    '자료를 선택하면 실제로 전달할 내용과 출처를 확인할 수 있습니다.':'Select a reference to preview its source and the exact content to be sent.',
    '첨부 본문과 토큰은 프로젝트·설정에 저장하지 않습니다. 앱 재시작이나 새 설계에서는 자료를 다시 선택하세요. 연결 주소와 브랜치만 기억합니다.':'Reference bodies and tokens are not saved in projects or settings. Reattach after restart or a new document. Only repository address and branch are remembered.',
    '부품 이름 변경 · F2':'Rename part / F2','부품 이름 변경':'Rename part',
    '이름을 바꿀 개별 부품':'Choose the individual part to rename','새 부품 이름 · 최대 80자':'New part name / up to 80 characters',
    '부품 / 기능 검색…':'Find parts / commands…','부품 / 기능 검색 · Ctrl+F':'Find parts / commands / Ctrl+F',
    '부품 이름, 구멍, 측정, fillet…':'Part name, hole, measure, fillet…',
    '기능 / 명령':'Commands','전체':'All',
    '↑↓로 선택 · Enter: 부품/피처 선택 또는 기능 실행 · Esc: 닫기':'Up/Down: select / Enter: select object or run command / Esc: close',
    'AI 설계 완료 알림':'AI design completion notifications',
    'Codex · 연결 대기 · 자동 재시도':'Codex / Waiting for connection / Automatic retry',
})

EN.update({
    '전장 회로 · 배선 / 전압강하…':'Electrical circuit / wiring / voltage drop…',
    '전장 회로 / 배선 설계':'Design electrical circuit / wiring',
    '전장 · 배선 / 전압강하 검사':'Electrical wiring / voltage drop check',
    '전장 부품 / 배선 편집':'Edit electrical component / wiring',
    '회로 이름':'Circuit name',
    '배터리 / DC 전원':'Battery / DC source',
    '전선':'Wire','스위치':'Switch','저항':'Resistor',
    '일반 부하':'Generic load','모터':'Motor','MCU 전원 부하':'MCU power load',
    'MCU / 보드 전원 부하':'MCU / board power load',
    '첫 번째 단자 / 노드':'First terminal / node',
    '두 번째 단자 / 노드':'Second terminal / node',
    'CAD 부품에 연결하지 않음':'No linked CAD part',
    '공급 전압':'Supply voltage','배터리 내부저항':'Battery internal resistance',
    '저항값':'Resistance','정격 전압':'Rated voltage','정격 전류':'Rated current',
    '명시한 기동 전류 · 0은 미입력':'Entered startup current / 0 = unspecified',
    '전선 길이':'Wire length','도체 단면적':'Conductor cross section',
    '도체 저항률':'Conductor resistivity',
    '닫힌 접점 저항':'Closed contact resistance',
    '허용 전류 · 0은 미입력':'Maximum current / 0 = unspecified',
    '스위치 닫힘':'Switch closed',
    '전선 연결됨 · 해제하면 단선':'Wire connected / uncheck for open circuit',
    'MCU 신호 핀 = 노드 · 한 줄씩':'MCU signal pin = node / one per line',
    'MCU VCC / 노드':'MCU VCC / node',
    'MCU GND / 리턴 노드':'MCU GND / return node',
    'MCU의 첫 단자는 VCC, 둘째 단자는 GND/리턴입니다. 신호 핀은 도통만 검사하며 코드·논리 동작은 검증하지 않습니다.':'The MCU first terminal is VCC and the second is GND/return. Signal pins are checked for continuity only; code and logic behavior are not verified.',
    '제품 자료 찾기 · 오프라인 카탈로그':'Find product data / offline catalog',
    '제품 자료':'Product data',
    '모델 찾기…':'Find model…',
    '출처 열기':'Open source',
    '수동 입력 · 자료 연결 없음':'Manual entry / no linked source',
    '특정 모델만 회로 항목에 적용합니다. 제품군과 미지원 소자는 공식 자료를 열어 볼 수 있지만, 검증되지 않은 수치를 자동 입력하지 않습니다.':'Only specific models can prefill circuit entries. You may open official references for product families and unsupported devices, but unverified values are never entered automatically.',
    '모델명 · 제조사 · 제품군 검색':'Search model, maker or product family',
    '검색':'Search',
    '분류':'Category',
    '제조사':'Manufacturer',
    '모델 / 제품군':'Model / family',
    '회로 적용':'Circuit use',
    '자료만 열람':'Reference only',
    '특정 모델 · 입력 가능':'Specific model / usable',
    '공식 자료 열기':'Open official source',
    '선택 모델 입력':'Use selected model',
    '일치하는 자료가 없습니다. 정확한 모델명이나 제품군 이름으로 검색하세요.':'No matching entry. Search a specific model or product family.',
    '자료 열람 전용 · 이 항목은 DC 회로 모델로 자동 변환하지 않습니다.':'Reference only. This item is not automatically converted into a DC circuit model.',
    '특정 모델 · 확인된 사양만 입력됩니다. 빠진 수치는 직접 입력하세요.':'Specific model. Only supported values are filled; enter missing values yourself.',
    '자료 열람 전용':'Reference only',
    '이 항목은 특정 동작 정격을 확정할 수 없어 회로 입력을 자동 생성하지 않습니다. 공식 자료에서 제품 변형과 조건을 확인하세요.':'No specific operating ratings are established for this entry, so no circuit component is created. Check the exact variant and conditions in the official source.',
    'GND는 기준 전위입니다. 이름이 다른 단자는 이어지지 않습니다. 보고서의 PASS / WARN / FAIL은 입력한 배선 모델에 대한 결과입니다.':'GND is the reference. Differently named terminals are disconnected. PASS / WARN / FAIL refer only to the entered wiring model.',
    '초기 수치는 가상 예시입니다. 실제 정격·전선 치수로 바꾸세요. 노드 이름은 영문·숫자·_·-만 쓰며 회로 계산은 DC 정상 상태 근사입니다.':'Initial values are illustrative. Replace them with actual ratings and wire dimensions. Node names use letters, digits, _ and -. The circuit calculation is a DC steady-state estimate.',
    '배터리·전선·모터·MCU의 두 단자를 노드 이름으로 연결합니다. 실제 제품 정격과 전선 치수를 입력하세요.':'Connect battery, wire, motor and MCU terminals by node name. Enter actual product ratings and wire dimensions.',
    '첫 단자':'Terminal A','둘째 단자':'Terminal B','CAD 부품':'CAD part',
    '주요 입력':'Key input',
    '부품 / 전선 추가…':'Add component / wire…',
    '선택 편집…':'Edit selected…','선택 제거':'Remove selected',
    '예시 회로 · 가상값':'Example circuit / illustrative values',
    'GND는 기준 전위입니다. 이름이 다른 단자는 이어지지 않습니다. 적색 경고는 초과·단선·검증 불가를 뜻합니다.':'GND is the voltage reference. Terminals with different node names are not connected. Red warnings indicate exceeded limits, open circuits or unverified results.',
    '회로 다시 계산':'Recalculate circuit','설계에 저장':'Save to design',
    '관절 구동 가능 범위 · 실제 형상 표본 검사':'Joint travel range / sampled solid check',
    '선택 관절 양쪽 한계 검사':'Check both travel limits',
    '범위 검사 취소':'Cancel range check',
    '검사할 관절 축을 선택하세요.':'Select a joint axis to check.',
    '직접 움직일 수 있는 관절 축이 없습니다.':'No directly driven joint axis is available.',
    '현재 자세가 유효합니다. 선택한 축의 양쪽 한계를 검사할 수 있습니다.':'The current pose is valid. You can check both limits of the selected axis.',
    '현재 자세를 검사한 뒤 사용 가능합니다.':'Available after checking the current pose.',
    '선택한 축의 구동 범위는 아직 검사하지 않았습니다.':'This axis travel range has not been checked yet.',
    '현재 자세부터 입력한 자세까지 최대 2° / 0.5 mm 간격으로 검사합니다. 충돌을 발견하면 적용을 막습니다. 얇은 장애물의 연속 충돌·제작 오차는 별도 검토가 필요합니다.':'Checks samples up to 2° / 0.5 mm apart between the current and requested poses. Detected collisions block application. Continuous motion past thin obstacles and manufacturing tolerances need separate review.',
})

EN.update({
    '전장만':'Electrical only',
    '구조만':'Structure only',
    '동력만':'Transmission only',
    '역할 보기 해제 · 이전 표시 상태와 색상으로 돌아오기':'Clear role view · restore the previous visibility and colors',
    '전장만 보기 / 선택 · 노란색':'Show / select electrical parts · yellow',
    '구조만 보기 / 선택 · 흰색':'Show / select structural parts · white',
    '동력만 보기 / 선택 · 초록색':'Show / select transmission parts · green',
    '배터리 + / 공급 노드':'Battery + / supply node',
    '배터리 - / 리턴 노드':'Battery - / return node',
    '전원 인가 · 배터리 출력 켜기':'Power on / enable battery output',
    '배터리 +는 공급, -는 리턴입니다. 같은 노드 이름으로 단자를 연결하고 실제 배터리 전압·정격·전선 치수를 입력하세요.':'Battery + is the supply and - is the return. Connect terminals with matching node names and enter actual battery voltage, ratings, and wire dimensions.',
    '선택 배터리 전원 켜기/끄기':'Turn selected battery on/off',
    '선택 배터리 전원 차단':'Turn selected battery off',
    '선택 배터리 전원 인가':'Turn selected battery on',
    '배터리를 선택해 전원 전환':'Select a battery to switch power',
    '회로도 보기…':'View schematic…',
    '회로도 입력 확인':'Check schematic input',
    '전장 회로도 · 배선 연결 보기':'Electrical schematic / wiring connections',
    '전체 맞춤':'Fit all',
    '확대':'Zoom in',
    '축소':'Zoom out',
    '연결된 단자만 전기적으로 이어집니다. 교차선은 접점 표시가 있을 때만 연결됩니다.':'Only connected terminals are electrically joined. Crossing lines connect only where a junction is marked.',
    '읽기 전용 연결도 · 같은 노드 이름만 이어집니다. 교차선은 접점 표시가 있을 때만 연결됩니다.':'Read-only schematic · only matching node names connect. Crossing lines connect only where a junction is marked.',
    '드래그: 이동   휠: 커서 기준 확대/축소':'Drag to pan   Wheel to zoom around cursor',
    'DC 계산 결과 표시 · OFF 배터리와 단선된 전선은 전류를 공급하거나 전달하지 않습니다.':'Showing DC results · disabled batteries and open wires do not supply or conduct current.',
    '회로 계산 미완료 · 연결과 입력값만 표시 · OFF 배터리와 단선된 전선은 전류를 공급하거나 전달하지 않습니다.':'Circuit calculation incomplete · showing connections and inputs only. Disabled batteries and open wires do not supply or conduct current.',
})

EN['부품 역할 보기']='Part role view'

# v2.16 generated static UI translations
EN.update({'기계 · 전원 규격 DB…': 'Mechanical / power standards DB…', '품번·치수·조건·출처를 AI 요청에 추가했습니다.': 'Part numbers, dimensions, conditions and sources added to the AI prompt.', '규격 관통홀 선택…': 'Choose standard clearance hole…', '규격 미선택 · 치수는 직접 입력': 'No standard selected · enter dimensions manually', '기계·전원 규격 자료 · 오프라인': 'Mechanical / power standards · offline', '정확한 품번과 출처를 검색하세요. 전류 정격·자유공기 전류는 실제 부하 전류나 밀폐 하네스 허용값이 아닙니다. 미확인 패널 구멍과 FDM 공차는 자동 입력하지 않습니다.': 'Search exact part numbers and sources. Current ratings and free-air wire ratings are not the actual load current or an enclosed harness limit. Unverified panel cutouts and FDM clearances are not filled automatically.', '품번 · 제조사 · M4 · AWG18 · 관통홀 검색': 'Search part number · manufacturer · M4 · AWG18 · clearance hole', '전체 분류': 'All categories', '전원 커넥터': 'Power connector', '패널 DC 잭': 'Panel DC jack', '전선': 'Wire', '관통홀 규격': 'Clearance hole standard', '나사 머리': 'Screw head', '검색': 'Search', '분류': 'Category', '제조사': 'Manufacturer', '품번 / 규격': 'Part number / standard', '핵심 설명': 'Summary', '공식 자료': 'Official source', '공식 자료 열기': 'Open official source', '선택한 항목을 프로젝트에 적용하기 전 제조사 조건을 확인하세요.': "Check the manufacturer's conditions before applying the selected record to a project.", 'AI 사양 복사': 'Copy AI spec', '선택': 'Select', '일치하는 자료가 없습니다. 품번이나 규격 크기로 다시 검색하세요.': 'No matching records. Search a part number or standard size.', '품번·조건·공식 출처가 포함된 사양을 복사했습니다.': 'Copied a specification with part number, conditions and official source.', '전원 연결 설계…': 'Design power connection…', '전원 연결 설계 · 공급선과 리턴선': 'Design power connection · supply and return', '배터리 + → 스위치 → 공급선 → 부하 → 리턴선 → 배터리 - 경로를 작성합니다. 입력 전류·전압·실제 전선 치수를 확인하고 미리보기에서 계산한 뒤 기존 회로에 추가합니다.': 'Create a battery + → switch → positive lead → load → return lead → battery − path. Enter actual voltage, current and wire dimensions, inspect the preview, then append it to the existing circuit.', '경로 이름과 출력 상태': 'Path name and output state', '경로 이름': 'Path name', '전원 경로': 'Power path', '전원 인가 · 배터리 출력 ON': 'Apply power · battery output ON', '스위치 닫힘 · 전원 경로 도통': 'Switch closed · path conducts', '배터리 / DC 공급원': 'Battery / DC source', '개방 전압 · 필수': 'Open-circuit voltage · required', '내부저항 · 0은 이상적 전원 모델': 'Internal resistance · 0 models an ideal source', '입력한 최대 출력 전류 · 0은 미검증': 'Entered output-current limit · 0 means unverified', 'CAD 배터리 부품 · 선택': 'CAD battery part · optional', '직렬 스위치': 'Series switch', '닫힌 접점저항 · 기본 0.01 Ω 근사': 'Closed-contact resistance · 0.01 Ω estimate by default', '입력한 허용 전류 · 0은 미검증': 'Entered current limit · 0 means unverified', 'CAD 스위치 부품 · 선택': 'CAD switch part · optional', '양극 공급 전선': 'Positive supply wire', '실제 배선 길이 · 필수': 'Actual wire length · required', '도체 단면적 · 필수': 'Conductor area · required', '정확한 전선 SKU · 선택': 'Exact wire SKU · optional', '수동 저항률 사용': 'Use entered resistivity', '저항률 · 기본은 상온 구리 근사': 'Resistivity · room-temperature copper estimate by default', '수동 입력 · 기본 상온 구리 저항률 근사': 'Manual input · default room-temperature copper estimate', 'CAD 공급선 부품 · 선택': 'CAD positive-lead part · optional', '부하': 'Load', '모델 종류': 'Model kind', '일반 저항 등가 부하': 'Generic resistance-equivalent load', '모터 · 정격 등가 부하': 'Motor · rated resistance-equivalent load', 'MCU / 보드 전원 부하': 'MCU / board power load', '실제 입력 정격 전압 · 필수': 'Actual input rated voltage · required', '해당 작동점의 전류 · 필수': 'Current at this operating point · required', '모터 기동 전류 · 0은 미입력': 'Motor starting current · 0 means not entered', 'CAD 부하 부품 · 선택': 'CAD load part · optional', '음극 리턴 전선': 'Negative return wire', 'CAD 리턴선 부품 · 선택': 'CAD return-lead part · optional', 'CAD 부품에 연결하지 않음': 'No linked CAD part', '공식 출처': 'Official source', 'DC 저항 등가만 계산합니다. 전선 허용 전류와 배터리 내부저항은 실측 또는 명시된 자료로 확인하세요. MCU 코드·모터 드라이버·배터리 수명·열 안전은 여기서 판단하지 않습니다.': 'Only a DC resistance-equivalent circuit is calculated. Check wire current limits and battery internal resistance against measurements or documented sources. Firmware, motor drivers, battery life and thermal safety are not evaluated.', '회로도 미리보기…': 'Preview schematic…', '기존 회로에 추가': 'Append to existing circuit', '전원·배선 정격 점검 · 입력값 기준이며 실제 제품 안전 인증은 아닙니다': 'Power and wiring limit checks · based on entered values, not safety certification', '결선 점검 · 입력한 모델의 도통과 MCU 전원 경로만 확인': 'Wiring checks · continuity and MCU supply path in the entered model only', '전원 단자 출력 / 부하·저항 소비': 'Source terminal output / load and resistive consumption', '볼트 축방향 인장 사전 검토': 'Bolt axial tension preliminary check', 'ISO 898-1 강재 볼트의 나사부에 순수한 정적 축인장이 걸릴 때만 증명하중과 비교합니다. 실제 총 하중·동일 볼트 개수·안전계수를 입력하세요. 결합부나 기계 전체의 안전 판정은 하지 않습니다.': 'Compare proof load only for pure static axial tension through the threaded section of an ISO 898-1 steel bolt. Enter the actual total force, number of identical bolts and a safety factor. This does not assess the whole joint or machine.', '볼트 보통 피치': 'Bolt coarse pitch', '실제 강도 등급': 'Actual property class', '실제 총 축방향 인장 하중 · N': 'Actual total axial tensile force · N', '총 축방향 인장 하중 (N)': 'Total axial tensile force (N)', '하중을 함께 받는 동일 볼트 개수': 'Number of identical bolts sharing the force', '볼트 개수': 'Bolt count', '사용자가 정한 안전계수 · 1 이상': 'User-selected safety factor · at least 1', '안전계수': 'Safety factor', '동일 볼트가 축방향 하중을 균등하게 분담한다고 가정합니다': 'I assume identical bolts share the axial force equally', '낮은 머리·접시머리처럼 증명하중을 낮출 수 있는 머리 형상이 아님을 확인했습니다': 'I confirmed this is not a low or countersunk head that could reduce the proof load', 'M8은 6az 용융아연도금 감소 증명하중 대상이 아님을 확인했습니다': 'I confirmed this M8 bolt is not subject to the reduced 6az hot-dip galvanized proof load', '전단·굽힘·편심·프리로드·피로·나사산 뽑힘·플라스틱 모재는 계산하지 않습니다. 확인한 실물 볼트의 등급·피치·코팅이 자료와 일치해야 합니다.': "Shear, bending, eccentricity, preload, fatigue, thread pull-out and plastic substrates are outside this calculation. Verify the actual bolt's class, pitch and coating against the source.", '축인장 검토 계산': 'Calculate axial check', 'Bossard 원문 열기': 'Open Bossard source', '보통 피치 원문 열기': 'Open coarse-pitch source', '하중·개수·안전계수는 아직 입력되지 않았습니다.': 'Force, count and safety factor have not been entered.', '입력이 바뀌었습니다. 다시 계산하세요.': 'Inputs changed. Calculate again.', '계산 결과와 적용 범위가 여기에 표시됩니다.': 'Result and scope appear here.', '검토 결과 복사': 'Copy check result', '총 하중·볼트 개수·안전계수를 모두 입력하세요.': 'Enter the total force, bolt count and safety factor.', '하중·개수·안전계수는 숫자로 입력하세요.': 'Enter numeric values for force, count and safety factor.', '입력값을 확인하세요.': 'Check the input values.', '지원하는 볼트는 8.8/10.9급 보통 피치 M4, M5, M6, M8뿐입니다.': 'Supported bolts are only class 8.8/10.9 coarse-pitch M4, M5, M6 and M8.', '볼트의 균등 하중 분담 가정을 직접 확인해야 합니다.': 'Confirm the equal load-sharing assumption for the bolts.', '낮은 머리·접시머리처럼 증명하중을 낮출 수 있는 형상이 아님을 확인해야 합니다.': 'Confirm this is not a low or countersunk head that may reduce the proof load.', 'M8은 6az 용융아연도금 감소 증명하중 대상이 아님을 확인해야 합니다.': 'Confirm this M8 bolt is not subject to the reduced 6az hot-dip galvanized proof load.', '볼트 개수는 1~1,000,000의 정수로 입력하세요.': 'Enter an integer bolt count from 1 to 1,000,000.', '총 축방향 인장 하중은 수치로 입력하세요.': 'Enter a numeric total axial tensile force.', '총 축방향 인장 하중은 0 초과의 유한한 값이어야 합니다.': 'Total axial tensile force must be finite and greater than zero.', '안전계수는 수치로 입력하세요.': 'Enter a numeric safety factor.', '안전계수는 1 이상의 유한한 값이어야 합니다.': 'Safety factor must be finite and at least one.', '하중과 안전계수의 곱이 계산 범위를 넘습니다.': 'Force times safety factor exceeds the calculation range.', '입력 하중이 부동소수점 계산 정밀도보다 작습니다.': 'Entered force is below floating-point calculation precision.', '볼트 개수에 따른 참조 하중이 계산 범위를 넘습니다.': 'Reference force for this bolt count exceeds the calculation range.', '이 축인장 가정에서 참조 증명하중 이내 · 결합부 검증은 별도': 'Within the proof reference for this axial assumption · verify the joint separately', '축인장 가정에서도 참조 증명하중 초과 · 설계 수정 필요': 'Above the proof reference even for axial tension · revise the design', '출처와 검토 범위를 포함한 결과를 복사했습니다.': 'Copied the result with its source and scope.', '볼트 축방향 검토…': 'Axial bolt check…'})
# end v2.16 static UI translations

EN.update({
    'MCU 선택 / 핀 연결…': 'Select MCU / pin connections…',
    'MCU 핀 연결 편집': 'Edit MCU pin connections',
    'MCU 입력 확인': 'Check MCU inputs',
    '같은 노드 이름만 이어집니다. MCU를 고르고 핀을 클릭하면 연결을 편집합니다. 교차선은 접점 표시가 있을 때만 연결됩니다.': 'Only equal net names connect. Select an MCU and click a pin to edit wiring. Crossing lines connect only at junction dots.',
    '핀 모식도 전체 맞춤': 'Fit pin diagram',
    '핀을 클릭해 연결 편집 · GPIO와 전원 레일은 별도입니다.': 'Click a pin to edit wiring · GPIO and supply rails are separate.',
    '회로도 변경 저장': 'Save schematic changes',
    'MCU 핀을 클릭해 센서·드라이버·다른 보드 단자와 연결합니다.': 'Click an MCU pin to connect a sensor, driver or another board terminal.',
    '추가 신호 단자 = 노드 · 센서 / 드라이버': 'Additional signal terminal = net · sensor / driver',
    '핀 연결 해제 확인': 'Confirm pin disconnection',
    '모델을 바꾸면 기존 MCU 핀 연결을 해제합니다. 계속할까요?': 'Changing the model removes existing MCU pin assignments. Continue?',
})

EN.update({'CAD 부품 · 전장 등록 / 모식도…': 'CAD part · electrical registration / diagram…', '이 CAD 부품을 전장으로 등록…': 'Register this CAD part as electrical…', '전장 피처 · 모델 / 모식도 편집': 'Electrical feature · edit model / diagram', '정격 입력 완료 · DC 계산에 포함': 'Ratings entered · include in DC analysis', '정격 입력 전 · DC 계산 제외': 'Ratings pending · excluded from DC analysis', '전장으로 등록할 CAD 부품을 먼저 만들거나 가져오세요.': 'First create or import the CAD part to register as electrical.', '전장 피처를 더블클릭하면 모델·핀 모식도를 편집합니다.': 'Double-click the electrical feature to edit its model / pin diagram.', '사용자 정의': 'Custom', 'DC 계산 포함': 'Included in DC analysis'})


EN.update({
    '기계 기능 · 체결 / 관절 / 액추에이터…':'Mechanical function · fastener / joint / actuator…',
    '연결 부품의 기계 기능 지정…':'Assign mechanical functions to connected parts…',
    '관절 구속은 운동 관계입니다. 체결부품·수동 지지부·실제 구동기는 별도로 지정합니다.':'A joint defines a motion relationship. Fasteners, passive supports and actual actuators are declared separately.',
    '기계 기능 미지정':'Mechanical function unspecified',
    '체결 부품 · 볼트 / 너트 / 고정 핀':'Fastener · bolt / nut / retaining pin',
    '수동 관절 지지 구조':'Passive joint support',
    '구동기 · 모터 / 액추에이터':'Actuator · motor / powered actuator',
    '동력 전달 부품':'Mechanical transmission',
})

EN.update({
    '출력할 부품을 선택하세요. 부품이 많으면 여러 출력판에 나누며 원본 설계·관절은 변경하지 않습니다.':'Select parts to print. Large selections are arranged on multiple plates; the source design and joints stay unchanged.',
    '미리볼 출력판':'Preview plate', '출력판 1':'Plate 1',
    '선택한 부품을 출력판에 배치합니다.':'Arrange selected parts on print plates.',
    '이 부품의 출력판':"This part's plate", '볼트·너트 제외':'Exclude bolts and nuts',
    '볼트·너트 판별 근거를 표시합니다. 이름에 따른 추정은 제품 확인이 아니며 와셔·핀과 미분류 부품은 남깁니다.':'Classification reasons are shown. Name hints do not verify products; washers, pins and unclassified parts are retained.',
    '현재 선택':'Current selection', '전체 선택':'Select all', '선택 해제':'Clear selection',
    '새 출력판':'New plate', '전체 출력판 STL · ZIP 저장':'Save all plate STLs as ZIP',
    '현재 출력판 STL 저장':'Save current plate STL', '출력판 STL 묶음 저장':'Save plate STL bundle',
    '한 부품이 출력 영역보다 크면 경고합니다. 부품 자체를 자르지 않습니다. 여러 출력판은 판별 STL과 목록을 ZIP으로 저장합니다.':'Oversized parts produce warnings and are never sliced. Multiple plates are saved as separate STLs and an index in a ZIP.',
    '출력할 부품을 하나 이상 선택하세요.':'Select at least one part to print.',
    '3D 출력 작업이 취소되었습니다.':'3D print preparation was cancelled.',
    '명시된 제품 종류 또는 카탈로그 분류입니다.':'Explicit product subtype or catalog classification.',
    '제품 종류 지정이 서로 다릅니다.':'Product subtype declarations conflict.',
    '이름에 핀·와셔·나사 단서가 있어 볼트·너트로 자동 제외하지 않습니다.':'Pin, washer or screw name hints prevent automatic bolt/nut exclusion.',
    '이름의 독립 단어 단서입니다. 실제 제품 식별은 미검증이며 선택을 직접 바꿀 수 있습니다.':'Separate-word name hint. Product identity is unverified; edit the selection as needed.',
    '이름에 볼트·너트 단서가 함께 있어 자동 제외하지 않습니다.':'Both bolt and nut name hints are present; automatic exclusion is disabled.',
    '체결 부품 또는 미지정 기능만으로 볼트·너트 종류를 알 수 없습니다.':'A generic fastener or unspecified function does not identify a bolt or nut.',
    '저장된 기계 기능은 볼트·너트 지정이 아닙니다.':'The saved mechanical function does not declare a bolt or nut.',
    '자동 자세·배치 (서포트 최소)':'Auto orient / arrange (less support)',
    '자동 자세 후보를 비교하는 중…':'Comparing print orientation candidates…',
    '형상 기반 추정입니다. 실제 서포트 체적·슬라이싱·출력 성공을 보장하지 않습니다.':'Geometry-based estimates. Actual support volume, slicing and successful printing are not guaranteed.',
    '추천 자세 적용':'Recommended orientation applied',
    '수동 자세 · 자동 추천 이후 변경됨':'Manual orientation · changed after recommendation',
    '예상 서포트 면적':'Estimated support area',
    '바닥 접촉 면적':'Bed contact area',
    '안정성':'Stability',
    '출력 영역 적합':'Build-volume fit',
    '추천 회전 X / Y / Z':'Recommended X / Y / Z rotation',
    '서포트 추정 지표 · 전 / 추천':'Estimated support demand · before / recommended',
    '돌출 면적 · 전 / 추천':'Overhang area · before / recommended',
    '바닥 접촉 면적 · 전 / 추천':'Bed contact area · before / recommended',
    '안정성 · 추천 기준':'Stability · recommendation',
    '출력 영역 적합 · 추천 기준':'Build-volume fit · recommendation',
    '자동 버튼을 눌러 자세 후보를 비교하세요.':'Click auto orientation to compare candidate poses.',
    '이전 출력 영역 추천 · 다시 비교하세요.':'Recommendation for the previous build volume · compare again.',
    '미리보기 다시 확인 중…':'Checking the updated preview…',
    '접촉·무게중심 기준 통과':'Contact / center-of-mass check passed',
    '접촉·무게중심 확인 필요':'Contact / center-of-mass needs review',
    '영역 안에 맞음':'Fits inside the build volume',
    '영역 초과 · 부품을 자르지 않음':'Exceeds the build volume · part kept whole',
    '자동 자세 검토값':'Automatic orientation details',
    '▸ 자동 자세 검토값':'▸ Automatic orientation details',
    '▾ 자동 자세 검토값':'▾ Automatic orientation details',
    '자동 자세 계산 시간 한도를 넘었습니다. 선택 부품 수를 줄이세요.':'Automatic orientation time limit exceeded. Select fewer parts.',
    '자동 자세 표면 계산 한도를 넘었습니다. 선택 부품 수를 줄이세요.':'Automatic orientation mesh limit exceeded. Select fewer parts.',
    '체결 부품 제외 후 출력할 부품이 없습니다. 선택을 확인하세요.':'No print parts remain after fastener exclusion. Check the selection.',
    '출력할 부품을 선택하세요.':'Select parts to print.',
    '자동 자세 각도·계산 시간 한도를 확인하세요.':'Check the automatic orientation angle and time limits.',
})

def translate(text,language):
    if language!='en' or not isinstance(text,str):return text
    if text in EN:return EN[text]
    if text.startswith('자동 자세에 유효한 표면이 필요합니다: '):return 'Automatic orientation needs a valid surface: '+text[len('자동 자세에 유효한 표면이 필요합니다: '):]
    plate=re.fullmatch(r'출력판 (\d+)(?: · (\d+)개 부품)?',text)
    if plate:return 'Plate '+plate[1]+(' · '+plate[2]+' parts' if plate[2] else '')
    count=re.fullmatch(r'선택 (\d+)개 · 출력 (\d+)개 · 출력판 (\d+)개(?: · 볼트·너트 제외 (\d+)개)?',text)
    if count:return f'Selected {count[1]} · Printing {count[2]} · {count[3]} plates'+(f' · {count[4]} bolts/nuts excluded' if count[4] else '')
    excluded=re.fullmatch(r'볼트·너트 제외 (\d+)개',text)
    if excluded:return excluded[1]+' bolts/nuts excluded'
    status=re.fullmatch(r'출력판 (\d+)/(\d+) · (.*)',text)
    if status:return f'Plate {status[1]}/{status[2]} · '+translate(status[3],language)
    model_status=re.fullmatch(r'([A-Za-z0-9._:/+\-]+) · (목록에 없음|연결 확인 전)',text)
    if model_status:return model_status[1]+' · '+('not in catalog' if model_status[2]=='목록에 없음' else 'connection not checked')
    if text.startswith('전장 피처 · '):return 'Electrical feature · '+text[len('전장 피처 · '):]
    if text.startswith('참고자료 ') and 'AI에 전송' in text:return text.replace('참고자료 ','References: ').replace('개',' files').replace('자',' characters').replace('AI에 전송','sent to AI')
    if '\n' in text:return '\n'.join(translate(line,language) for line in text.split('\n'))
    if text.startswith('Codex ') and ('남음' in text or '한도' in text or '잔여량 확인 불가' in text):
        return text.replace('주간','weekly').replace('시간',' hours').replace('분',' minutes').replace('기타 한도','other limit').replace('% 남음','% remaining').replace('초기화','resets').replace('잔여량 확인 불가','remaining usage unavailable')
    if re.fullmatch(r'조회 \d{2}/\d{2} \d{2}:\d{2}',text):return text.replace('조회','Checked',1)
    match=re.fullmatch(r'형상 유효 · (\d+)개 부품 · 체적 ([\d,.]+) mm³ · 간섭 (\d+)건',text)
    if match:return f'Geometry valid · {match[1]} parts · Volume {match[2]} mm³ · {match[3]} interferences'
    if re.match(r'^\d+개 부품',text):
        return re.sub(r'^(\d+)개 부품',r'\1 parts',text).replace(' 선택 · Shift+클릭: 추가/해제 · Shift+드래그: 범위 추가 · Ctrl+G: 그룹',' selected · Shift+click: toggle · Shift+drag: add range · Ctrl+G: group')
    return text


class UILanguage(QObject):
    def __init__(self,app,path):
        super().__init__(app);self.app=app;self.path=Path(path);self.language='ko';self.active=False
        try:self.language=json.loads(self.path.read_text(encoding='utf-8')).get('language','ko')
        except (OSError,ValueError,AttributeError):pass
        if self.language not in ('ko','en'):self.language='ko'
        self.refresh=QTimer(self);self.refresh.setSingleShot(True);self.refresh.timeout.connect(self.flush)
        app.installEventFilter(self)

    def field(self,obj,key,get,setter):
        current=get();records=getattr(obj,'_cad_translations',{});old=records.get(key)
        source=old[0] if old and current==old[1] else current
        target=translate(source,self.language)
        if current!=target:
            blocked=obj.blockSignals(True)
            try:setter(target)
            finally:obj.blockSignals(blocked)
        records[key]=(source,target);obj._cad_translations=records

    def apply(self,obj):
        if not isValid(obj):return
        if isinstance(obj,QAction):
            self.field(obj,'text',obj.text,obj.setText);self.field(obj,'tip',obj.toolTip,obj.setToolTip);return
        if not isinstance(obj,QWidget):return
        self.field(obj,'title',obj.windowTitle,obj.setWindowTitle);self.field(obj,'tip',obj.toolTip,obj.setToolTip)
        if isinstance(obj,(QLabel,QAbstractButton)) and not obj.property('cadUserText'):self.field(obj,'text',obj.text,obj.setText)
        if isinstance(obj,QGroupBox):self.field(obj,'group',obj.title,obj.setTitle)
        if isinstance(obj,(QLineEdit,QPlainTextEdit)):self.field(obj,'placeholder',obj.placeholderText,obj.setPlaceholderText)
        if isinstance(obj,QComboBox) and not obj.isEditable() and not obj.property('cadUserText'):
            # Only catalogue matches change display strings; IDs / itemData are untouched.
            for i in range(obj.count()):self.field(obj,'item'+str(i),lambda i=i:obj.itemText(i),lambda value,i=i:obj.setItemText(i,value))
        if isinstance(obj,QTabWidget):
            for i in range(obj.count()):self.field(obj,'tab'+str(i),lambda i=i:obj.tabText(i),lambda value,i=i:obj.setTabText(i,value))
        if isinstance(obj,QTableWidget):
            for i in range(obj.columnCount()):
                item=obj.horizontalHeaderItem(i)
                if item:self.field(obj,'header'+str(i),item.text,item.setText)
        # Tree/table/list contents and editable fields may contain user names,
        # prompts, paths or history. Do not translate them.
        for action in QWidget.actions(obj):self.apply(action)

    def eventFilter(self,obj,event):
        if self.active:return False
        self.active=True
        try:
            if event.type() in (QEvent.Type.Show,QEvent.Type.LayoutRequest,QEvent.Type.ActionChanged) and not self.refresh.isActive():self.refresh.start(0)
        finally:self.active=False
        return False

    def flush(self):
        self.active=True
        try:
            for widget in self.app.allWidgets():self.apply(widget)
        finally:self.active=False

    def set_language(self,language,persist=True):
        if language not in ('ko','en'):raise ValueError('Unsupported UI language')
        if persist:
            self.path.parent.mkdir(parents=True,exist_ok=True);temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps({'language':language}),encoding='utf-8');temporary.replace(self.path)
        self.language=language;self.flush()


def install_language(path):
    app=QApplication.instance();service=getattr(app,'cad_language',None)
    if service is None:service=UILanguage(app,path);app.cad_language=service
    return service

EN.update({'회로도':'Circuit', '메인 회로도 작업 공간':'Main circuit workspace'})
EN.update({'BOM 보고 설계…':'Design from BOM…',
           '선택 CAD 부품을 BOM 행에 연결…':'Link selected CAD parts to a BOM row…',
           'BOM 없음':'No BOM',
           'CAD 파일 열기 연결…':'CAD file opening…',
           'CAD 파일 연결 등록':'Register CAD file opening',
           'Windows 기본 앱 설정…':'Windows default apps…',
           '이 앱의 연결 등록 해제':'Remove this app registration',
           'AI로 검증 수정 계속':'Continue AI validation repair'})
EN.update({'✓ Codex 연결 완료 · 모델 선택됨':'✓ Codex connected · model selected',
           '선택 핀 연결 해제':'Disconnect selected pin',
           '부품 드래그: 배치 · 선택 편집: 모델 변경 · 핀 연결 버튼으로 배선':'Drag: arrange · Edit selected: change model · Wire pins: connect',
           '부품 드래그: 배치 · 시작/대상 핀 클릭: 연결 · 선택 편집: 모델/정격 변경 · 실물 몸체 클릭: 확대/CAD 보기.':'Drag: arrange · source/target pins: wire · Edit selected: model/ratings · click physical body: focus/CAD.'})
EN.update({
    'Codex 모델 선택…':'Choose Codex model…',
    '연결 후 모델 목록을 불러옵니다':'Connect to load the model catalog',
    'Codex가 반환한 모델 목록입니다. 모델 접근 권한은 실제 요청 시 확인됩니다. 선택만으로 요청하지 않습니다.':'Model catalog reported by Codex. Access is checked on the actual request. Selecting a model does not start a request.',
})
EN.update({
    '커패시터 / 콘덴서':'Capacitor', '코일 / 인덕터':'Coil / inductor', '액추에이터':'Actuator',
    '액추에이터 · 정격 등가 부하':'Actuator · rated equivalent load',
    '구동 시뮬레이션…':'Drive simulation…',
    '모터 / 엔코더 · 폐루프 시뮬레이션…':'Motor / encoder · closed-loop simulation…',
    '부품 제품 스펙 / 구매 링크…':'Part product specifications / purchase links…',
    '제품 스펙 / 공식 자료 / 구매 링크…':'Product specifications / official references / purchase links…',
    '제품 자료를 연결할 부품을 선택하세요.':'Select a part to attach product references.',
    '모델을 바꾸면 이 부품의 기존 핀 연결을 해제합니다. 계속할까요?':'Changing the model clears this component’s existing pin connections. Continue?',
    '정전 용량':'Capacitance', '인덕턴스':'Inductance', '코일 DC 권선 저항':'Coil DC winding resistance',
    '극성 커패시터 · 첫 단자가 +':'Polarized capacitor · first terminal is +',
    '정격 전압 · 커패시터 0은 미입력':'Rated voltage · 0 means unspecified for a capacitor',
    '커패시터는 DC 정상 상태에서 개방, 코일은 입력한 권선 저항으로 계산합니다. 충방전·역기전력·AC·PWM 구동 해석은 포함하지 않습니다.':'Capacitors are open at steady DC; coils use the entered winding resistance. Charging, flyback, AC and PWM drive behavior are not simulated.',
})
