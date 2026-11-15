# VS Code 익스텐션 설치·배포 안내

Theseus VS Code 익스텐션(`backend/theseus-core-server/vscode-extension`)을 저장소에서 빌드해 설치하고, 다른 PC로 배포하는 절차입니다.
설치·패키징 wrapper는 [`scripts/vscode-extension/`](../scripts/vscode-extension/)에 있고, 실제 로직은 [`backend/theseus-core-server/scripts/`](../backend/theseus-core-server/scripts/)의 PowerShell/셸 스크립트입니다.
Package wrapper는 Git Bash·Linux용 `.sh`(`Package-Theseus-LocalExtension.sh`, `Package-Theseus-TestPackage.sh`)도 함께 있습니다.

## 빠른 시작

VS Code `^1.90.0`, Python 3.11, Node.js/npm을 준비하고 저장소 루트에서 실행합니다. 이미 저장소를 받았다면 Clone 단계는 생략합니다.

```powershell
git clone https://github.com/karneva/Theseus.git
Set-Location Theseus
Push-Location backend/theseus-core-server/vscode-extension
npm.cmd ci
npm.cmd run package:vsix
Pop-Location
.\scripts\vscode-extension\Install-Theseus-Extension.cmd -Ide vscode
```

설치기는 이미 빌드된 VSIX를 설치하므로 **패키징이 성공한 것을 확인한 뒤** 실행합니다. 설치 후 LLM 모델과 API 키를 설정하고([3-5](#3-5-llm-모델과-api-키-설정)), VS Code에서 작업 폴더를 열어 `Theseus: Start Agent`를 실행합니다.

명령은 별도 표시가 없으면 **Windows PowerShell** 기준입니다.

## 1. 구성과 설치 방식

```text
VS Code → Theseus Extension → 로컬 Daemon → Theseus Agent Engine → LLM Provider
                                  └─ 선택한 프로젝트의 코드·도구
```

익스텐션이 데몬을 직접 실행합니다. 로컬 데몬은 `127.0.0.1`의 빈 포트를 자동 선택하며, 작업 공간의 `.theseus/runner.json`에 연결 정보를 기록합니다. 웹 Core Server의 `8086` 포트와 별개이므로 익스텐션 사용을 위해 FastAPI 서버를 따로 시작할 필요가 없습니다.

| 방식 | 실행 환경 | 사용 목적 |
| --- | --- | --- |
| 소스 설치 / `source-python` | VSIX + Python 가상환경 + `theseus_engine` 소스 | 개발, 엔진 수정, 소스와 함께 배포 |
| 실행 파일 설치 / `bundled-runner` | VSIX + `theseus-runner.exe`와 동봉 파일 | Windows 테스트 배포 |
| 자동 선택 / `auto` | `runnerPath`가 있으면 실행 파일, 없으면 Python 소스 | 기본 런타임 선택 |

`theseus.serverUrl`을 빈 문자열로 두면 Standalone 모드입니다. 기본 로컬 실행에는 웹용 API Server, MySQL, Redis, Kafka의 동시 실행이 필요하지 않습니다. 외부 서버나 별도 도구가 필요한 기능은 해당 연결과 의존성을 추가로 준비합니다.

## 2. 준비 환경

| 항목 | 준비 사항 |
| --- | --- |
| VS Code | 익스텐션 `package.json`의 호환 범위 `^1.90.0` |
| Python | 소스 설치 및 Runner 빌드 환경은 3.11 기준 |
| Node.js / npm | VSIX를 직접 빌드할 때 필요. `npm ci`로 잠금 파일의 의존성 설치 |
| Git | 저장소 Clone 및 소스 갱신 |
| PowerShell | Windows 설치·패키징 스크립트 실행 |
| VS Code CLI | `code` 명령 사용 가능 또는 설치 시 `-Code`로 경로 지정 |
| LLM 설정 | 선택한 모델과 해당 Provider API 키 |

VSIX와 Runner가 이미 포함된 테스트 패키지의 사용자는 VSIX 빌드용 Node.js나 엔진 실행용 Python을 별도로 설치하는 대신 동봉된 Runner를 사용합니다. 실행할 커스텀 도구에 필요한 외부 프로그램은 별도입니다.

```powershell
git --version
python --version
node --version
npm.cmd --version
code --version
```

## 3. 저장소에서 빌드하고 설치하기

### 3-1. 소스 받기

```powershell
git clone https://github.com/karneva/Theseus.git
Set-Location Theseus
```

이후 명령에서 **저장소 루트**는 `Theseus` 폴더입니다. 이미 Clone했다면 해당 폴더에서 시작합니다.

### 3-2. VSIX 빌드

저장소 루트에서 실행합니다.

```powershell
Push-Location backend/theseus-core-server/vscode-extension
npm.cmd ci
npm.cmd run package:vsix
Pop-Location
```

`package:vsix`는 TypeScript 컴파일, 필수 패키지 입력 파일 확인, VSIX 패키징을 수행합니다. 각 명령이 성공했는지 확인한 뒤 다음 단계로 진행합니다.

- 출력 위치: `backend/theseus-core-server/vscode-extension/`
- 파일 이름: `theseus-vscode-<version>.vsix`
- 현재 Manifest 버전: `0.0.1`
- 익스텐션 ID: `theseus.theseus-vscode`

설치기는 VSIX를 자동 빌드하지 않습니다. VSIX가 여러 개라면 수정 시각이 가장 최근인 파일을 선택하므로, 특정 파일을 설치하려면 `-VsixPath`를 지정합니다.

### 3-3. 설치기 실행

저장소 루트에서 실행합니다.

```powershell
.\scripts\vscode-extension\Install-Theseus-Extension.cmd -Ide vscode
```

설치기는 Core 폴더의 `.venv` 생성, `requirements.txt` 설치, VS Code 설정 반영, VSIX 설치를 수행합니다. `uv`가 있으면 Python 3.11 가상환경 생성에 사용하고, 없으면 `python` 또는 `-Python`으로 지정한 실행 파일을 사용합니다.

기본 설정 파일은 작업 공간의 `.vscode/settings.json`입니다. 설치기가 `theseus.*` 항목을 다시 작성하므로 기존 Theseus 연결 설정은 설치 후 확인합니다.

Theseus 저장소가 아닌 다른 프로젝트에서 사용하려면 **이미 존재하는 프로젝트 폴더**를 지정합니다.

```powershell
.\scripts\vscode-extension\Install-Theseus-Extension.cmd -Ide vscode -WorkspacePath "C:\DEV\my-project"
```

| 옵션 | 용도 |
| --- | --- |
| `-CorePath "경로"` | `theseus_engine`과 `requirements.txt`가 있는 Core 폴더 지정 |
| `-WorkspacePath "경로"` | 분석·작업 대상 프로젝트 폴더 지정 |
| `-Python "경로"` | 가상환경 생성에 사용할 Python 실행 파일 지정 |
| `-Code "경로"` | 자동 감지되지 않는 VS Code CLI 지정 |
| `-VsixPath "경로"` | 설치할 VSIX를 명시 |
| `-SkipRequirements` | 기존 가상환경의 의존성 재설치 생략 |
| `-SkipExtension` | VSIX 설치 생략 |
| `-SkipSettings` | IDE 설정 작성 생략 |
| `-InstallPlaywright` | 브라우저 도구용 의존성과 Chromium 추가 설치 |

예를 들어 VS Code CLI가 PATH에 없다면 다음처럼 지정합니다.

```powershell
.\scripts\vscode-extension\Install-Theseus-Extension.cmd -Ide vscode -Code "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd"
```

VS Code가 다른 위치에 설치되어 있으면 실제 경로로 바꿉니다. 이미 다른 런타임을 사용하던 환경이라면 아래 설정에서 `runtimeMode`와 `runnerPath`도 확인합니다.

### 3-4. 수동 설정 확인

VS Code에서 `Preferences: Open Workspace Settings (JSON)`을 열고 다음 항목을 확인합니다. 아래 예시는 저장소를 `C:/DEV/Theseus`에, 작업할 프로젝트를 `C:/DEV/my-project`에 둔 경우입니다.

```json
{
  "theseus.runtimeMode": "source-python",
  "theseus.corePath": "C:/DEV/Theseus/backend/theseus-core-server",
  "theseus.pythonPath": "C:/DEV/Theseus/backend/theseus-core-server/.venv/Scripts/python.exe",
  "theseus.workspacePath": "C:/DEV/my-project",
  "theseus.runnerPath": "",
  "theseus.serverUrl": "",
  "theseus.readyTimeoutSeconds": 60
}
```

| 설정 | 의미 |
| --- | --- |
| `corePath` | 엔진 설치 위치. 작업 대상 프로젝트와 달라도 됨 |
| `pythonPath` | 의존성이 설치된 가상환경의 Python 실행 파일 |
| `workspacePath` | 작업 대상. 비어 있으면 VS Code의 첫 번째 작업 공간 폴더 사용 |
| `runtimeMode` | `auto`, `source-python`, `bundled-runner` 중 선택 |
| `runnerPath` | `bundled-runner` 실행 파일 경로 |
| `serverUrl` | 외부 서버 연동 주소. 로컬 Standalone은 빈 문자열 |
| `readyTimeoutSeconds` | 준비 대기 시간. 기본 60초, 허용 범위 1~60초 |

경로 설정은 `${workspaceFolder}`, `${userHome}`, `${env:NAME}` 치환을 지원합니다. Theseus 저장소 자체가 작업 공간일 때에는 `corePath`를 `${workspaceFolder}/backend/theseus-core-server`로 쓸 수 있습니다.

### 3-5. LLM 모델과 API 키 설정

소스 설치에서는 `backend/theseus-core-server/.env`에 사용할 모델과 해당 Provider 키를 설정합니다. 기존 파일이 있으면 필요한 값만 수정합니다.

```dotenv
THESEUS_MODEL=<사용 가능한 모델 ID>
GEMINI_API_KEY=<발급받은 키>
```

위 키 이름은 Gemini 사용 예시입니다. 엔진이 사용하는 Provider에 맞춰 아래 중 필요한 키를 설정합니다.

| Provider | 환경 변수 |
| --- | --- |
| Gemini | `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Ollama(로컬) | 키 없음. `THESEUS_MODEL=ollama/<모델>`, 필요하면 `OLLAMA_BASE_URL`(기본 `http://localhost:11434/v1`) |

`THESEUS_MODEL`은 해당 Provider에서 실제 사용할 수 있고 엔진이 인식하는 모델 ID로 지정합니다. 코드에 기본 모델이 지정되어 있어도 계정의 접근 가능 여부는 별도이므로 배포 환경에 맞춰 설정합니다.

Runner 배포에서는 `theseus-runner.exe`와 같은 폴더의 `.env` 또는 작업 공간의 `.env`를 사용할 수 있습니다. 프로세스에 이미 설정된 환경 변수는 `.env`로 덮어쓰지 않습니다. 키 파일은 저장소나 배포 ZIP에 포함하지 말고 설치 환경에서 설정합니다.

설정 변경 후에는 `Theseus: Stop Agent` → `Theseus: Start Agent`로 재시작합니다. 시스템 환경 변수를 바꿨다면 VS Code도 완전히 종료한 뒤 다시 엽니다.

## 4. 최초 실행과 동작 확인

1. VS Code에서 작업 대상 폴더를 엽니다.
2. Activity Bar의 **Theseus**를 선택합니다.
3. 명령 팔레트에서 `Theseus: Start Agent`를 실행합니다.
4. `Theseus: Show Logs`로 엔진 시작 로그와 오류 여부를 확인합니다.
5. “현재 프로젝트의 디렉터리 구조를 설명해 줘”처럼 코드 조회 요청을 보냅니다.
6. 코드를 선택해 `Theseus: Explain Selection`을 실행하고 선택한 파일의 문맥이 전달되는지 확인합니다.
7. 편집 기능은 테스트용 파일에서 `Theseus: Inline Edit`를 실행한 뒤 변경 사항을 확인합니다.

Inline Edit 단축키는 Windows/Linux `Ctrl+I`, macOS `Cmd+I`이며 에디터에 포커스가 있을 때 적용됩니다.

| 확인 항목 | 기대 결과 |
| --- | --- |
| 익스텐션 설치 | Extensions에서 Theseus를 찾을 수 있음 |
| 런타임 시작 | 설정한 Python 또는 Runner가 실행되고 데몬이 준비됨 |
| 프로젝트 경로 | 현재 분석 대상이 지정한 `workspacePath`와 일치 |
| LLM 연결 | 선택한 Provider의 인증 오류 없이 응답 수신 |
| 에디터 연동 | 선택 코드 설명과 테스트 파일 편집 동작 확인 |
| 종료·재시작 | Stop 후 Start가 정상 동작 |

`.theseus/runner.json`에는 연결 인증 정보가 포함되므로 파일 내용을 공개 로그나 이슈에 붙이지 않습니다.

## 5. 다른 PC로 배포하기

### 5-1. 엔진 소스를 포함한 배포

VSIX 빌드 의존성 설치가 끝난 환경에서 저장소 루트의 다음 명령을 실행합니다.

```powershell
.\scripts\vscode-extension\Package-Theseus-LocalExtension.cmd
```

래퍼는 VSIX 빌드를 요청한 뒤 필요한 엔진 소스와 설치 스크립트를 묶습니다.

```text
backend/theseus-core-server/dist/local-extension-package/
└── Theseus-LocalExtensionSourcePackage.zip
```

배포물에는 `theseus_engine`, `theseus_cli`, 의존성 목록, VSIX와 설치·제거 스크립트 등이 포함됩니다. 웹 Frontend/API Server, 개발 가상환경, 테스트와 실제 `.env`는 포함하지 않습니다.

받는 PC에서는 ZIP 전체를 고정된 위치에 압축 해제하고, 패키지 루트의 `Install-Theseus-Extension.cmd -Ide vscode`를 실행합니다. Python 3.11을 준비하고 API 키를 별도로 설정합니다. 이미 빌드된 VSIX를 설치하므로 수신자가 VSIX를 다시 빌드할 필요는 없습니다.

### 5-2. Runner 실행 파일을 포함한 테스트 배포

빌드 PC에 Core 가상환경과 의존성이 준비되어 있어야 합니다. 3장의 소스 설치를 완료한 환경에서 진행하거나, IDE 설치 없이 아래처럼 빌드 환경만 준비할 수 있습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backend\theseus-core-server\scripts\install-vscode-extension.ps1 -SkipExtension -SkipSettings
```

익스텐션 폴더에서 `npm.cmd ci`를 완료한 뒤 저장소 루트에서 실행합니다.

```powershell
.\scripts\vscode-extension\Package-Theseus-TestPackage.cmd -BuildRunner -InstallPyInstaller
```

VSIX와 PyInstaller 기반 Runner를 빌드하고 다음 ZIP을 생성합니다. 이미 Runner를 빌드했다면 `-BuildRunner`를 생략할 수 있지만, 이 경우 기존 실행 파일이 있어야 합니다.

```text
backend/theseus-core-server/dist/test-package/Theseus-TestPackage.zip

Theseus-TestPackage/
├── README.md
├── Install-Theseus-TestPackage.cmd
├── scripts/
│   └── install-test-package.ps1
├── theseus-vscode-0.0.1.vsix
└── theseus-runner/
    ├── theseus-runner.exe
    └── _internal/
```

버전에 따라 VSIX 이름은 달라집니다. 기본 Runner 빌드는 디렉터리 단위 배포이므로 `.exe`만 복사하지 말고 `_internal`을 포함한 전체 패키지를 전달합니다. 이 `.exe` 배포 절차는 Windows 대상입니다.

받는 PC에서는 ZIP을 압축 해제한 뒤 **압축 해제된 패키지 루트에서** 실행합니다.

```powershell
.\Install-Theseus-TestPackage.cmd -Ide vscode -WorkspacePath "C:\DEV\my-project"
```

설치기는 VSIX 설치, `runtimeMode=bundled-runner`, `runnerPath`, `workspacePath` 설정 후 IDE를 엽니다. API 키와 모델 설정을 마친 뒤 4장의 절차로 검증합니다. 패키지 폴더를 옮기거나 삭제하면 설정된 실행 파일 경로가 끊어지므로 계속 사용할 위치에 보관합니다.

### 5-3. 소스 설치용 Bash 스크립트

소스 방식은 [Bash 설치기](../backend/theseus-core-server/scripts/install-vscode-extension.sh)도 제공합니다. Python 환경과 VSIX를 준비한 후 Core 폴더에서 실행합니다.

```bash
bash scripts/install-vscode-extension.sh --ide vscode --workspace-path /path/to/project
```

Bash 옵션은 `--workspace-path`, `--code`처럼 표기합니다. Windows PowerShell의 `-WorkspacePath`와 혼용하지 않습니다. 이 경로는 소스 Python 실행 방식이며 Windows Runner 실행 파일을 다른 OS에서 실행하는 절차가 아닙니다.

## 6. 업데이트와 설치 위치 변경

- **익스텐션 코드 변경**: `npm.cmd ci`와 `npm.cmd run package:vsix`를 다시 수행하고 새 VSIX를 설치합니다.
- **소스 엔진 변경**: Core 소스를 갱신하고 의존성이 바뀌었다면 설치기로 재설치한 뒤 Agent를 재시작합니다.
- **Runner 엔진 변경**: `-BuildRunner`를 포함해 테스트 패키지를 다시 만듭니다. VSIX 교체만으로 기존 Runner의 엔진 코드가 갱신되지는 않습니다.
- **다른 프로젝트 사용**: 설치 시 `-WorkspacePath`를 지정하거나 `Theseus: Select Workspace (Worktree)`를 사용합니다.
- **폴더 이동**: `corePath`, `pythonPath`, `runnerPath`, `workspacePath`를 새 위치에 맞춰 수정하거나 설치기를 다시 실행합니다.
- **런타임 변경**: 소스 방식은 `source-python`으로 설정하고 `runnerPath`를 비웁니다. 실행 파일 방식은 `bundled-runner`와 유효한 `runnerPath`를 설정합니다.

업데이트 후 VS Code의 `Developer: Reload Window`를 실행하고 4장의 확인 절차를 반복합니다.

## 7. 문제 해결

| 증상 | 확인 및 해결 |
| --- | --- |
| `VSIX package was not found` | 3-2 빌드 성공 여부와 출력 파일 확인. 필요하면 `-VsixPath` 지정 |
| `Missing VSIX package inputs` | 익스텐션 폴더에서 컴파일하고 오류에 나온 `out/`, `media/`, `resources/` 파일 확인 |
| `code` 명령을 찾지 못함 | VS Code CLI 경로를 `-Code`로 지정 |
| `Cannot find theseus_engine/` | `corePath`가 엔진 패키지 자체가 아닌 그 상위 Core 폴더인지 확인 |
| `ModuleNotFoundError` | `pythonPath`가 의존성을 설치한 `.venv`의 Python인지 확인 |
| `bundled-runner`인데 실행 파일을 못 찾음 | `runnerPath`의 파일 존재 여부와 압축 해제 위치 확인 |
| Agent 준비 시간 초과 | `Theseus: Show Logs`에서 기동 오류 확인. 대기 설정 최대값은 60초 |
| LLM 인증 또는 모델 오류 | 선택 모델과 Provider 키가 일치하는지, 계정에 모델 접근 권한이 있는지 확인 후 재시작 |
| 잘못된 프로젝트를 분석함 | `workspacePath` 및 Worktree 선택 확인. 다중 폴더에서는 첫 폴더가 기본값 |
| 브라우저 도구 실행 실패 | 소스 설치기 `-InstallPlaywright`로 의존성과 Chromium 설치 |
| 설치 후 이전 화면이 보임 | 새 VSIX 설치 여부 확인 후 `Developer: Reload Window` 실행 |

수동으로 소스 데몬의 시작 오류를 확인하려면 **Core 폴더에서** 다음을 실행합니다. IDE에서 실행 중인 Agent는 먼저 중지합니다.

```powershell
.\.venv\Scripts\python.exe -m theseus_engine.daemon --workspace "C:\DEV\my-project" --host 127.0.0.1 --port 0
```

이 명령은 진단을 위한 별도 실행이며, 정상 사용 시에는 익스텐션의 `Start Agent`가 데몬을 시작합니다. 확인을 마치면 `Ctrl+C`로 종료합니다.

## 8. 제거

익스텐션만 제거하려면 VS Code Extensions 화면에서 Theseus를 제거하거나 다음 명령을 실행합니다.

```powershell
code --uninstall-extension theseus.theseus-vscode
```

저장소의 `scripts/vscode-extension/Uninstall-Theseus-VSCode.cmd`는 확장 데이터와 설정까지 정리합니다. 기본 옵션은 작업 공간의 `.vscode` 폴더 전체와 Core `.venv`도 삭제하므로, 해당 파일을 보존하려면 다음 옵션을 사용합니다. 먼저 제거 대상을 미리 확인합니다.

```powershell
.\scripts\vscode-extension\Uninstall-Theseus-VSCode.cmd -WorkspacePath "C:\DEV\my-project" -KeepVenv -KeepWorkspaceVscode -DryRun -NoPause
```

출력된 대상이 의도한 환경인지 확인한 뒤 같은 명령에서 `-DryRun`을 제거하면 실제 정리가 진행됩니다. `-KeepWorkspaceVscode`를 지정해도 `settings.json`의 `theseus.*` 설정은 제거 대상입니다.

## 9. 구현 기준 문서와 파일

- [익스텐션 Manifest](../backend/theseus-core-server/vscode-extension/package.json): 호환 버전, 명령, 설정, 빌드 스크립트
- [Core README](../backend/theseus-core-server/README.md): 엔진과 익스텐션 실행 안내
- [Windows 설치기](../backend/theseus-core-server/scripts/install-vscode-extension.ps1): 가상환경, VSIX 및 IDE 설정
- [소스 배포 패키저](../backend/theseus-core-server/scripts/package-local-extension-source.ps1)
- [Runner 빌더](../backend/theseus-core-server/scripts/build-runner-binary.ps1)
- [테스트 배포 패키저](../backend/theseus-core-server/scripts/package-test-distribution.ps1)
- [테스트 패키지 설치 안내](../backend/theseus-core-server/scripts/test-package-README.md)

이 문서는 저장소 구현과 명령·경로를 대조한 설치 안내입니다. 배포 환경별 실행 성공 여부는 실제 대상 PC에서 4장의 절차로 확인합니다.
