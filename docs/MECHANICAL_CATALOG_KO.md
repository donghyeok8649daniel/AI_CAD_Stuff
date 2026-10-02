# 기계·전원 규격 자료

이 카탈로그는 설계 중 자주 찾는 **정확한 품번 또는 표준 호칭**을 오프라인에서 검색하는 작은 참고 자료입니다. 2026-10-03에 확인한 제조사·표준 발행처 링크, 치수, 조건부 정격을 함께 보관합니다. 검색 창에서는 품번, 제조사, `M6 관통홀`, `AWG18` 같은 말을 입력하고 분류를 좁힐 수 있습니다. 선택 항목의 공식 자료를 열거나, 출처와 주의점까지 담은 AI용 사양 문구를 복사할 수 있습니다.

현재 21개 레코드에는 JST XH·VH, Molex Mini-Fit Jr., Phoenix Contact 1757019/1759017 조합, Kycon KLDLX-A/B, Switchcraft 712A, Belden 전선 6종, ISO 273 medium 관통홀 M4/M5/M6/M8, ISO 4762 소켓머리 외경 M4/M5/M6/M8이 들어 있습니다. 여러 부품이 결합되어야 하는 커넥터는 해당 품번을 함께 표시합니다. 아직 확인하지 않은 crimp 단자나 패널 가공 구멍을 임의로 만들어 넣지 않습니다.

기구 치수는 원문이 뜻하는 변수 그대로 사용합니다. 예를 들어 JST의 `B` 치수는 도면의 B이며 전체 부품 바운딩 박스로 바꿔 읽지 않습니다. Kycon 도면의 Ø8.1 mm는 **동봉 와셔 내경**이지 패널 cutout의 확인값이 아닙니다. ISO 273 medium 관통홀도 FDM 출력물의 실제 제작 오차나 사용자가 고른 PLA 간극 0/0.2 mm와 별개입니다. ISO 4762의 `dK`는 나사 머리 외경이며 완성 카운터보어 지름·깊이는 아닙니다.

전류값은 각 출처의 의미와 조건을 보존합니다. JST XH의 3 A는 AWG 22 조건, VH의 10 A는 AWG 16과 표준형 헤더 조건입니다. Molex의 9 A는 해당 헤더 **접점당 최대값**이고, Phoenix의 12 A는 지정한 두 제품의 **공칭값**입니다. Belden 전선 페이지의 전류는 30 °C 자유공기 중 **단일 도체** 조건이며, 케이스 안의 묶음 배선이나 커넥터의 허용 전류가 아닙니다. 이 수치로 실제 모터·MCU의 소비전류를 자동 설정하지 않습니다.

Belden 항목의 명목 DC 저항은 제조사 원 단위 `Ω/1000 ft`와 환산 `Ω/m`를 모두 보여 줍니다. 배선 전압 강하는 **공급선과 리턴선을 각각** 길이에 포함하고 실제 운전 전류를 지정한 다음 계산해야 합니다. 도체 온도, 단자 접촉 저항, 스위치, PCB 배선 저항은 별도로 다룹니다.

코드 연결점은 [`cadstudio/mechanical_catalog.py`](../cadstudio/mechanical_catalog.py)의 `search_catalog`, `get_catalog_entry`, `get_clearance_hole`, `get_socket_head`, `format_ai_spec`입니다. `get_clearance_hole("M6")`는 `HoleSpec(thread="M6", fit="medium", diameter_mm=6.6, standard="ISO 273:1979", source_url=...)`을 반환합니다. 미등록 나사 크기나 `fine`/`coarse` 요청은 `None`을 반환합니다. `get_socket_head("M6")`는 `HeadSpec.diameter_mm=10.0`을 반환합니다. UI 클래스는 [`cadstudio/native/mechanical_catalog_dialog.py`](../cadstudio/native/mechanical_catalog_dialog.py)의 `MechanicalCatalogDialog(parent, query)`이고, 사용자가 선택해 닫으면 `.entry`와 해당될 때만 `.hole_spec`을 제공합니다. 이 창 자체는 CAD 형상이나 회로를 수정하지 않습니다.

데이터를 늘릴 때는 제품군 값과 특정 품번의 값을 섞지 말고, `SourceRef`의 공식 링크·확인일과 각 `SpecFact`의 단위·정격 종류·조건을 같이 추가합니다. 출처에 없는 하중, 내구 수명, 패널 cutout, 극성, 전선 하네스 ampacity는 빈 상태로 둡니다. 확인 근거와 미확인 사항은 각 레코드의 출처와 주석을 따릅니다.
