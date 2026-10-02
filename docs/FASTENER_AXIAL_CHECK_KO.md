# 볼트 축방향 인장 사전 검토

이 도구는 사용자가 **실제 총 축방향 인장 하중(N)**, 같은 하중을 받는 **동일 볼트 개수**, **안전계수**를 입력했을 때만 계산합니다. 빈 값을 임의의 기계 하중이나 CAD 치수로 채우지 않습니다. 사용자는 동일 볼트가 하중을 균등하게 나눈다는 가정을 직접 확인해야 합니다.

자료 범위는 **ISO 898-1 강재 볼트의 보통 피치 M4·M5·M6·M8, 강도 등급 8.8 또는 10.9**입니다. 볼트의 나사부가 순수한 정적 축인장을 받으며, 실물의 크기·피치·등급·표면 처리가 선택값과 일치해야 합니다. 낮은 머리나 접시머리처럼 증명하중 적용에 영향을 줄 수 있는 형상이 아니라는 확인도 필요합니다. 실온 시험에 근거한 증명하중 값이며, 실제 조립체의 허용 운전 하중이나 파단 하중이 아닙니다. M8은 6az 용융아연도금 볼트의 감소 증명하중 대상이 아니라는 확인을 추가로 요구합니다.

| 보통 피치 | 공칭 인장 유효단면적 `As` (mm²) | 8.8급 표기 증명하중 (N) | 10.9급 표기 증명하중 (N) |
| --- | ---: | ---: | ---: |
| M4×0.7 | 8.78 | 5,100 | 7,290 |
| M5×0.8 | 14.2 | 8,230 | 11,800 |
| M6×1 | 20.1 | 11,600 | 16,700 |
| M8×1.25 | 36.6 | 21,200 | 30,400 |

선택 등급의 증명응력 `Sp`는 8.8급 **580 MPa**, 10.9급 **830 MPa**입니다. 입력 총 외력을 `F`, 개수를 `n`, 사용자가 정한 안전계수를 `S`라 하면 볼트당 검토 외력은 `F×S/n`, 검토 인장응력은 `F×S/(n×As)`입니다. 이용률은 `max(검토 인장응력/Sp, 볼트당 검토 외력/제조사 표기 증명하중)`로 계산합니다. 표 값의 반올림 때문에 두 비율 중 큰 값을 적용합니다. 여유율은 `1/이용률 − 1`이며, 이용률이 1 이하여도 **오직 이 축인장 가정에서 증명하중 참조 이내**라는 뜻입니다.

전단, 굽힘, 편심, 볼트 프리로드와 체결 토크, 동적·충격·피로 하중, 나사산 뽑힘, 너트·와셔·모재 강도, FDM 플라스틱 체결부, 볼트 머리 파손, 실제 하중 분포는 계산하지 않습니다. 프리로드를 고려하지 않은 단순 외력 비교는 조립체 설계를 대신하지 않습니다. CAD의 관절이나 구멍 위치에서 하중을 자동 추정하지 않으며, 결과를 부품 안전 승인으로 저장하지 않습니다.

근거는 Bossard의 [강도 등급 4.6~12.9 기술 정보](https://www.bossard.com/ch-en/knowledge-hub/resources/technical-information/screws-property-class-04-to-12/)에서 연결되는 [2025년 1월 공식 PDF](https://assets.eu.ctfassets.net/0vp0u5uh75zd/1VPwGxSRcAQdDRArMtTqeY/8fe01cf6ef692e134b45f895fb69fe97/012_016_Screws_property_class46_Fastening_EN_01_2025.pdf)의 12쪽(증명응력)과 14쪽(공칭 유효단면적·증명하중)입니다. 피치는 Bossard의 별도 [ISO 미터 나사 기술 정보](https://www.bossard.com/au-en/knowledge-hub/resources/technical-information/metric-iso-threads/)에서 연결되는 [2025년 1월 자료](https://assets.eu.ctfassets.net/0vp0u5uh75zd/2tYqENAuufvdsudjM8Qbrc/b3461eaa59c2203d3a8b9509ac24dacf/096_098_Metric_ISOthreads_Fastening_EN_01_2025.pdf) 97쪽을 따릅니다. 2026-10-03에 링크를 확인했습니다. [ISO 898-1:2013](https://www.iso.org/standard/60610.html)은 표준의 적용 범위를 확인하는 별도 공식 문서입니다. PDF 전체 표를 복제하지 않고 이 네 크기의 검토값만 등록했습니다.

구현은 [`cadstudio/fastener_checks.py`](../cadstudio/fastener_checks.py)의 `check_axial_bolts` 및 [`native/fastener_check_dialog.py`](../cadstudio/native/fastener_check_dialog.py)의 `FastenerCheckDialog`에 있습니다. 결과에는 입력값, 사용한 수치, 계산식의 결과, 제외 범위, 공식 출처가 함께 남습니다.
