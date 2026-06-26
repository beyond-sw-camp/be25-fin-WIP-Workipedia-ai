"""부서 R&R 설명에서 라우팅용 핵심 역할 키워드만 LLM으로 추출한다.

관리자가 입력한 원문(BE DB·FE 표시용)은 그대로 두고, Qdrant에 임베딩할 텍스트만
"배정/문의/담당" 같은 보일러플레이트와 부서명을 제거한 순수 키워드로 만들기 위함이다.
보일러플레이트가 섞이면 특정 부서로 라우팅이 쏠리는 문제를 근본적으로 막는다.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import provider_call
from app.infra.llm.factory import get_llm

_SYSTEM_PROMPT = """당신은 티켓 부서 라우팅을 위한 키워드 추출기입니다.

부서 역할 설명을 받으면, 티켓을 그 부서로 분류하는 데 도움이 되는 "구체적 업무 도메인 키워드"만 추출합니다.

규칙:
- 부서명은 제외한다.
- 그 부서를 **다른 부서와 구별짓는 구체적인 업무 대상·분야 명사만** 남긴다. (예: 연차, 복리후생, 네트워크, 보안, 비품)
- 아래 같은 단어는 **반드시 제외**한다:
  - 일반 업무어: 담당, 배정, 문의, 신청, 처리, 관리, 업무, 운영
  - 추상·범용어: 지원, 개선, 향상, 효율, 환경, 근무, 제도, 시스템, 설치, 기타
  - 조사·서술어("~을", "~합니다", "~한다" 등)
- 목적·효과·취지를 설명하는 부분(예: "~를 통해 직원의 근무 환경을 개선하고 지원한다")에서는 단어를 뽑지 않는다. 실제 담당 분야만 본다.
- 쉼표로 구분한 키워드 한 줄로만 응답한다. 다른 설명·문장 부호는 쓰지 않는다.

예시:
입력: "인사팀은 연차, 휴가, 복리후생을 담당하며, 이를 통해 직원의 근무 환경을 개선하고 지원한다."
출력: 연차, 휴가, 복리후생
입력: "계정, 네트워크 드라이버 설치, OS 및 기타 시스템 설치 문의와 RAG를 담당한다."
출력: 계정, 네트워크, OS, RAG"""


def extract_role_keywords(prompt_text: str) -> str:
    """부서 R&R 원문에서 역할 키워드만 추출해 한 줄 문자열로 반환한다.

    Raises:
        ProviderError: LLM 호출 실패 (호출 측에서 원문 fallback 권장)
    """
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=prompt_text),
    ]
    with provider_call("llm"):
        llm = get_llm(request_timeout=30.0, max_retries=1)
        response = llm.invoke(messages)
    content = response.content if hasattr(response, "content") else str(response)
    return content.strip()
