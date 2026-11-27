# 내 정보·교통 조건 API

## 범위와 의존 관계

가입·로그인은 auth, 개인화 조건 저장·조회는 users 모듈이 담당한다. 로그인 직후 교통 정보 등록 화면과 마이페이지의 조회·수정을 지원한다. 프론트엔드·정책 데이터·To-Do·챗봇·알림·회원 탈퇴는 이 변경에서 구현하지 않는다. 로그아웃은 기존 POST /api/v1/auth/logout을 사용한다.

선행 인증 PR #3은 develop에 병합됐다. feat/user-profile은 해당 변경이 포함된 develop을 기준으로 검토하고 PR도 develop을 대상으로 한다. 적용 순서는 인증 revision 다음 프로필 revision이다. 이 기능을 완료했다고 실제 Supabase에 테이블이 적용된 것은 아니다.

## API

세 경로 모두 Authorization: Bearer Access Token이 필요하다. 요청마다 기존 CurrentUser가 사용자 활성 상태·세션 소유자·만료·폐기를 검증한다. 클라이언트가 user_id를 지정하는 경로는 제공하지 않는다.

| 메서드·경로 | 동작 |
| --- | --- |
| GET /api/v1/me | 본인의 이메일·교통 조건·만 나이·미입력 항목 조회 |
| PATCH /api/v1/me | 본인의 교통 조건을 부분 등록·수정 |
| GET /api/v1/me/options | 거주 지역·교통카드·주 이용 수단 코드와 표시명 조회 |

PATCH 예시:

```json
{
  "birth_date": "2000-11-28",
  "region_code": "seoul",
  "transport_cards": ["k_pass"],
  "transport_modes": ["bus", "subway"]
}
```

- birth_date는 YYYY-MM-DD만 허용한다. 1900-01-01부터 한국 시간(UTC+09:00)의 오늘까지이며 숫자 epoch·timestamp·미래·잘못된 날짜는 거부한다. 1900년 하한은 입력 검증 기준이지 정책 자격 기준이 아니다.
- region_code는 서비스 내부 지역 코드다. 행정·법정동 코드나 정책의 지역 자격을 의미하지 않는다. 서울·부산 등 17개 선택지를 options에서 제공한다. 별도 자유 입력 주소는 저장하지 않는다.
- transport_cards는 k_pass, climate_card, other_or_none이다. 마지막 값은 화면의 '기타 / 이용 카드 없음'에 대응하며 두 지정 카드와 함께 선택할 수 없다. 카드번호·발급사 식별번호·금융 정보는 저장하지 않는다.
- transport_modes는 bus, subway이며 복수 선택할 수 있다.
- 목록은 집합 의미로 처리하고 응답은 코드순으로 정렬한다. 중복·알 수 없는 코드·null 목록은 422다. 빈 목록은 기존 선택을 지운다.
- 누락 필드는 유지한다. birth_date·region_code의 명시적 null은 값을 지운다. 빈 PATCH, user_id/email/age/is_active/password_hash 등 허용하지 않은 필드는 422다.
- 프로필 미등록 GET은 기본 빈 상태를 반환하며 DB에 행을 만들지 않는다. 첫 PATCH에서 생성한다.
- is_complete와 missing_fields는 네 가지 입력의 완료 상태다. 정책 대상 여부나 혜택 보장을 의미하지 않는다. 일부 값을 지우면 다시 미완료가 된다.
- 나이는 저장하지 않고 reference_date 기준으로 매번 계산한다. 생일 당일 증가하며 2월 29일생은 비윤년 3월 1일에 증가한다. 생일 이전 기준일의 내부 조회는 음수 나이 대신 미확인 상태를 제공한다.
- 응답은 user_id/email/birth_date/age/region_code/transport_cards/transport_modes/reference_date/is_complete/missing_fields/updated_at이다. 미등록 updated_at은 null이다.
- 개인정보 응답과 관련 오류에는 Cache-Control: no-store를 적용한다. 입력·생년월일·이메일·Bearer Token을 로그에 기록하지 않는다. 다른 사용자의 식별자로 조회·수정할 수 없다.

전체 입력이 완료되면 프론트는 홈으로 이동할 수 있다. 미완료 상태를 이유로 사용자를 임의의 정책 대상 또는 비대상으로 확정하지 않는다.

## DB와 트랜잭션

revision 20261127_0002는 20261030_0001을 잇는다.

| 테이블 | 구조 |
| --- | --- |
| user_profiles | user_id UUID PK·users FK, birth_date DATE NULL, region_code VARCHAR(16) NULL, created_at/updated_at TIMESTAMPTZ |
| user_transport_cards | user_id UUID·card_code VARCHAR(32) 복합 PK, user_profiles FK |
| user_transport_modes | user_id UUID·mode_code VARCHAR(16) 복합 PK, user_profiles FK |

모든 FK는 ON DELETE CASCADE다. PK·FK·지역/카드/수단 코드 CHECK·생년월일 정적 하한 CHECK를 모델과 migration에 함께 둔다. 미래일 검증과 카드 선택의 상호 배타 조건은 서비스·입력 검증에서 수행한다. 코드 목록을 바꾸면 새 revision으로 CHECK를 갱신하고 이미 적용한 revision은 수정하지 않는다.

최초 등록과 목록 교체는 users 행의 FOR UPDATE 잠금으로 직렬화한다. 누락 필드를 보존하는 부분 수정과 목록 전체 교체를 하나의 트랜잭션으로 처리한다. 같은 필드 동시 수정은 나중에 잠금을 획득한 요청의 값이 최종값이며, 서로 다른 필드 수정은 보존한다. SQLite는 이 행 잠금 검증을 대신하지 않는다. 조회는 세 프로필 테이블을 한 SQL로 읽어 READ COMMITTED에서도 서로 다른 시점의 지역·카드·이용 수단이 섞이지 않도록 한다.

라우터는 동기 def와 공통 function-scoped DbSession을 사용한다. commit을 성공 응답보다 먼저 완료하고 실패 시 전체 변경을 rollback한다. 서버 시작 시 create_all()을 호출하지 않는다.

PostgreSQL의 세 테이블은 RLS를 활성화하고 허용 정책을 두지 않는다. PUBLIC과 존재하는 anon/authenticated/service_role의 직접 권한을 회수한다. owner·superuser·BYPASSRLS 예외는 유지하므로 운영 최소 권한 역할의 GRANT·정책은 별도 적용·검증해야 한다. Supabase auth.users와 기존 인증 revision은 변경하지 않는다. downgrade는 세 프로필 테이블만 제거하고 기존 회원·인증 정보를 보존한다.

## 다른 기능에 제공하는 계약

```python
from app.modules.users.service import get_personalization_context

context = get_personalization_context(db, authenticated_user.id)
```

내부 호출자는 이미 인증·권한 확인을 완료한 사용자 ID만 전달한다. 비활성 또는 없는 사용자는 404다. HTTP 입력으로 다른 사용자 ID를 받아 이 함수를 호출하지 않는다.

PersonalizationContext에는 user_id/reference_date/age/region_code/transport_cards/transport_modes/is_complete/missing_fields만 포함한다. 이메일과 생년월일 원문을 불필요하게 To-Do·외부 AI로 전달하지 않는다. 정책 조회·To-Do·챗봇은 이 계약으로 동일한 코드를 사용하며 업무 로직을 users 라우터에 직접 연결하지 않는다. 정보 부족과 other_or_none을 특정 카드 보유·미보유로 임의 추정하지 않는다. 정책 자격 판단은 검수된 정책 규칙이 담당한다.

## 검증·실행 경계

```powershell
uv run python -m pytest tests/test_user_profile.py tests/test_user_profile_migrations.py -q
uv run python scripts/check.py
```

API·SQLite 테스트는 임시 DB와 테스트용 회원·토큰을 사용한다. 기존 get_db commit/rollback 경로, 다른 사용자 접근 차단, 입력·생일 경계, 목록 교체·삭제 연쇄, 로그·캐시 비노출을 검증한다. SQLite에서 upgrade→인증 revision으로 downgrade→재업그레이드와 PostgreSQL/SQLite 오프라인 DDL을 검사한다.

PostgreSQL 테스트는 TEST_DATABASE_URL이 지정된 폐기 가능한 로컬/CI *_test DB만 사용한다. 기존 안전 fixture가 생성하는 별도 임시 DB에서 Alembic check·upgrade/downgrade·DB 제약·RLS·역할 권한·삭제 연쇄·동시 최초 등록을 검증한다. 실제 Supabase로 대체하지 않는다. 테스트 URL 또는 Docker 엔진이 없으면 PostgreSQL 실행 검증은 미검증으로 기록한다.

실제 .env·DB 비밀번호·Supabase 연결 설정은 변경하지 않는다. 실제 migration 적용은 별도 승인 대상이다. 새로운 환경변수나 외부 서비스 키는 추가하지 않는다. 인증 키 설정은 기존 인증 문서를 따른다.

### 로컬 검증 결과 (2026-11-27)

- Python 3.12.15와 별도 임시 Docker PostgreSQL 17에서 `uv run --locked --extra dev python scripts/check.py`를 실행했다. Lint·포맷·전체 309개 테스트·Git 공백 검사 통과, 제외 0개다.
- 새 프로필 revision의 upgrade→Alembic check→인증 revision으로 downgrade→재업그레이드, 기존 회원 보존, DB 제약·삭제 연쇄·역할 권한·RLS·동시 최초 등록 검증을 포함한다. 기존 인증 회귀 테스트도 통과했다.
- SQLite 표현식 인덱스 reflection 제한 경고 2개는 기존과 동일하며 PostgreSQL Alembic check는 통과했다.
- 단일 SQL 조회 검사와 PostgreSQL 조회 도중 별도 연결의 수정이 commit되는 상황에서도 변경 전후 값이 섞이지 않는 회귀 테스트를 통과했다.
- 테스트 프로세스의 DB URL만 loopback 임시 DB로 격리했다. 종료 후 해당 테스트 컨테이너와 임시 데이터만 정리했다. 실제 Supabase 스키마·데이터와 .env는 변경하지 않았다.
- GitHub CI·Python 3.14·실제 Supabase 적용·프론트엔드 연동은 이번 로컬 결과로 검증했다고 간주하지 않는다.

## 설계 근거

- [SQLAlchemy 행 잠금](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update)
- [Pydantic 입력 검증](https://docs.pydantic.dev/latest/concepts/validators/)
- [PostgreSQL RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)

API 코드·기준일·입력 하한·카드 분류는 서비스가 선택한 계약이며 공식 정책 자격 요건을 대신하지 않는다.
