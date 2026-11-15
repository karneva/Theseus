# VSCode 확장 설치·패키징 스크립트

Theseus VSCode 확장(`backend/theseus-core-server/vscode-extension`)을 로컬에 설치하거나 배포용 패키지로 묶는 wrapper 모음입니다.
실제 로직은 `backend/theseus-core-server/scripts/`의 PowerShell/셸 스크립트에 있고, 여기 있는 파일은 경로를 찾아 그 스크립트를 호출하기만 합니다.

| 파일 | 용도 |
| --- | --- |
| `Install-Theseus-Extension.cmd` | Python venv 준비, 에디터 설정, VSIX 설치를 한 번에 실행합니다(`-Help`로 옵션 확인). |
| `Uninstall-Theseus-VSCode.cmd` | 설치된 확장, `theseus.*` 설정, workspace `.vscode`, core `.venv`를 정리합니다(`-DryRun` 지원). |
| `Package-Theseus-LocalExtension.cmd` / `.sh` | VSIX를 다시 빌드하고 소스 포함 로컬 설치 패키지를 만듭니다. |
| `Package-Theseus-TestPackage.cmd` / `.sh` | VSIX와 runner 바이너리를 묶은 테스트 배포 zip을 만듭니다. |
| `Install-Theseus-TestPackage.cmd` | 테스트 배포 zip을 푼 폴더에서 설치를 시작합니다. |

## 경로 해석 규칙

- 저장소 안에서는 이 디렉터리(`scripts/vscode-extension/`)의 두 단계 위를 저장소 루트로 봅니다.
- `Install-*`, `Uninstall-*` 스크립트는 패키지에 복사되면 패키지 루트에 놓이므로, 자기 옆에 `backend/theseus-core-server`(또는 테스트 패키지의 `scripts/`)가 있으면 그 위치를 먼저 사용합니다.

VSIX 파일은 빌드 산출물이라 저장소에 커밋하지 않습니다(`.gitignore`의 `*.vsix`).
