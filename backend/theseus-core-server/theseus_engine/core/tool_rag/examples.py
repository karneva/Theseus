"""도구 검색의 정적 데이터: 필수 도구 집합과 코어 도구 few-shot 예시 질의.

few-shot 예시는 순위용 passage와 BM25 문서(shots 필드), none 판정용 앵커 passage에 들어갑니다.
커스텀 도구는 클래스 속성 ``example_queries``로 자기 예시를 붙일 수 있습니다(tool_factory가 작성을 권장).
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
        "이 정보 기억해줘",
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
