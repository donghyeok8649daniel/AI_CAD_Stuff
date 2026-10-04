# 이전 전장 프로젝트 열기 수정 · 2.18.1

2.18.0에서 새로 추가한 전장 기본 필드가 예전 프로젝트의 작업 이력에는 없을 수 있습니다. 파일 열기 중 기본 필드가 추가되는 것을 형상·구속 변경으로 판단하던 오류를 수정했습니다. 파일을 편집하거나 작업 기록을 지우지 않고 원본을 그대로 열 수 있습니다.

수정은 예전 전장 항목에 없는 새 기본 필드에만 적용됩니다. 새 파일에 명시된 기본값과 기본값이 아닌 분석 여부·모델·핀 연결·등록 정보는 보존합니다. 이력의 실제 이전 값, 현재 형상과 구속, 잘못된 분기 및 경로에 대한 검사는 유지합니다. 파일 열기 실패 시 현재 열린 설계는 바뀌지 않습니다.

업데이트하려면 작업을 저장하고 CAD 창을 모두 닫은 뒤 설치·업데이트 프로그램을 실행하세요. 프로젝트 원본은 그대로 보관하세요. 이번 재현에 사용한 비공개 프로젝트·화면·파일 이름은 공개 배포물에 넣지 않았습니다.

## English

Version 2.18.1 fixes legacy electrical project loading. New default fields stay absent when they were absent from an older journal snapshot. Explicit defaults and non-default values in newer files are retained. Geometry, assembly constraints, circuit connections, history IDs and branches remain validated; the fix does not discard history or accept inconsistent designs. Close all CAD windows after saving before running the updater.
