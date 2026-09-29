"""Local UI catalogue. User-entered text and CAD documents are never translated."""
import json
import re
from pathlib import Path
from PySide6.QtCore import QObject,QEvent,QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication,QWidget,QLabel,QAbstractButton,QComboBox,QGroupBox,QLineEdit,QPlainTextEdit,QTabWidget,QTableWidget,QTreeWidget
from shiboken6 import isValid


PAIRS = '''AI로 간섭 수정 계속|Continue AI interference repair
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

def translate(text,language):
    if language!='en' or not isinstance(text,str):return text
    if text in EN:return EN[text]
    if '\n' in text:return '\n'.join(EN.get(line,line) for line in text.split('\n'))
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
