# 기여 가이드

Theseus에 기여해 주셔서 감사합니다. 이 문서는 브랜치, 커밋, PR 규칙과 PR 전에 확인할 항목을 정리합니다.

## 저장소 구성

| 경로 | 내용 | 주요 도구 |
| --- | --- | --- |
| `backend/theseus-api-server` | Spring Boot API 서버 | JDK 21, Gradle |
| `backend/theseus-core-server` | FastAPI Core 서버와 `theseus_engine` | Python 3.11 |
| `frontend` | React 웹 클라이언트 | Node(`frontend/.nvmrc`), npm |
| `infra/docker` | docker compose 구성 | Docker |
| `scripts/vscode-extension` | VSCode 확장 설치·패키징 wrapper | Windows cmd, bash |
| `docs` | 설계·API·운영 문서 | Markdown |

## 브랜치

- 기본 브랜치는 `dev`입니다. 모든 작업 브랜치는 최신 `dev`에서 만들고, PR도 `dev`로 보냅니다.
- 브랜치 이름은 `<type>/<요약>` 형식이고, 요약은 영어 소문자 kebab-case로 씁니다.

```text
feat/tool-plan-retry
fix/kafka-consumer-dlt
docs/self-hosting-guide
```

- `<type>`은 아래 커밋 type과 같은 값을 씁니다.

## 커밋 메시지

[Conventional Commits](https://www.conventionalcommits.org/ko/v1.0.0/) 형식을 따르고, 요약은 한국어로 씁니다.

```text
<type>(<scope>): <무엇을 했는지 한 줄 요약>

<필요하면 왜 바꿨는지, 동작이 어떻게 달라지는지>
```

- **type**: `feat`(기능), `fix`(버그 수정), `refactor`(동작 변화 없는 구조 개선), `perf`(성능), `test`(테스트), `docs`(문서), `build`(빌드·의존성), `ci`(CI 설정), `chore`(그 밖의 잡무)
- **scope**(선택): `api`, `core`, `engine`, `frontend`, `infra`, `docs`, `repo` 중 변경 영역
- 커밋 하나에는 논리적인 변경 하나만 담습니다. 포맷 변경과 기능 변경은 커밋을 나눕니다.

```text
fix(core): 내부 API 인증을 dependency로 통일
feat(frontend): 도구 상세 화면에 실행 이력 탭 추가
docs(repo): CONTRIBUTING 추가
```

## Pull Request

1. PR 제목은 커밋 메시지 첫 줄과 같은 형식으로 씁니다.
2. 본문은 [PR 템플릿](.github/pull_request_template.md)을 채웁니다. 관련 이슈가 있으면 `Closes #번호`로 연결합니다.
3. CI(`.github/workflows/ci.yml`)가 모두 통과해야 병합합니다.
4. 리뷰어 승인 후 병합하고, 병합한 브랜치는 삭제합니다.

### PR 체크리스트

- [ ] 변경한 영역의 로컬 검증 명령(아래)이 통과한다.
- [ ] 동작이 바뀌는 변경에는 테스트를 추가하거나 고쳤다.
- [ ] 새 환경 변수를 추가했다면 해당 서비스의 `.env.example`과 문서를 함께 고쳤다.
- [ ] 비밀 값, 실제 도메인·서버 주소, 개인 로컬 경로가 커밋에 들어 있지 않다.
- [ ] 빌드 산출물(`build/`, `dist/`, `node_modules/`, `.venv/`, `*.vsix` 등)이 커밋에 들어 있지 않다.
- [ ] API, Kafka 메시지, DB 스키마를 바꿨다면 `docs/api`나 관련 문서를 갱신했다.

## 로컬 검증

```bash
# API 서버 (Testcontainers를 쓰므로 Docker가 실행 중이어야 합니다)
cd backend/theseus-api-server && ./gradlew test

# Core 서버
cd backend/theseus-core-server && python -m pytest -q

# 프론트엔드
cd frontend && npm ci && npm run lint && npm test && npm run build
```

비밀 값이 섞이지 않았는지 [gitleaks](https://github.com/gitleaks/gitleaks)로 미리 확인할 수 있습니다. CI에서도 같은 검사를 합니다.

```bash
gitleaks git -v
```

## 코드와 문서 작성 규칙

- 주석과 docstring은 한국어로, 코드가 **무엇을, 왜** 하는지 설명합니다. 흐름, 상태 전이, 보안상 이유처럼 코드만 봐서는 알기 어려운 내용을 적습니다.
- 주석 처리한 코드는 남기지 않습니다. 필요하면 git 이력에서 찾습니다.
- 문서는 `docs/` 아래 주제별 디렉터리에 둡니다. 더 이상 쓰지 않는 문서는 지우거나 `docs/archive/`로 옮깁니다.

## 보안 문제

취약점은 공개 이슈로 올리지 말고 [SECURITY.md](SECURITY.md)의 절차를 따라 주세요.
