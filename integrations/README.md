# Autodesk 네이티브 형식으로 변환

이 패키지는 실제 솔리드 STEP과 변환 도구입니다. F3D/IPT 파일 자체는 Autodesk 프로그램에서 생성합니다. 확장자만 바꾸지 않습니다.

## Fusion → .f3d

1. ZIP을 풀고 Autodesk Fusion을 실행합니다.
2. 유틸리티 → 애드인 → 스크립트 및 애드인에서 **+ / 스크립트 추가**로 `Fusion/PromptCADImport` 폴더를 등록합니다.
3. `PromptCADImport`를 실행하고 `design.step` 및 저장할 `.f3d` 경로를 선택합니다.
4. 스크립트가 새 문서로 STEP을 가져오고 Fusion 공식 ExportManager로 F3D를 저장합니다. 기존 문서는 수정하지 않습니다.

스크립트 등록 없이 Fusion에서 STEP을 연 다음 파일 → 내보내기 → Fusion 아카이브로 저장해도 됩니다. Fusion 설치와 사용 가능한 계정이 필요합니다.

## Inventor → .ipt

Inventor가 설치되고 라이선스가 활성화된 Windows에서 ZIP 폴더를 PowerShell로 연 후:

```powershell
powershell -ExecutionPolicy Bypass -File .\ConvertToIpt.ps1
```

`parts/`의 단일 솔리드 STEP을 각각 열어 새 `parts/IPT-날짜시간/` 폴더에 IPT로 저장합니다. 조립 전체의 네이티브 형식은 `.iam`이므로, 이 도구는 **부품별 IPT**를 생성합니다. STEP이 부품으로 열리지 않는 Inventor 설정에서는 명시적으로 중단합니다. 이때 Inventor에서 STEP 가져오기 옵션을 부품으로 선택하고 다른 이름으로 저장하세요.

## 보존 범위와 검증

솔리드와 배치는 STEP을 거쳐 전달됩니다. 이 앱의 스케치 치수·구속·피처 이력을 Autodesk 이력으로 재구성하지는 않습니다. 원본 편집 데이터는 함께 들어 있는 `design.cad.json`을 보관하세요.

STEP 생성·재불러오기와 패키지 구성은 자동 시험했습니다. F3D/IPT 변환 도구는 공식 API 기반이며 Autodesk 실행 환경에서의 실변환 시험은 아직 수행하지 않았습니다.

공식 API: [Fusion STEP 가져오기](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/core_ImportManager_importToNewDocument.htm), [Fusion F3D 저장](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/fusion_ExportManager_createFusionArchiveExportOptions.htm), [Inventor SaveAs](https://help.autodesk.com/cloudhelp/2022/ENU/Inventor-API/files/PartDocument_SaveAs.htm).
