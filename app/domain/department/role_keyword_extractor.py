"""부서 R&R 설명에서 라우팅용 핵심 역할 키워드를 LLM으로 추출한다.

관리자가 입력한 원문(BE DB·FE 표시용)은 그대로 두고, Qdrant에 임베딩할 텍스트만
"배정/문의/담당" 같은 보일러플레이트와 부서명을 제거한 순수 키워드로 만들기 위함이다.
보일러플레이트가 섞이면 특정 부서로 라우팅이 쏠리는 문제를 근본적으로 막는다.

추가로, 사용자가 같은 대상을 다른 단어로 물어도(예: "연차" vs "휴가") 라우팅이 깨지지
않도록, 각 키워드의 흔한 동의어·표기 변형을 함께 추출한다. 단 같은 대상의 다른 표현만
넣어 엉뚱한 부서로 쏠리는 것을 막는다.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import provider_call
from app.infra.llm.factory import get_llm

_SYSTEM_PROMPT = """당신은 티켓 부서 라우팅을 위한 키워드 추출기입니다.

부서 역할 설명을 받으면, 티켓을 그 부서로 분류하는 데 도움이 되는 "구체적 업무 도메인 키워드"를 추출하고,
각 키워드에 대해 사용자가 같은 대상을 가리킬 때 흔히 쓰는 동의어·표기 변형을 함께 포함합니다.

규칙:
- 부서명은 제외한다.
- 그 부서를 **다른 부서와 구별짓는 구체적인 업무 대상·분야 명사만** 남긴다. (예: 연차, 복리후생, 네트워크, 보안, 비품)
- 핵심 키워드마다 사용자가 같은 것을 다르게 부르는 **동의어·줄임말·표기 변형**을 함께 넣는다.
  - 예: 연차 → 연차, 휴가, 월차, 반차 / 네트워크 → 네트워크, 인터넷, 와이파이 / 계정 → 계정, 아이디, 로그인
  - 단, **같은 대상의 다른 표현만** 넣는다. 의미가 다른 상위·관련 개념(예: 휴가→복지, 네트워크→전산)으로 넓히지 않는다. (엉뚱한 부서 쏠림 방지)
- 아래 같은 단어는 **반드시 제외**한다:
  - 일반 업무어: 담당, 배정, 문의, 신청, 처리, 관리, 업무, 운영
  - 추상·범용어: 지원, 개선, 향상, 효율, 환경, 근무, 제도, 시스템, 설치, 기타
  - 조사·서술어("~을", "~합니다", "~한다" 등)
- 목적·효과·취지를 설명하는 부분(예: "~를 통해 직원의 근무 환경을 개선하고 지원한다")에서는 단어를 뽑지 않는다. 실제 담당 분야만 본다.
- 중복은 제거하고, 쉼표로 구분한 키워드 한 줄로만 응답한다. 다른 설명·문장 부호는 쓰지 않는다.

예시:
입력: "인사팀은 연차, 복리후생을 담당하며, 이를 통해 직원의 근무 환경을 개선하고 지원한다."
출력: 연차, 휴가, 월차, 반차, 복리후생, 복지
입력: "계정, 네트워크 드라이버 설치, OS 및 기타 시스템 설치 문의와 RAG를 담당한다."
출력: 계정, 아이디, 로그인, 네트워크, 인터넷, 와이파이, OS, 운영체제, RAG"""


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
