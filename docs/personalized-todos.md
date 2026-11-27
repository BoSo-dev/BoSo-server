# 개인별 To-Do

정책 데이터 revision `20261127_0003`을 기반으로 `20261127_0100`과 `user_todos`를 추가한다. 정책 HTTP 목록 API 없이 기존 정책·개인 조건 내부 서비스를 사용한다. 실제 Supabase 적용은 별도 작업이다.

## API

모든 경로는 Bearer 인증, 본인 소유권 검증, no-store를 적용한다. 기능 API의 사용자 ID는 인증 결과에서만 얻는다.

| 경로 | 내용 |
| --- | --- |
| POST /api/v1/todos/sync | JSON `{}`. 현재 한국 날짜·프로필·검수 정책으로 생성/갱신/보관 |
| GET /api/v1/todos | status=pending/completed/archived/all, limit=1..100, offset>=0 |
| GET /api/v1/todos/summary | 미완료·완료·보관·마감 초과 건수 |
| GET /api/v1/todos/{id} | 본인 할 일과 출처 버전 식별자 |
| PATCH /api/v1/todos/{id} | `{"completed": true}` 또는 false. 문자열/다른 필드 거부 |

GET은 할 일을 생성하지 않는다. 목록의 total과 페이지는 일반 READ COMMITTED 조회이므로 동시 변경 시 차이가 날 수 있다. 필요하면 다시 조회한다.

## 생성·완료·재계산 규칙

- 나이·지역·카드·수단은 AND, 목록 안은 OR. 불일치가 확인되면 비대상, 값 부족·추가 확인은 unknown이다. unknown에서는 할 일을 생성하지 않는다.
- `other_or_none`을 특정 카드 보유 여부로 추측하지 않는다. `climate_card`는 상세 권종 증명이 아니므로 정책의 추가 확인을 유지한다.
- 정책이 기준일에 active이고 대상이 eligible인 경우에만 행동별로 생성한다. 동일 `(user_id, policy_id, action_key)`는 한 행이다.
- 완료 행은 원래 출처 버전·내용·완료 시각을 보존한다. 같은 행동 키의 새 버전이 자동으로 완료 이력을 초기화하지 않는다. 새 행동이 필요하면 정책 검수자가 새 action_key를 사용한다.
- 미완료 행은 새 버전의 내용·기한·출처로 갱신한다. 대상 해제·정보 부족·정책 종료·행동 제거 시 archived로 바꾸고 이유를 보존한다. 이후 다시 적격이면 같은 ID로 pending에 복구한다.
- 기한 당일은 마감 초과가 아니다. 다음 한국 날짜부터 pending의 is_overdue=true다. 기한 초과만으로 삭제하거나 완료하지 않는다.
- 완료 취소·신규 완료는 현재 정책·조건·행동을 다시 검증한다. 보관 항목이나 더 이상 적용되지 않는 항목은 409다. 이미 완료한 항목의 재완료는 같은 결과를 반환한다.
- 프로필 수정과 재계산을 자동 연결하지 않는다. 프론트는 입력 저장 후 sync를 호출한다. 스케줄러도 같은 내부 서비스를 명시적으로 호출할 수 있다.

users 행 잠금으로 동일 사용자의 프로필 수정·To-Do 동기화를 직렬화한다. 트랜잭션은 공통 DbSession이 성공 응답 전 commit하고 실패 시 rollback한다. DB UNIQUE·FK·CHECK와 서버 소유권 검사를 함께 사용한다.

## 모듈 계약

`evaluate_eligibility(rules, profile)`은 eligible/not_eligible/unknown과 조건 이름을 반환한다. 외부 AI가 적격 판정을 대신하지 않는다.

`related_todos(db, authorized_user_id, policy_ids)`는 해당 사용자의 보관되지 않은 관련 할 일을 최대 100개 반환한다. `pending_todos(db, authorized_user_id)`는 알림 모듈용 내부 조회다. 예약 작업은 `lock_todo_owner`로 소유자를 잠그고 동일 트랜잭션에서 조회해야 한다. 다른 사용자가 입력한 ID를 그대로 넘기지 않는다.

RLS 기본 차단과 클라이언트 역할 직접 권한 회수를 적용한다. owner·superuser·BYPASSRLS 예외는 PostgreSQL 기본 동작을 유지한다. 운영 실행 역할의 최소 권한은 배포 시 별도 검증한다. downgrade는 이 기능의 테이블만 제거한다.

## 검증

`uv run python scripts/check.py` 및 폐기 가능한 로컬 PostgreSQL의 migration·metadata·RLS·동시 sync 테스트를 사용한다. 실제 Supabase나 외부 AI를 테스트 대상으로 삼지 않는다. 테스트 결과는 ZIP의 VALIDATION.md에 기록한다.
