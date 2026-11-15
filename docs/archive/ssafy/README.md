# SSAFY 시절 CI·협업 자산 보관

이 디렉터리는 SSAFY 프로젝트 기간에 쓰던 Jenkins/GitLab/Jira 기반 자산을 기록용으로 보관합니다.
**현재 저장소에서는 사용하지 않고, 유지보수하지 않습니다.** 파일 안의 경로·자격증명 ID·브랜치 규칙은 당시 환경 기준이라 그대로 동작하지 않습니다.

| 파일 | 원래 위치 | 대체 |
| --- | --- | --- |
| `Jenkinsfile` | 저장소 루트 | `.github/workflows/ci.yml` (GitHub Actions) |
| `jenkinsfile-improvement-roadmap.md` | `docs/` | GitHub Actions CI |
| `gitlab/merge_request_templates/Default.md` | `.gitlab/` | `.github/pull_request_template.md` |
| `git-hooks/prepare-commit-msg`, `git-hooks/install.sh` | `tools/git-hooks/` | 없음(Jira 이슈 키를 쓰지 않음) |
| `jira-convention.md` | `docs/conventions/` | 없음 |
| `branch-strategy-jira.md` | `docs/conventions/branch-strategy.md` | [`CONTRIBUTING.md`](../../../CONTRIBUTING.md) |
