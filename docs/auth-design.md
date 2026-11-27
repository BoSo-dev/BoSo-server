# BoSo 회원 인증 설계

## 범위와 구현 상태

Supabase는 PostgreSQL 저장소로만 사용하고 인증은 FastAPI에서 직접 처리한다. Supabase Auth의 `auth.users`를 연동·변경하지 않는다.

- 1단계: 아래 인증 정책 확정.
- 2단계: `User`, `AuthSession`, `RefreshToken` ORM 모델과 `20261030_0001` revision, 모델·migration 테스트 작성.
- 3단계: 가입·로그인·인증 확인·갱신·현재 세션 로그아웃 API, Argon2id·JWT, 쿠키·CSRF·CORS와 회귀 테스트 구현.
- 별도 운영 작업: 실제 Supabase 스키마 적용, 실행 계정 권한 부여, 분산 요청 제한, 만료 이력 정리. PostgreSQL 실행 검증은 격리 테스트 DB가 필요하다.
- 모델·revision 작성은 실제 DB 적용 완료가 아니다. 이번 작업에서 실제 Supabase에 migration을 적용하거나 데이터를 변경하지 않는다.

## 인증 정책

아래 수명은 BoSo의 초기 정책값이며 표준이 강제하는 값이 아니다.

| 항목 | 정책 |
| --- | --- |
| 가입 | 이메일·비밀번호 가입 후 별도 로그인. 이메일 소유 확인 기능은 범위 밖 |
| 이메일 | 후속 입력/서비스 계층에서 공백 제거·대소문자 정규화. DB는 빈 값·앞뒤 공백·대소문자 중복 차단 |
| 비밀번호 | 15~128자, 공백을 자르거나 조합 규칙을 강제하지 않음. Argon2id 해시만 저장. 로그인 때 필요하면 해시 재생성 |
| Access Token | 서명된 JWT, 15분. 만료는 세션 만료를 넘지 않음. 원문 DB 저장 없음 |
| JWT 검증 | 서버에서 고정한 알고리즘(초기 HS256), 서명, 필수 sub/sid/iat/exp/iss/aud/type=access 검증 |
| Refresh Token | 최소 32바이트 안전한 난수. 원문 대신 SHA-256 소문자 16진수 해시 저장 |
| 세션 | 최초 로그인부터 최대 7일. 갱신해도 연장하지 않음. 다중 세션 허용 |
| 인증 확인 | JWT 검증에 더해 회원 활성 상태, 세션 소유자·만료·폐기 여부를 매 요청 확인 |
| 로그아웃 | Refresh 쿠키에 연결된 현재 세션만 폐기. 다른 로그인 세션 유지. 폐기 commit 이후 인증 검사부터 차단 |

JWT 키와 CSRF 서명 키는 DB 비밀번호·Supabase 키와 별도로 관리하고 서로도 분리한다. 비밀번호·해시·설정 비밀을 응답하지 않는다. Access Token·CSRF 토큰은 인증 응답으로만, Refresh 원문은 HttpOnly 쿠키로만 전달하며 로그·Git·PR에 기록하지 않는다.

### 교체·재사용·동시성

토큰 해시로 세션을 찾고 세션 행을 잠근다. 잠금 이후 최신 토큰·회원·세션 상태를 확인하고 기존 토큰의 used_at 기록 → flush → 새 토큰 삽입을 하나의 트랜잭션으로 수행한다. commit 성공 전에는 새 토큰을 응답하지 않는다.

사용된 해시를 재사용하면 해당 세션만 폐기하고 재로그인을 요구한다. DB에 없는 임의의 토큰으로 다른 세션을 폐기하지 않는다. 재사용 유예는 없다. 동시 요청 중 두 번째가 이전 토큰을 사용하면 첫 요청에서 발급한 토큰도 세션 폐기로 무효화된다. 프론트엔드는 다중 탭을 포함해 갱신을 직렬화하고 같은 토큰을 무조건 재시도하지 않아야 한다.

기존 DbSession은 예외 시 rollback한다. 재사용 탐지 시 서비스는 예외 대신 실패 결과를 반환하고 라우터는 정상 반환 경로의 공통 형식 401 응답을 만든다. function-scoped 의존성 종료 시 폐기 commit을 완료한 다음 전송한다. commit 실패는 쿠키·토큰 없이 500으로 응답한다. 이 동작은 API 회귀 테스트에 포함했다.

### 쿠키·CSRF

- Access Token은 브라우저 메모리에서 Bearer 헤더로 전송한다.
- 운영 Refresh 쿠키: `__Host-` 접두어, HttpOnly, Secure, SameSite=Lax, Path=/, Domain 미지정. 유효 기간은 남은 세션 수명 이내다.
- 로컬 HTTP는 별도 개발용 쿠키 이름·설정만 허용한다.
- Refresh·로그아웃에는 세션에 바인딩된 HMAC 서명 CSRF 토큰과 쿠키·X-CSRF-Token 헤더를 검증한다. 프론트는 허용된 초기화 응답에서 토큰을 받을 수 있어야 한다.
- 정확한 Origin 허용 목록, JSON 전용 가입·로그인, 토큰 응답 Cache-Control: no-store를 적용한다. SameSite·HttpOnly·CORS 중 하나만으로 CSRF 방어를 대체하지 않는다.
- CORS는 정확한 Origin 목록·allow_credentials=True·X-CSRF-Token 허용으로 변경했다. 모든 인증 POST는 Origin과 application/json이 필수다. 비브라우저 클라이언트도 이 헤더를 제공한다.
- 개발·테스트 쿠키는 boso-dev-refresh/boso-dev-csrf, 운영은 __Host-boso-refresh/__Host-boso-csrf다. 운영은 HTTPS Origin과 서로 다른 JWT·CSRF 키가 필수다.
- 로컬/테스트에서 키를 생략하면 health는 유지하고 인증 API는 AUTH_NOT_CONFIGURED(503)로 차단한다. 실행마다 임의 키를 만들거나 고정 기본 비밀을 제공하지 않는다.

## API와 프론트엔드 연동

| 메서드·경로 | 입력·동작 | 성공 응답 |
| --- | --- | --- |
| POST /api/v1/auth/signup | email/password JSON, 이메일 정규화·중복 차단 | 201, id/email/is_active/created_at. 자동 로그인하지 않음 |
| POST /api/v1/auth/login | email/password JSON, 비활성/오인증은 동일 401 | Access Token·expires_in·session_expires_at·csrf_token, Refresh/CSRF 쿠키 |
| GET /api/v1/auth/me | Authorization: Bearer <access_token> | 인증 사용자 기본 정보. 개인화 프로필은 별도 users 기능 |
| POST /api/v1/auth/csrf | Refresh 쿠키와 허용 Origin. 새로고침 후 CSRF 초기화 | csrf_token과 CSRF 쿠키. 기존 세션의 유효한 CSRF는 유지 |
| POST /api/v1/auth/refresh | Refresh/CSRF 쿠키, X-CSRF-Token | 새 Access Token·Refresh 쿠키. 만료/폐기/재사용은 401 |
| POST /api/v1/auth/logout | Refresh/CSRF 쿠키, X-CSRF-Token | 204, 현재 세션 폐기와 쿠키 삭제. 쿠키가 이미 없으면 204 |

토큰 응답은 access_token/token_type/expires_in/session_expires_at/csrf_token이다. Refresh 원문을 JSON으로 받거나 user_id/session_id를 요청해서 인증 대상을 지정하는 API는 제공하지 않는다. POST 본문이 없는 경우도 Content-Type: application/json을 보내면 된다.

브라우저는 fetch의 credentials: "include"를 사용한다. 로그인 응답의 Access Token과 CSRF를 메모리에 두고, 페이지 새로고침 시 POST /auth/csrf → POST /auth/refresh로 복구한다. Refresh/로그아웃은 X-CSRF-Token을 포함하며 다중 탭 갱신을 직렬화한다. 401 재사용 탐지 뒤에는 자동 재시도하지 않고 재로그인한다. 운영 기본 SameSite=Lax는 동일 site 배치를 전제로 한다. cross-site 배포는 별도 설계가 필요하다.

다른 모듈은 app.modules.auth.dependencies.CurrentUser와 공통 DbSession을 사용한다. CurrentUser는 scope="function"으로 DB 의존성을 감싸며 검증된 User를 제공한다. 각 리소스의 소유권은 그 모듈에서 반드시 user.id로 제한한다. JWT 검증만 하고 DB 상태 확인을 생략하지 않는다.

인증 POST에 peer IP·경로별 프로세스 내 30회/분 제한을 두고 상태는 최대 4096개로 제한한다. 원시 Forwarded 헤더를 신뢰하지 않는다. 이 제한은 메모리·요청 남용 완화용이며 다중 worker/서버 공통 방어를 대신하지 않는다. 운영 gateway의 공유 quota·신뢰 proxy 설정·비밀번호 유출 목록 검사는 별도 적용한다. 이메일 존재 여부는 가입 409로 드러날 수 있으며 로그인은 존재 여부·비활성 여부를 구분하지 않는다.

### 설정

- AUTH_JWT_KEY, AUTH_CSRF_KEY: 각각 독립적으로 생성한 최소 32바이트 비밀. DB/Supabase 키나 서로 같은 키 사용 금지. 실제 값은 .env/배포 secret store에만 둔다.
- AUTH_JWT_ISSUER=boso-api, AUTH_JWT_AUDIENCE=boso-web. 변경하면 기존 Access Token은 유효하지 않다.
- JWT HS256만 허용하고 필수 claims·UUID·정수 시간·최대 15분 수명·정확한 issuer/audience를 확인한다. Refresh 원문은 32바이트 CSPRNG, DB에는 64자 SHA-256만 저장한다.
- 회원가입/로그인, Redis, 이메일 인증, 비밀번호 재설정용 Supabase API 키는 사용하지 않는다. 이메일 소유 확인·비밀번호 재설정·계정 삭제는 현재 범위 밖이다.

## DB 구조

관계는 `users 1:N auth_sessions 1:N refresh_tokens`다. UUID는 애플리케이션의 uuid4로 생성하고 PostgreSQL 시간은 UTC 기준 TIMESTAMPTZ로 다룬다. 모델은 공통 Base와 기본 스키마를 유지하고 PostgreSQL migration은 public을 명시한다. SQLite의 UUID·시간 표현은 PostgreSQL 검증을 대신하지 않는다.

| 테이블 | 컬럼 |
| --- | --- |
| users | id UUID PK, email VARCHAR(320), password_hash TEXT, is_active BOOLEAN 기본 true, created_at/updated_at TIMESTAMPTZ |
| auth_sessions | id UUID PK, user_id UUID FK, created_at/expires_at TIMESTAMPTZ, revoked_at TIMESTAMPTZ NULL, revocation_reason VARCHAR(32) NULL |
| refresh_tokens | id UUID PK, session_id UUID FK, token_hash VARCHAR(64), created_at/expires_at TIMESTAMPTZ, used_at TIMESTAMPTZ NULL |

NULL이라고 명시한 컬럼 외에는 NOT NULL이다. created_at과 updated_at은 DB 현재 시각을 기본값으로 사용한다. updated_at은 ORM UPDATE 시 갱신하며 직접 SQL UPDATE에서는 작성자가 명시한다. 별도 DB 트리거는 없다.

### 제약·인덱스

- users: 빈 이메일·앞뒤 공백·빈 비밀번호 해시 거부. `uq_users_email_ci`는 lower(email)의 UNIQUE 표현식 인덱스다.
- auth_sessions: user_id → users.id, ON DELETE CASCADE. user_id·expires_at 인덱스. expires_at > created_at, revoked_at이 있으면 created_at 이상.
- 폐기 시각과 사유는 함께 설정·해제한다. 허용 사유는 logout, refresh_reuse, user_disabled다. CHECK는 NULL 논리로 우회되지 않게 시각·사유의 NULL 여부를 모두 명시한다.
- refresh_tokens: session_id → auth_sessions.id, ON DELETE CASCADE. token_hash UNIQUE 및 길이 64 CHECK. session_id 일반 인덱스와 `used_at IS NULL` 조건의 session_id UNIQUE 부분 인덱스를 둔다.
- 토큰 expires_at > created_at, used_at이 있으면 created_at 이상. 원문·폐기 상태 중복 컬럼은 없다. 개별 사용 처리는 used_at, 세션 전체 무효화는 부모 세션의 폐기가 기준이다.
- 이메일 형식, Argon2 해시 적합성, SHA-256 해시 생성은 입력/서비스 계층에서 처리한다. 모델은 입력값을 변환하거나 인증하지 않는다.
- 토큰과 부모 세션의 만료 일치, 만료·폐기 세션 발급 금지, 사용자별 접근, 재사용 탐지·잠금은 서비스에서 보장한다. PostgreSQL 동시 갱신은 기본 READ COMMITTED와 세션 행 FOR UPDATE 잠금을 사용한다. SQLite 테스트는 이 동시성을 검증하지 못한다.
- 재사용 탐지에 필요한 토큰 해시는 세션 만료 전에 삭제하지 않는다. 만료 후 보관 유예·정리 주기는 별도 확정한다.

## Migration과 접근 제한

첫 revision은 `20261030_0001`, down_revision=None이다. 다음 revision 전에 다시 head 충돌을 확인한다.

- upgrade: users → auth_sessions → refresh_tokens 생성. PostgreSQL public만 대상으로 하고 auth 스키마는 변경하지 않는다.
- 세 테이블에 RLS를 활성화하되 허용 정책은 추가하지 않아 기본 거부 상태로 둔다.
- PUBLIC 권한과 존재하는 anon/authenticated/service_role의 직접 테이블 권한을 모두 회수한다. service_role은 RLS 우회 가능성이 있으므로 ACL도 제한한다.
- 역할이 없으면 조건부로 건너뛴다. migration은 역할 생성·속성 변경, 스키마 전체 권한·기본 권한 변경을 하지 않는다.
- owner·superuser·BYPASSRLS는 기본 RLS 차단 대상이 아니다. 최소 권한 실행 역할의 GRANT·정책은 실제 역할 확정 후 별도 적용·검증해야 한다. 제한 계정은 정책 추가 전 접근할 수 없는 것이 정상이다.
- downgrade: refresh_tokens → auth_sessions → users만 삭제. 실제 Supabase에서 실행하지 않는다.
- SQLite에는 RLS·PostgreSQL ACL SQL을 실행하지 않는다. 서버 시작 시 create_all()을 호출하지 않는다.

## 테스트·안전 경계

```powershell
uv run python -m pytest tests/test_auth_models.py tests/test_auth_migrations.py -q
uv run python -m pytest tests/test_auth_api.py tests/test_auth_security.py tests/test_auth_postgres.py -q
uv run python scripts/check.py
```

- 모델 테스트는 함수별 임시 SQLite에만 테이블을 만든다. 관계·기본값·중복·해시 길이·미사용 토큰 제한·시간/폐기 제약·FK·DB 삭제 연쇄를 검증한다.
- SQLite upgrade→downgrade→재업그레이드와 PostgreSQL/SQLite 오프라인 upgrade/downgrade DDL을 검증한다. SQL 생성은 실제 PostgreSQL 실행 검증이 아니다.
- SQLite는 표현식 인덱스 reflection을 지원하지 않아 기존 Alembic check에서 uq_users_email_ci 비교 생략 경고가 발생할 수 있다. UNIQUE 동작은 직접 테스트하며 스키마 동등성의 최종 검증은 PostgreSQL Alembic check로 수행한다.
- PostgreSQL 실행 테스트는 프로세스 환경변수 TEST_DATABASE_URL이 없으면 skip한다. 실제 .env의 DB URL로 대체하지 않는다.
- 폐기 가능한 로컬/CI superuser 클러스터 전용이다. loopback 호스트, 이름이 _test로 끝나는 접속 DB만 허용한다. sslmode 외 query 옵션과 PGHOSTADDR/PGSERVICE 재정의는 거부한다.
- 테스트는 boso_auth_test_<uuid> 임시 DB를 생성해 그 안에서만 upgrade/downgrade·권한·RLS를 검증하고 정확히 해당 DB만 삭제한다. 원래 TEST_DATABASE_URL DB의 테이블은 변경하지 않는다.
- 필요한 Data API 역할이 없으면 테스트에서만 NOLOGIN 역할을 잠시 생성하고 자신이 만든 역할만 정리한다. 별도 NOBYPASSRLS 역할로 GRANT 이후에도 RLS가 행 읽기·쓰기를 차단하는지 검사한다. 공유·운영 클러스터에 사용하지 않는다.
- 테스트에서 만든 auth.users sentinel의 보존도 검사한다. 실제 Supabase 접속 검증이 아니다.
- 기존 CI의 격리 PostgreSQL 작업에 연결했다. 로컬 Docker 엔진·테스트 URL이 없으면 PostgreSQL 실행·RLS는 미검증이다. CI 설정 추가 자체를 CI 성공으로 보고하지 않는다.
- API 테스트는 임시 SQLite와 실제 get_db의 commit/rollback 경로를 사용한다. 재사용 폐기 후 401 commit, commit 실패 시 쿠키·성공 응답 차단, 다른 세션 유지, CSRF·Origin·CORS·쿠키 속성, JWT·비활성·만료·소유자 검사를 검증한다.
- PostgreSQL 전용 테스트는 앞의 격리 fixture를 재사용해 API 전체 흐름, 중복 가입 경합, 두 동시 갱신 중 하나 성공 후 재사용 탐지로 세션 전체 폐기를 검사한다. TEST_DATABASE_URL 없으면 이 테스트도 skip한다.

### 로컬 실행 검증 결과 (2026-11-24)

- Python 3.12.15, 별도 임시 Docker PostgreSQL 17 컨테이너에서 `python scripts/check.py`를 실행해 Lint·포맷·Git 공백 검사와 전체 235개 테스트를 통과했다. 제외된 테스트는 없다.
- 이전에 제외했던 PostgreSQL 접속, migration upgrade→check→downgrade→재업그레이드, 제약·삭제 연쇄, Data API 역할 권한 회수, NOBYPASSRLS 역할의 기본 차단, 인증 API, 동시 갱신·중복 가입 경합 검증을 포함한다.
- SQLite 표현식 인덱스 reflection 제한 경고 2개는 유지된다. 별도 PostgreSQL의 Alembic check와 대소문자 중복 제약 검증은 통과했다.
- 커밋 전 uv lock 검사와 uv 기반 통합 검사를 재실행해 235개 통과를 확인했다. Compose 설정 검사, Docker 이미지 빌드, 컨테이너 /health/live=200, 인증 키 미설정 시 인증 API=503도 로컬에서 검증했다. Docker 기동 검사는 실제 Supabase 연결·인증 API 전체 컨테이너 통합 검증을 의미하지 않는다.
- 컨테이너는 loopback의 임의 포트·임시 데이터 영역만 사용했다. 세 DB URL을 테스트 프로세스에서만 격리 주소로 주입했고 `.env`는 변경하지 않았다. 테스트 후 자신이 생성한 컨테이너와 임시 데이터만 정리했다.
- 이 결과는 로컬 검증이다. 실제 Supabase 스키마·데이터와 기존 프로젝트 컨테이너를 변경하지 않았으며 GitHub CI·Python 3.14·운영 배포 검증을 대신하지 않는다.

## 후속 작업·근거

적용·배포 전에 PostgreSQL 실행 결과, 프론트/API 도메인, cross-site 필요성, 최소 권한 DB 역할, 실제 Supabase 동명 테이블·revision과 풀러→DB TLS를 확인한다. 프론트의 다중 탭 갱신 직렬화, 운영 공유 요청 제한, 만료 이력 보관·정리 정책도 필요하다. 이력은 세션 만료 전 삭제하지 않는다.

- [FastAPI 비밀번호 해시·JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [RFC 9700 Refresh Token 보호](https://www.rfc-editor.org/rfc/rfc9700.html#section-4.14)
- [OWASP CSRF 방어](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [MDN 쿠키](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie)
- [SQLAlchemy ON DELETE](https://docs.sqlalchemy.org/en/20/orm/cascades.html#using-foreign-key-on-delete-cascade-with-orm-relationships)
- [SQLAlchemy 부분 인덱스](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#partial-indexes)
- [PostgreSQL RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)
- [Supabase Data API 권한](https://supabase.com/docs/guides/api/securing-your-api)

토큰 수명·엄격한 재사용 차단·현재 세션만 로그아웃·테이블 구성은 이 자료를 참고해 선택한 BoSo 정책이다.
