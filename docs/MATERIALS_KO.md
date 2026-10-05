# 부품 재질과 물성 목록

**재질 / 물성**에서 대상 부품을 체크하고 재질을 검색한 다음 **선택 재질 미리보기 → 설계에 적용**을 누릅니다. 여러 부품에 같은 재질을 지정할 수 있습니다. 기존 재질이 있는 부품은 **기존 재질도 교체**를 직접 체크해야 교체됩니다. 창을 열거나 목록을 검색하는 것만으로 재질이 바뀌지 않습니다. 사용자 색상, 제품 정보, 전장 배선과 CAD 형상은 보존합니다.

직접 입력값은 빈칸을 **미확인(null)**으로 저장하며 밀도는 필수입니다. 기존 사용자 입력 재질은 그대로 열립니다. 출처가 있는 재질의 값을 직접 수정하면 그 항목은 사용자 입력으로 표시하고 목록 인증값으로 취급하지 않습니다. **개별 재질 지정 해제**도 체크한 대상에만 적용됩니다. 새 부품에 PLA나 다른 재질을 일괄 지정하지 않습니다.

## 단위와 사용 범위

| 항목 | 저장 단위 | 사용 |
|---|---|---|
| 밀도 | kg/m³ | 정확한 CAD 체적의 질량·관성 및 기존 동역학 |
| 탄성계수 E / 항복·인장강도 | MPa | 출처·조건 기록; 인장해석에는 별도 명시적 적용 필요 |
| 포아송 비 ν | 무차원 | 미확인일 때 추정하지 않음 |
| 열전도율 | W/(m·K) | 참고 기록; 열해석 자동 실행 없음 |
| 선팽창계수 | 1/K | 자료의 온도 구간·방향 보존 |
| 비열 | J/(kg·K) | 참고 기록 |
| 흡수율 | 질량 % | 자료의 시험 시간·온도 보존; 습도별 팽창·투습·누설 모델 아님 |

목록은 제조사 또는 연구·계량기관 자료를 확인한 **참고 DB**입니다. 로트 성적서, 시편 방향, 가공·열처리·용접·출력 상태, 온도와 환경을 확인해야 합니다. 범위로만 주어진 값은 임의의 단일값을 고르지 않습니다. 미확인 열·강도·포아송 비·습도 물성은 비워 둡니다. 방습 챔버의 밀폐 성능, 압력·피로 수명이나 씰 압축 성능을 인증하지 않습니다.

## 등록 소재와 출처

확인일은 2026-10-06입니다. 프로젝트에 적용하면 출처 URL, 문서 리비전, 원 단위 변환, 온도·방향·시험 조건, 대표값/최소값/범위 구분도 함께 저장됩니다.

| 목록 소재 | 자료와 조건 |
|---|---|
| Al 6061-T6 압출재 | [Kaiser 6061 압출재](https://online.kaiseraluminum.com/depot/PublicProductInformation/Document/1006/Kaiser_Aluminum_Shapes_Soft_Alloy.pdf), [Hydro 6061](https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf). 압출재 조질의 대표 탄성계수와 최소 강도이며 판재·열영향부로 확장하지 않음. |
| S355J2+N 강판 | [SSAB 2422, 2025-01-21](https://www.ssab.com/-/media/files/en/zero/data_sheet_2422_ssab_s355j2n_zero_2025_01_21.pdf), [SSAB 일반 강재 참고값](https://www.ssab.com/en/support/product-material-data/steel/20-questions). 강도는 6–16 mm, 압연 횡방향; 밀도·E는 일반 강재 근사로 구분. |
| 304 / 1.4301 스테인리스 | [Outokumpu Core](https://www.outokumpu.com/en/products/product-ranges/-/media/files/products/core/outokumpu-core-range-datasheet.pdf). EN 냉연 C 제품의 강도; 열 물성은 명시된 20 °C 또는 20–100 °C 조건. |
| PC 투명창 | [Ensinger TECANAT natural](https://www.ensingerplastics.com/en-us/shapes/polycarbonate-tecanat-natural). 미국 ASTM D638, 73 °F; psi를 MPa로 변환. FDM 출력물의 값이 아님. |
| POM-C | [Ensinger stock shapes](https://www.ensingerplastics.com/-/media/ensinger/files/document-teaser-files/brochures/shapes/food-technology-shapes-en.pdf). TECAFORM AH natural, 시험규격과 길이 방향 선팽창 조건 보존. |
| PMMA 아크릴창 | [Ensinger extruded acrylic](https://www.ensingerplastics.com/-/media/ensinger/files/document-teaser-files/uk-documents/datasheet-extruded-acrylic-sheet-en.pdf). 탄성계수는 범위로 보존; 인장강도를 항복강도로 바꾸지 않음. |
| PTFE | [Ensinger TECAFLON PTFE](https://www.ensingerplastics.com/pt-br/semiacabados/tecaflon-ptfe). 독일 stock shapes 자료; 크리프·씰 압축·누설 모델은 미확인. |
| 실리콘 고무 | [Wacker LR 3003/50 A/B, v18](https://www.wacker.com/h/en-us/medias/ELASTOSIL-LR-300350-AB-en-2021.06.30-v18.pdf). 경화·후경화 조건 보존; Shore 경도를 E나 ν로 환산하지 않음. |
| 단결정 Si | [BIPM 자연 Si 밀도 비교](https://www.bipm.org/kcdb/comparison?id=1807), [Hopcroft·Nix·Kenny, 2010](https://people.eecs.berkeley.edu/~pister/147fa15/Resources/Hopcroft10.pdf). 밀도는 표준 구의 명목값이며 웨이퍼 로트값이 아님; E의 결정방향별 참고값을 별도 보관. |

## Si와 인장해석

단결정 Si는 이방성입니다. [100]·[110]·[111] 방향의 E는 참고용으로만 보관하고 등방성 E·ν·항복강도는 null입니다. 웨이퍼 결정면, 하중 방향, 도핑·표면 결함과 취성 파괴를 구분해야 합니다. 현재 등방성 선형 인장 솔버에 Si나 비선형 고무·PTFE를 자동 적용하지 않습니다. 연구 저장소의 계산이나 솔버는 실행하지 않습니다.

인장 해석 창의 **선택 시편의 재질값 가져오기**를 눌러 E·ν·항복강도를 가져올 수 있습니다. 세 값이 모두 확인되어야 하며, Si 등 이방성 재질과 비선형 재질은 거부합니다. 가져온 뒤 **계산 / 갱신 → 조건을 작업 기록에 저장**해야 해당 해석 조건에 적용됩니다. 하중·메시 설정과 기존 저장 조건은 그대로 유지합니다. 입력 범위를 벗어난 값은 조용히 잘라 넣지 않고 오류로 알립니다. 목록에 없는 ν를 자동으로 0.3 또는 0.33으로 채우지 않습니다.

개발용 `tensile_material_values()`는 완전한 등방성 제안값만 반환합니다. `tensile_settings_with_material()`는 MPa → GPa를 변환한 새 설정을 검증하며 저장된 연구·해석 설정을 직접 변경하지 않습니다.

## 저장·성능

기존 네 개의 재질 필드만 있는 CAD JSON과 작업 이력은 추가 기본값 없이 같은 형태로 저장됩니다. 새 목록의 미확인 값은 명시적 null로 보존됩니다. 재질 미리보기는 형상이 같다는 검증 표식이 있는 메시에 한해서 기존 형상과 간섭 결과를 재사용합니다. 물성 변경으로 형상을 다시 만들거나 기존 간섭을 새로 허용하지 않습니다.
