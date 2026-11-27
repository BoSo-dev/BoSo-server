# 서비스 내 알림

알림함의 새 할 일·마감 임박 알림과 읽음 처리를 제공한다. 이메일·웹 푸시·문자 발송은 포함하지 않는다. `20261127_0120`은 `20261127_0110` 뒤에 notifications를 추가한다. 코드 적용·PR 순서는 To-Do → 챗봇 → 알림이며 migration을 선형으로 유지한다.

## API

모든 경로는 Bearer 인증, 본인 소유권, no-store를 적용한다. 목록은 limit=1..100/offset>=0으로 조회한다.

| 경로 | 내용 |
| --- | --- |
| POST /api/v1/notifications/sync | JSON {}. 본인의 To-Do 조건을 재계산한 뒤 알림 생성 |
| GET /api/v1/notifications | unread=true/false 또는 생략 |
| GET /api/v1/notifications/unread-count | 본인의 미읽음 건수 |
| POST /api/v1/notifications/{id}/read | JSON {}. 단일 읽음, 반복 요청 시 원래 read_at 유지 |
| POST /api/v1/notifications/read-all | JSON {}. 현재 미읽음만 일괄 읽음 |

알림의 todo_id로 기존 본인 To-Do 상세를 연결한다. 다른 사용자의 ID는 조회·읽음 처리할 수 없다. 표시용 제목·본문은 생성 당시의 snapshot이며 정책·할 일의 현재 상태는 상세에서 다시 조회한다. 읽음은 완료 상태를 바꾸지 않는다.

## 생성 규칙

- To-Do 서비스를 먼저 호출하여 현재 한국 날짜·프로필·정책에 맞게 재계산하고 같은 사용자 행 잠금을 유지한 상태로 알림을 만든다.
- pending 할 일에 new_todo를 한 번 만든다. 처음 알림 생성 전에 이미 완료된 항목이나 보관된 항목은 만들지 않는다.
- due_date가 오늘부터 3일 뒤 사이(양 끝 포함)이면 due_soon을 생성한다. 오늘 마감도 포함하고 기한 초과·기한 없음은 제외한다.
- 새 할 일은 todo_id, 마감 알림은 todo_id와 해당 due_date를 기준으로 중복을 막는다. 매일 같은 마감 알림을 다시 만들지 않는다. 마감일이 바뀌면 새 마감 이벤트로 본다.
- 보관 후 복구된 같은 To-Do는 새로운 ID가 아니므로 new_todo를 다시 만들지 않는다. 이미 생성된 알림은 읽음/미읽음 이력을 유지한다.
- 정책 적용과 프로필 변경이 알림을 즉시 자동 실행하지는 않는다. 프론트의 sync 또는 명시적인 운영 예약 작업으로 갱신한다.

DB에 사용자/이벤트 키 UNIQUE, 종류·키 길이 CHECK, 사용자 FK와 (todo_id,user_id) 복합 FK를 둬 소유자가 다른 할 일 연결도 막는다. 사용자별 생성은 행 잠금과 하나의 트랜잭션이며 실패 시 To-Do 재계산과 알림 생성이 함께 rollback한다. 읽음 처리와 생성이 동시에 실행되면 read-all 시작 이후 생성된 알림은 미읽음으로 남을 수 있다.

## 예약 실행

기본 명령은 DB에 접속하지 않는다.

```powershell
uv run python -m scripts.sync_notifications
```

실제 스키마·접속 대상·권한을 확인한 운영 작업에서만 `--apply`를 붙인다. 이 명령은 DATABASE_URL의 활성 사용자를 keyset 페이지로 읽고 사용자별 트랜잭션으로 동기화한다. 중간 실패 이전 사용자의 commit은 유지되며 재실행 시 이벤트 키로 중복을 방지한다. 출력에는 건수·고정 오류 코드만 넣고 사용자 ID·개인 정보·DB 오류 원문은 출력하지 않는다.

서버 시작 시 스케줄러를 자동 실행하지 않는다. 배포 환경에서 주기와 실행 주체를 지정한다(예: 주기적 cron job). 여러 worker의 중복 실행도 PostgreSQL 잠금·UNIQUE로 방어하지만 공유 DB와 올바른 트랜잭션이 전제다. 실제 Supabase·예약 서비스 설정은 별도 검증한다.

## 보안과 검증

RLS 기본 차단, PUBLIC 및 존재하는 anon/authenticated/service_role의 직접 테이블 권한 회수를 적용한다. 운영 실행 계정의 최소 권한과 RLS 정책은 별도 확인한다. 실제 Supabase auth.users·기존 역할은 수정하지 않는다.

`uv run python -m pytest tests/test_notifications.py tests/test_notification_migrations.py` 및 `uv run python scripts/check.py`를 사용한다. 기한 경계·다른 사용자 접근·중복 생성·읽음 반복·예약 재실행·PG 복합 FK·동시 실행·RLS·migration 왕복을 검증한다. 실행 결과와 미검증 범위는 ZIP의 VALIDATION.md에 기록한다.
