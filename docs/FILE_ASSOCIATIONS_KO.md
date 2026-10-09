# Windows에서 .pcad 프로젝트 열기

Prompt CAD Studio의 기본 프로젝트 확장자는 **.pcad**입니다. 프로젝트 내용은 기존 CAD JSON과 같은 형식이므로 파일 이름을 .cad.json에서 .pcad로 바꾸어도 설계, 저장한 코드와 작업 기록은 유지됩니다. 앱은 이전 .cad.json도 계속 읽을 수 있습니다.

ZIP 전체를 푼 폴더의 **Install.ps1**을 실행하면 현재 Windows 사용자에게 .pcad 파일 형식을 등록하고 바탕화면 바로가기를 만듭니다. 관리자 권한이나 실행 정책 변경은 필요하지 않습니다. PowerShell 스크립트를 실행할 수 없는 환경에서는 앱의 **도움말 → CAD 파일 열기 연결…**을 사용하세요.

기존 .pcad 기본 앱이나 Windows 사용자 선택이 없으면 .pcad의 기본 열기 명령이 이 설치의 Prompt CAD Studio를 가리킵니다. 프로젝트를 더블 클릭하면 앱에 파일 경로를 전달합니다. 명령줄에서는 다음처럼 열 수 있습니다.

```text
PromptCADStudio.exe --open "C:\설계\조립체.pcad"
```

이미 다른 .pcad 기본 앱이나 보호된 사용자 선택이 있으면 보존합니다. 이 경우 **도움말 → Windows 기본 앱 설정…**에서 **.pcad**를 찾아 Prompt CAD Studio를 직접 선택하세요. Install.ps1 -OpenDefaultApps로도 해당 설정을 열 수 있습니다. Windows가 앱별 설정 페이지를 지원하지 않으면 기본 앱 목록이 열립니다. 설치와 업데이트는 보호된 UserChoice를 직접 고치거나 해시를 만들어 우회하지 않습니다.

이전 **.cad.json** 파일에는 파일 이름 조건이 있는 **Prompt CAD Studio로 열기** 우클릭 동작이 제공됩니다. Windows 11에서는 **더 많은 옵션 표시**에 나타날 수 있습니다. 이 동작은 기본 열기 동작으로 지정하지 않습니다. Windows는 마지막 .json 확장자를 파일 형식으로 판단하므로 이전 파일의 더블 클릭은 기존 JSON 앱을 사용할 수 있습니다. 일반 .json의 기본 앱을 CAD로 바꿀 필요는 없습니다.

앱은 일반 **.json** 파일 형식의 연결 프로그램 후보나 지원 확장자로 등록하지 않습니다. Windows는 등록된 후보가 하나뿐이면 명시적 기본 앱 값이 없어도 그 후보를 기본 앱처럼 선택할 수 있습니다([Microsoft의 설명](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/export-or-import-default-application-associations?view=windows-11#tip-3)). 이전 등록 형식에서 업데이트할 때는 앱이 등록한 일반 JSON 후보 값이 그대로 남아 있는 경우에만 제거하며, 이후 사용자가 바꾼 값과 보호된 기본 앱 선택은 보존합니다. 이전 .cad.json은 위의 파일 이름 조건이 있는 우클릭 동작으로 계속 열 수 있습니다.

**Remove CAD File Registration.ps1**은 이 설치가 등록한 변경되지 않은 값과 해당 설치를 가리키는 바탕화면 바로가기를 제거합니다. 기존 .pcad 연결, 보호된 사용자 선택, 사용자가 나중에 바꾼 등록 값과 다른 프로그램의 연결은 보존합니다. 프로젝트, 자동 복구 데이터, 앱 파일은 유지합니다. 다른 폴더의 새 설치에 연결을 옮겼다면 이전 설치에서는 새 설치의 연결을 제거할 수 없습니다.

앱 업데이트는 이미 같은 설치 폴더에 등록한 경우에만 등록 상태를 갱신합니다. 폴더를 이동했을 때는 새 위치의 Install.ps1을 다시 실행하세요. 업데이트는 사용자가 나중에 고른 .pcad 기본 앱을 다시 가져오지 않습니다.

## Windows 등록 방식과 검증

.pcad는 [Microsoft의 파일 형식 등록 방식](https://learn.microsoft.com/en-us/windows/win32/shell/fa-file-types)에 따라 앱 전용 ProgID, 아이콘과 따옴표로 감싼 실행 파일 및 파일 인수로 등록합니다. 현재 사용자 범위에만 쓰며 기존 사용자·컴퓨터 범위 .pcad 기본 연결과 UserChoice의 존재를 먼저 확인합니다.

Windows 기본 앱 변경은 [공식 기본 앱 플랫폼](https://learn.microsoft.com/en-us/windows/apps/develop/windows-integration/default-apps-platform)의 사용자 선택을 따릅니다. 앱은 [공식 기본 앱 설정 URI](https://learn.microsoft.com/en-us/windows/apps/develop/launch/launch-default-apps-settings)를 제공합니다. .pcad가 별도 확장자이므로 선택이 일반 JSON에 적용되지 않습니다.

등록·반복 등록·해제·실패 복원 테스트는 기존 .pcad 기본 앱, 컴퓨터 범위 연결, 보호된 사용자 선택, 일반 .json 연결과 나중에 변경한 값을 보존하는지 확인합니다. 릴리스 설치 검증은 작업 공간의 .pcad와 일반 JSON 파일에 대해 탐색기의 기본 동작과 실제 연결 명령을 읽어 확인합니다. 검증 과정에서 CAD 프로젝트나 장치 코드를 실행하지 않습니다.

이전 등록에서 갱신하는 검증은 일반 JSON 후보 정리, 나중에 변경한 값의 보존, 등록 실패 시 이전 값과 소유 정보의 복원을 확인합니다. 레지스트리의 명시적 기본 값이 같다는 사실만으로 탐색기의 실제 기본 앱이 유지됐다고 판단하지 않습니다.
