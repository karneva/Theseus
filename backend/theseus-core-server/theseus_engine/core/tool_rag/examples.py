"""도구 검색의 정적 데이터: 필수 도구 집합과 코어 도구 few-shot 예시 질의.

* ``TOOL_EXAMPLE_QUERIES``(코어 도구): 순위용 passage와 BM25 문서(shots 필드), none 판정용 앵커 passage와 커버리지
  어휘에 모두 들어갑니다. 커스텀 도구의 클래스 속성 ``example_queries``도 같은 경로를 탑니다(tool_factory가 작성을 권장).
* ``RANKING_ONLY_EXAMPLE_QUERIES``(Remote Workspace remote_* 도구): 순위용 passage와 BM25 문서에만 넣고 앵커·커버리지
  어휘에는 넣지 않습니다. none 규칙은 core 레지스트리(remote_* 없음)로 보정하므로 remote_* 앵커를 few-shot으로 넓히면
  서버 레지스트리의 none 특징이 보정 분포 밖으로 나갑니다.
"""

from __future__ import annotations

# 검색 결과와 무관하게 항상 LLM에 보내는 필수 도구입니다(가시성 필터는 그대로 적용).
# create_tool은 넣지 않습니다. PLAN Executing 단계에서만 보이므로 can_create_tool과 가시성 정책이 결정합니다
# (Explore 단계 측정에서 이 변경의 품질 영향은 0이었습니다).
ESSENTIAL_TOOL_NAMES: frozenset[str] = frozenset(
    {"read_file", "write_file", "edit_file", "glob", "grep", "bash", "ask_user"}
)

# 비용 예산과 무관하게 붙는 메타 도구(none 판정 시 soft fallback으로 추가)
TOOL_SEARCH_NAME = "tool_search"

# 도구 이름 → 예상 사용자 발화. 새 코어 도구를 추가하면 여기와 tool_gloss.GLOSSARY를 함께 갱신하세요.
TOOL_EXAMPLE_QUERIES: dict[str, list[str]] = {
    "web_search": [
        "검색해줘",
        "최신 뉴스 찾아줘",
        "이 에러 해결법 검색",
        "공식 문서 찾아줘",
        "구글에서 찾아봐",
        "인터넷에서 검색",
        "search for",
        "look up online",
    ],
    "web_fetch": [
        "이 URL 내용 읽어줘",
        "웹페이지 가져와",
        "문서 다운로드해줘",
        "링크 열어줘",
        "API 응답 확인해줘",
        "fetch this URL",
    ],
    "read_file": [
        "이 파일 읽어줘",
        "코드 보여줘",
        "설정 파일 내용 확인해줘",
        "파일 열어봐",
        "소스코드 확인",
        "내용 보여줘",
        "show me the file",
        "read this",
    ],
    "write_file": [
        "새 파일 만들어줘",
        "이 내용으로 저장해줘",
        "파일 생성해줘",
        "새로 작성해줘",
        "create a new file",
        "save to file",
    ],
    "edit_file": [
        "코드 수정해줘",
        "버그 고쳐줘",
        "함수 이름 변경해줘",
        "import 추가해줘",
        "이 부분 바꿔줘",
        "리팩터링해줘",
        "fix this code",
        "modify the function",
    ],
    "bash": [
        "터미널 명령 실행해줘",
        "테스트 실행해줘",
        "패키지 설치해줘",
        "빌드해줘",
        "서버 실행해줘",
        "프로세스 확인해줘",
        "pip install",
        "npm run",
        "docker",
        "git 명령",
        "run command",
        "execute",
    ],
    "lsp": [
        "함수 정의 위치 알려줘",
        "이 변수 어디서 사용돼?",
        "참조 찾기",
        "심볼 검색해줘",
        "go to definition",
        "find references",
        "타입 정보 알려줘",
        "호출하는 곳 찾아줘",
    ],
    "grep": [
        "이 텍스트가 어디 있어?",
        "TODO 찾아줘",
        "에러 메시지 검색해줘",
        "코드에서 이거 찾아줘",
        "어디서 import 하고 있어?",
        "문자열 검색",
        "find in files",
        "search for text",
    ],
    "glob": [
        "파일 목록 보여줘",
        "py 파일 찾아줘",
        "디렉토리 구조 확인",
        "어떤 파일들이 있어?",
        "프로젝트 구조 보여줘",
        "list files",
        "find files matching",
        "show directory",
    ],
    "ask_user": [
        "사용자한테 물어봐",
        "확인이 필요해",
        "어떤 걸 선택할지 질문해줘",
        "사용자 입력 받아줘",
        "선택지 제시해줘",
    ],
    "search_knowledge_base": [
        "지식베이스 검색",
        "이전 프로젝트에서 어떻게 했어?",
        "사내 문서 찾아줘",
        "기억하고 있는 거 찾아줘",
        "관련 지식 검색",
        "knowledge search",
    ],
    "ingest_document": [
        "지식베이스에 추가해줘",
        "문서 저장해줘",
        "나중에 쓸 수 있게 저장",
        "save to knowledge base",
    ],
    "skill_save": [
        "이 방법 기억해줘",
        "스킬로 저장해줘",
        "워크플로우 저장",
        "재사용할 수 있게 저장",
    ],
    "skill_read": [
        "저장된 스킬 보여줘",
        "이전에 배운 방법 알려줘",
        "스킬 내용 확인",
    ],
    "skill_list": [
        "스킬 목록",
        "배운 것들 보여줘",
        "어떤 스킬이 있어?",
    ],
    # 메모리 도구(#62): 예시가 없어 "…기억해줘" 질의가 서버에서 숨겨지는 ingest_document와 skill_save로 끌려갔습니다.
    # 평가셋을 보지 않고 도구 설명만 보고 썼고, 평가셋·홀드아웃과의 difflib 유사도는 모두 0.75 미만(최대 0.621)입니다.
    "memory_write": [
        "이 정보 기억해줘",
        "이거 기억해 둬",
        "메모해 둬",
        "앞으로 이 규칙 기억해",
        "다음 세션에도 참고하게 메모해 둬",
        "내 선호 기억해 둬",
        "remember this",
        "keep in mind for next time",
        "note this preference for later",
    ],
    "memory_read": [
        "전에 기억해 둔 거 알려줘",
        "예전에 메모한 규칙 확인해줘",
        "내 선호 뭐라고 했었지?",
        "what did I ask you to remember",
        "read my saved note",
    ],
    "memory_list": [
        "메모 목록 보여줘",
        "기억하고 있는 것들 보여줘",
        "메모 뭐 있어?",
        "list saved memories",
    ],
    "create_tool": [
        "새 도구 만들어줘",
        "커스텀 툴 생성",
        "도구 제작해줘",
        "플러그인 만들어줘",
    ],
    "agent": [
        "서브 에이전트 실행",
        "이 작업 위임해줘",
        "병렬로 처리해줘",
        "다른 에이전트한테 맡겨줘",
    ],
    "enter_worktree": [
        "실험용 브랜치 만들어줘",
        "워크트리 생성",
        "안전하게 코드 수정할 공간 만들어줘",
        "격리된 환경에서 작업",
    ],
    "exit_worktree": [
        "워크트리 제거",
        "실험 브랜치 정리해줘",
        "워크트리 나가기",
    ],
    "brief": [
        "요약해줘",
        "긴 대화 압축해줘",
        "지금까지 내용 정리해줘",
        "컨텍스트 줄여줘",
    ],
}

# Remote Workspace 도구 few-shot(순위 전용). 평가셋·용어집·few-shot을 보지 않은 작성자가 도구 카탈로그만 보고 쓴
# 예시입니다(도구당 한국어 2 + 영어 2). remote_* 도구 클래스는 src/remote_workspace에 있지만, 코어 few-shot과 한곳에서
# 검토하고 RECIPE_VERSION으로 함께 관리하려고 여기에 둡니다. 클래스 속성 example_queries로 두면 앵커에도 들어갑니다.
RANKING_ONLY_EXAMPLE_QUERIES: dict[str, list[str]] = {
    "remote_read_file": [
        "원격 서버 설정 파일 열어봐",
        "원격 워크스페이스 app.py 내용 보여줘",
        "open config.yml on the remote server",
        "show me remote main.py contents",
    ],
    "remote_glob": [
        "원격 서버에서 yml 파일 다 찾아줘",
        "원격 워크스페이스 로그 파일 위치 찾아",
        "list all .py files on remote",
        "find Dockerfiles in the remote workspace",
    ],
    "remote_grep": [
        "원격 코드에서 API_KEY 검색해줘",
        "원격 서버 소스에서 에러 문구 찾아",
        "grep the remote repo for TODO",
        "search remote code for db_connect calls",
    ],
    "remote_tail_log": [
        "원격 서버 에러 로그 최근 줄 보여줘",
        "원격 app.log 끝부분 확인해줘",
        "tail the nginx log on remote",
        "show latest lines of remote app.log",
    ],
    "remote_check_cpu": [
        "원격 서버 CPU 사용률 확인해줘",
        "원격에서 CPU 많이 먹는 프로세스 뭐야",
        "check CPU load on the remote server",
        "which process is hogging remote CPU",
    ],
    "remote_check_memory": [
        "원격 서버 메모리 얼마나 남았어",
        "원격 서버 램 사용량 보여줘",
        "check RAM usage on remote box",
        "is the remote server running out of memory",
    ],
    "remote_check_disk": [
        "원격 서버 디스크 용량 확인해줘",
        "원격 서버 저장공간 얼마나 남았어",
        "check disk space on the remote server",
        "is the remote disk almost full",
    ],
    "remote_write_file": [
        "원격 서버에 새 설정 파일 만들어줘",
        "원격에 deploy.sh 파일 작성해줘",
        "create a new .env file on remote",
        "write a config file to the remote server",
    ],
    "remote_edit_file": [
        "원격 설정 파일에서 포트 번호 바꿔줘",
        "원격 서버 코드 한 줄 수정해줘",
        "change the timeout value in remote config",
        "patch server_name in remote nginx.conf",
    ],
    "remote_run_command": [
        "원격 서버에서 서비스 재시작해줘",
        "원격에서 git pull 실행해",
        "run docker ps on the remote server",
        "restart the app service remotely",
    ],
}
