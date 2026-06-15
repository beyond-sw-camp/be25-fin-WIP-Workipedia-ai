# Ticket Domain Guide

> 문서 유형: Development Guide
> 상태: Draft
> 정본 위치: `docs/domain-guides/ticket.md`
> 관련 문서: `docs/domain-guides/ticket-routing-ai.md`, `docs/reference/service-flow.md`, `docs/reference/trd.md`
> 버전: v0.1
> 최종 수정: 2026-06-04

## 개발 목표

요청을 티켓으로 발행하고, 자동 배정 또는 공통 접수 큐를 거쳐 담당 부서와 팀원에게 연결한다.

## 먼저 볼 문서

- `docs/domain-guides/ticket-routing-ai.md`
- `docs/reference/service-flow.md`
- `docs/reference/trd.md`

## MVP 구현 범위

- 요청 티켓 생성
- 라우팅 점수 저장
- 담당 부서 자동 배정
- 낮은 점수일 때 공통 접수 큐 이동
- `TEAM_ADMIN`의 팀원 배정
- `TEAM_ADMIN`의 이관 요청 시 공통 접수 큐 이동
- 티켓 상태 변경
- 본인 티켓 조회
- 상태별/부서별 티켓 목록 조회
- 팀 티켓 큐 조회
- 공통 접수 큐 조회
- 티켓 중요도(priority) 저장
- TEAM_ADMIN용 팀원별 최근 30일 처리 건수 통계
- 사진 첨부 업로드/조회

## API/DB 영향

- `tickets`
- `ticket_status`
- `priority`
- `assigned_department_id`
- `assignee_id`
- `routing_confidence_score`
- `transfer_reason`
- `attachments`
- ticket create/list/detail/update APIs
- `GET /tickets?status={status}&departmentId={departmentId}`
- attachment upload/read APIs

## 권한/보안 체크

- `USER`는 본인 티켓만 조회한다.
- `TEAM_ADMIN`은 자기 팀 티켓만 조회한다.
- `SYSTEM_ADMIN`은 공통 접수 큐를 관리한다.
- 팀 관리자의 이관은 다른 부서 직접 이동이 아니라 공통 접수 큐 이동이다.

## 완료 기준

- 사용자가 요청 티켓을 생성할 수 있다.
- 라우팅 점수에 따라 담당 부서 또는 공통 접수 큐로 이동한다.
- 팀 관리자가 팀원에게 티켓을 배정할 수 있다.
- 담당 팀원이 처리 완료 상태로 변경할 수 있다.
- `status`, `departmentId` 조건으로 티켓 목록을 조회할 수 있다.
- 티켓 생성 시 중요도와 첨부 파일이 저장된다.
- TEAM_ADMIN 화면에서 팀원별 최근 처리 건수 등 배정 참고 통계를 확인할 수 있다.
- AI 라우팅은 담당 부서까지만 추천하며 개인 담당자를 추천하지 않는다.

## 논의 필요 사항

- `RECEIVED` 상태를 DB에 실제로 남길지
- 라우팅 점수 초기 기준
- 담당자 변경 허용 여부
- 취소 상태를 별도로 추가할지 여부
- 고객사별 이미지 저장소 adapter 설정(S3 또는 MinIO)
