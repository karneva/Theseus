"""도구 공통 영→한 용어집(korean_gloss).

도구 설명은 대부분 영어인데 사용자 질의의 약 70%는 한국어라서, 도구 이름·설명의 영어 단어를 한국어 표기로
바꿔 passage("한국어: …")와 BM25 문서(description 필드)에 덧붙입니다. 결정적이고 LLM이 필요 없으며,
커스텀 도구와 MCP 도구에도 자동으로 적용됩니다(용어집에 없는 단어는 건너뜁니다).

출처(docs/architecture/tool-rag.md 4.1절): 이 용어집은 평가셋 dev 분할을 본 뒤 작성됐습니다. 출처가 깨끗한 대안으로
질의를 한 번도 보지 않은 작성자가 도구 카탈로그 어휘만으로 만든 블라인드 용어집(335개 항목)과 비교했고, 미리 정한 규칙
("블라인드의 dev core R@3가 최선보다 0.010 넘게 낮지 않으면 블라인드")에 따라 이 용어집을 유지했습니다.
dev core R@3: 현재 0.918 / 블라인드 0.904 / 합집합 0.895. test 누출 의심 항목 background → 백그라운드는
블라인드 용어집에도 같은 표기로 들어 있습니다(task_* 설명의 카탈로그 어휘).
remote → 원격은 remote_* 도구용으로 나중에 더한 항목입니다(블라인드 용어집에도 있음, dev server R@3 0.881 → 0.895,
core 변화 없음). 새 코어 도구 어휘를 추가할 때는 이 용어집도 함께 갱신하고 RECIPE_VERSION을 올리세요.
키는 소문자여야 합니다(korean_gloss가 소문자로 찾습니다).
"""

from __future__ import annotations

import re

GLOSSARY: dict[str, str] = {
    'read': '읽기',
    'write': '쓰기 작성',
    'create': '생성 만들기',
    'new': '새',
    'edit': '수정',
    'update': '업데이트 수정',
    'replace': '교체',
    'replacing': '교체',
    'file': '파일',
    'files': '파일',
    'text': '텍스트',
    'content': '내용',
    'contents': '내용',
    'line': '줄',
    'lines': '줄',
    'search': '검색',
    'searches': '검색',
    'find': '찾기',
    'pattern': '패턴',
    'matching': '일치',
    'list': '목록',
    'directory': '디렉터리 폴더',
    'workspace': '작업 공간',
    'repository': '저장소',
    'web': '웹 인터넷',
    'page': '페이지',
    'url': 'URL 링크',
    'fetch': '가져오기',
    'results': '결과',
    'research': '조사 리서치',
    'deep': '심층',
    'links': '링크',
    'markdown': '마크다운',
    'shell': '셸 터미널',
    'command': '명령',
    'run': '실행',
    'execute': '실행',
    'stdout': '출력',
    'background': '백그라운드',
    'task': '작업 태스크',
    'tasks': '작업 태스크',
    'output': '출력',
    'log': '로그',
    'status': '상태',
    'stop': '중지 정지',
    'running': '실행 중',
    'start': '시작',
    'servers': '서버',
    'server': '서버',
    'builds': '빌드',
    'detailed': '상세',
    'metadata': '메타데이터',
    'code': '코드',
    'python': '파이썬',
    'symbols': '심볼',
    'symbol': '심볼',
    'definitions': '정의',
    'definition': '정의',
    'references': '참조',
    'type': '타입',
    'hover': '타입 정보',
    'delegate': '위임',
    'sub-agent': '서브 에이전트',
    'agent': '에이전트',
    'parallelizable': '병렬',
    'skill': '스킬',
    'skills': '스킬',
    'workflow': '워크플로',
    'methodology': '방법론',
    'recipe': '레시피',
    'save': '저장',
    'saved': '저장된',
    'reuse': '재사용',
    'memory': '메모리',
    'knowledge': '지식',
    'base': '베이스',
    'documents': '문서',
    'document': '문서',
    'docs': '문서',
    'ingest': '등록',
    'remember': '기억',
    'information': '정보',
    'internal': '내부 사내',
    'worktree': '워크트리',
    'git': '깃',
    'branch': '브랜치',
    'remove': '제거 삭제',
    'clean': '정리',
    'compress': '압축',
    'summary': '요약',
    'conversation': '대화',
    'history': '이력',
    'ask': '질문 묻기',
    'user': '사용자',
    'clarification': '확인',
    'decision': '결정',
    'tool': '도구',
    'tools': '도구',
    'custom': '커스텀',
    'source': '소스',
    'validate': '검증',
    'todo': '할 일',
    'checklist': '체크리스트',
    'done': '완료',
    'item': '항목',
    'resources': '리소스',
    'resource': '리소스',
    'mcp': 'MCP',
    'report': '보고서',
    'local': '로컬',
    'project': '프로젝트',
    'session': '세션',
    'available': '사용 가능',
    'add': '추가',
    'adds': '추가',
    'remote': '원격',
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]*")


def korean_gloss(*texts: str) -> str:
    """텍스트들에 나오는 영어 단어의 한국어 표기를 등장 순서대로 중복 없이 이어 붙입니다."""
    seen: set[str] = set()
    out: list[str] = []
    for text in texts:
        for word in _WORD_RE.findall((text or "").replace("_", " ")):
            gloss = GLOSSARY.get(word.lower())
            if gloss and gloss not in seen:
                seen.add(gloss)
                out.append(gloss)
    return " ".join(out)
