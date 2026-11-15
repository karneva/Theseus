# Environment Variables

서비스별 환경 변수 목록과 설명은 [operations/environment-variables.md](../operations/environment-variables.md)에 있습니다.
이 파일은 관리 원칙만 적습니다.

## 관리 원칙

- 실제 값이 들어간 `.env`, `.env.*` 파일은 커밋하지 않습니다(`.gitignore`에서 제외되어 있습니다).
- 저장소에는 키 이름만 담은 `.env.example`만 둡니다. 비밀 값은 비워 두고, 그 외 값은 누구나 알아볼 수 있는 placeholder만 씁니다.
- 실제 도메인, 서버 주소, 개인 경로를 예시 값으로 넣지 않습니다.
- 새 환경 변수를 추가하면 같은 PR에서 해당 서비스의 `.env.example`과 [환경 변수 문서](../operations/environment-variables.md)를 함께 갱신합니다.
- 비밀 값이 실수로 커밋되었다면 [SECURITY.md](../../SECURITY.md)의 절차에 따라 즉시 회전합니다.
