# Case-based Dynamic Ticket Routing

> 상태: Draft  
> 최종 수정: 2026-06-09

## 목적

티켓 내용을 분석하여 가장 적합한 부서에 배정하도록 추천한다. 개인 담당자 배정은 AI 범위에 포함하지 않고, 배정된 부서 내부의 인원 분배는 TEAM_ADMIN이 수행한다.

SYSTEM_ADMIN은 관리자 화면에서 부서별 담당 업무 프롬프트를 작성한다.

```text
개발1팀 → A서비스, ERP, 계정 시스템
개발2팀 → B서비스, RAG, 검색 시스템
```

이 프롬프트가 부서 R&R의 기준 데이터가 된다.

## 2단계 라우팅

### 1차 후보 검색

티켓에서 시스템명과 업무 키워드를 추출하고 질의 벡터를 생성한다.

```text
ticket text
→ keyword extraction
→ keyword embedding
→ weighted query vector
→ department R&R and approved case similarity
→ top 3 department candidates
```

시스템명과 소업무처럼 구체적인 키워드에 더 높은 가중치를 준다.

### 2차 재정렬

상위 부서 후보의 R&R과 승인된 과거 처리 사례를 티켓 내용과 함께 Cross-Encoder에 입력한다.

```text
(ticket, department R&R + approved cases)
→ Cross-Encoder relevance score
→ candidate reranking
```

1위 점수가 기준 이상이고 1위와 2위의 점수 차이가 충분하면 해당 부서를 추천한다. 그렇지 않으면 공통 접수 큐 또는 관리자 확인으로 전환한다.

Reranker와 라우팅 서비스의 반환 계약:

```json
{
  "recommendedDepartmentId": 2,
  "topScore": 5.14,
  "scoreMargin": 1.27,
  "candidates": [
    {
      "candidateId": "department-2",
      "departmentId": 2,
      "score": 5.14,
      "rank": 1
    },
    {
      "candidateId": "department-5",
      "departmentId": 5,
      "score": 3.87,
      "rank": 2
    }
  ]
}
```

- Reranker는 후보별 `candidateId`, 원본 `score`, `rank`를 반환한다.
- 라우팅 서비스는 1위 점수인 `topScore`와 1·2위 차이인 `scoreMargin`을 계산한다.
- 점수 범위는 모델에 따라 다르므로 정규화 방식이 확정되기 전까지 `0~1`로 가정하지 않는다.

## 처리 사례 기반 동적 갱신

모델을 재학습하거나 부서 벡터를 직접 이동시키지 않는다. 최종 처리 결과가 확정된 티켓을 해당 부서의 검색 사례로 Vector Store에 추가한다.

```text
최초 추천 부서에서 이관
→ 최종 부서가 수락하고 처리 완료
→ TEAM_ADMIN이 라우팅 사례 반영 승인
→ 민감정보 제거 및 임베딩
→ 최종 처리 부서의 승인 사례로 Vector Store에 저장
```

다음 유사 티켓은 부서 R&R뿐 아니라 승인 사례와도 비교되므로 실제 처리 부서가 후보 순위에서 올라올 수 있다.

다음 이벤트만으로는 사례를 확정하지 않는다.

- AI가 특정 부서를 추천한 시점
- 다른 부서로 이관을 요청한 시점
- 사용자 취소 또는 업무량 분산 목적의 이관
- 최종 처리되지 않은 티켓

## Cold Start

신규 부서는 SYSTEM_ADMIN이 담당 서비스와 업무 키워드를 작성한다. 초기에는 R&R 임베딩만 사용하고, 승인된 처리 사례가 쌓이면 검색 근거에 함께 사용한다.

## Divergence Control

- 키워드 간 cosine similarity가 임계값보다 낮으면 단순 평균을 중단
- 시스템명 또는 가장 구체적인 소업무 키워드를 anchor로 사용
- 관련 없는 키워드 혼합 시 공통 접수 큐 또는 관리자 확인으로 전환

## 안전장치

- AI는 부서를 추천하고 BE가 라우팅 정책에 따라 실제 부서 배정을 저장한다.
- 초기에는 추천 부서를 SYSTEM_ADMIN 또는 공통 접수 큐에서 확인하도록 운영할 수 있다.
- 부서 내부 개인 담당자 배정은 TEAM_ADMIN이 담당한다.
- 승인 사례 등록·비활성화·삭제 이력을 저장한다.
- 잘못 승인된 사례를 제외하고 Vector Store에서 재동기화할 수 있어야 한다.
- 후보별 벡터 점수, Cross-Encoder 점수, 최종 배정, 최종 처리 부서를 추적 가능하게 저장한다.

## 남은 결정

- 승인 사례의 부서별 최대 보관 수와 시간 감쇠
- 동일·유사 사례 중복 제거 기준
- Cross-Encoder 모델과 점수 정규화 방식
- 1위 최소 점수와 1·2위 최소 점수 차이
- 자동 배정 전환을 허용할 정확도 기준
