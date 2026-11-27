# BoSo-server

교통카드 정책 변화 요약, 개인별 할 일 관리, 정책 상담 챗봇을 제공하는 BoSo의 백엔드 저장소입니다. FastAPI, SQLAlchemy, Alembic, PostgreSQL을 사용하며 Supabase PostgreSQL 연동을 대상으로 합니다.

`chore/project-setup`은 모든 팀원이 함께 사용할 실행 환경, 전체 도메인의 모듈 틀, API 연결 지점, 작업 하네스를 제공합니다. 각 기능의 업무 로직과 테이블은 기능별 브랜치에서 추가합니다.

## 빠른 시작

Python 기준 버전은 3.12이며 uv가 해당 버전을 설치·선택합니다. 호환성 검사는 Python 3.12와 3.14를 대상으로 합니다. [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 준비하세요.

```powershell
uv sync --locked --extra dev
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d db
uv run alembic current
uv run uvicorn app.main:app --reload --no-access-log
```

`.env`는 저장소 루트(`pyproject.toml` 옆)에 둡니다. 위 예시는 `.env.example`의 로컬 PostgreSQL 기본값을 기준으로 합니다. 이미 Supabase에 연결한 `.env`는 덮어쓰지 말고 아래 Supabase 검증 명령을 사용하세요. macOS/Linux에서는 `.env`가 없을 때만 `cp .env.example .env`를 실행합니다. 연결 문자열·비밀번호·키를 Git, 로그, 이슈, PR에 포함하지 않습니다.

- Swagger: <http://localhost:8000/docs>
- 프로세스 상태: `GET /health/live`
- DB 연결 상태: `GET /health/ready`

회원가입·로그인·인증 확인·갱신·현재 세션 로그아웃 API가 구현돼 있습니다. 실제 사용에는 인증 키와 스키마 적용이 필요하며 아래 인증 안내를 확인하세요. `/health/ready`는 DB 연결만 검사합니다. 회원·인증 세션·Refresh Token 모델과 첫 revision `20261030_0001`이 작성돼 있으며 실제 Supabase 적용은 별도 승인 대상입니다. `alembic current`는 적용된 revision을 조회하고 `alembic heads`는 로컬 revision을 확인합니다. 파일 존재나 접속 성공만으로 테이블 적용 완료를 의미하지 않습니다.

Docker 전체 실행은 `docker compose up --build`입니다. 이 Compose 파일은 로컬 개발용이며 DB 포트는 localhost에만 공개합니다. `docker compose down`으로 중지하고 데이터는 볼륨에 보존합니다.

## Supabase 연결 및 읽기 전용 검증

Dashboard → Connect에서 Direct connection 또는 Session pooler 주소를 가져와 `.env`의 `DATABASE_URL`에 넣습니다. `postgres://`, `postgresql://`는 코드에서 `postgresql+psycopg://`로 변환하므로 이미 동작하는 접속 주소를 다시 바꿀 필요는 없습니다. 원격 PostgreSQL에 SSL 옵션이 없으면 `sslmode=require`를 적용하고, `disable`·`allow`·`prefer`는 거부합니다. 비밀번호의 예약 문자는 URL 인코딩하고 예시의 대괄호는 제거합니다. IPv4 환경에서는 Session pooler를 사용합니다.

주소·포트는 URI 본문에 지정합니다. `host`·`hostaddr`·`port` 쿼리 옵션은 검증한 대상과 실제 드라이버의 접속 대상이 달라지는 것을 막기 위해 거부합니다. `sslmode`·`sslrootcert`·`application_name` 등 정상 옵션은 유지합니다.

```dotenv
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

프로젝트 URL·anon key 대신 서버 전용 PostgreSQL 연결 문자열을 사용합니다. 로컬 Compose의 API는 로컬 DB를 사용하도록 구성되어 있으므로 Supabase 검증은 호스트에서 실행하세요. [공식 연결 안내](https://supabase.com/docs/guides/database/connecting-to-postgres)를 참고하세요.

### 환경변수

| 변수 | 용도·기본값 |
| --- | --- |
| `APP_ENV` | `development`(기본), `test`, `production` |
| `DATABASE_URL` | FastAPI 실행용 DB 주소. 기본값은 로컬 PostgreSQL |
| `MIGRATION_DATABASE_URL` | 선택 사항. Alembic 전용 주소이며 생략하면 `DATABASE_URL` 사용. 사용하지 않으면 주석 처리하고 빈 값으로 설정하지 않음 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 프로세스별 기본·추가 연결 수. 기본값 `5` / `0`, 허용 범위 `1..20` / `0..20` |
| `DB_CONNECT_TIMEOUT` / `DB_POOL_TIMEOUT` | DB 연결 시도·풀 대기 제한(초). 기본값 `5` / `10`, 각각 `1..60` |
| `CORS_ORIGINS` | 허용 프론트엔드 주소의 JSON 배열. 운영에서는 `*` 금지 |
| `AUTH_JWT_KEY` / `AUTH_CSRF_KEY` | 각각 독립 생성한 최소 32바이트 비밀. 기본값 없음. 비밀번호·Supabase 키와 재사용 금지 |
| `AUTH_JWT_ISSUER` / `AUTH_JWT_AUDIENCE` | Access Token 발급자·수신자. 기본값 `boso-api` / `boso-web` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 로컬 Compose DB 전용. Supabase 접속 비밀번호와 무관 |
| `TEST_DATABASE_URL` | 선택적인 테스트 전용 PostgreSQL 주소. 테스트 프로세스 환경변수로 지정하며 실제 Supabase DB 사용 금지 |

Alembic은 Direct 또는 Session pooler 주소를 사용합니다. Supabase transaction pooler의 `6543` 포트는 마이그레이션용으로 거부합니다. 운영 시에는 `DATABASE_URL`을 최소 권한 실행 계정으로, `MIGRATION_DATABASE_URL`을 관리·마이그레이션 계정으로 분리합니다. 현재 관리 계정의 RLS 우회 권한을 임의로 제거하지 않습니다.

### 접속 검증 명령

```powershell
uv run python scripts/check_db.py
uv run python scripts/check_db.py --migration
uv run alembic current
```

`check_db.py`는 읽기 전용 트랜잭션으로 접속, 앱 측 TLS, PostgreSQL 세션의 SSL, 스키마 접근 권한, migration 이력 유무를 확인합니다. `--migration`도 DB를 변경하지 않으며 Alembic용 주소와 스키마 `CREATE` 권한을 추가 확인합니다. 실제 생성·변경 권한 전체나 migration 실행 성공을 보장하는 검사는 아닙니다. 실패 시 접속 정보·SQL·드라이버 원문 대신 정해진 오류 코드만 출력합니다.

`status=ok`는 접속·기본 권한 검사의 성공이며, 양쪽 구간의 TLS나 RLS까지 검증했다는 뜻은 아닙니다. `client_tls`는 앱→접속 서버, 풀러 사용 시 `backend_tls`는 PostgreSQL이 보는 풀러→DB 세션을 나타냅니다. `role_can_bypass_rls=true`인 계정으로는 RLS 차단 동작을 검증할 수 없습니다.

`sslmode=require`는 암호화 연결을 요구하지만 서버 신원 검증까지 의미하지는 않습니다. `verify-full`은 CA·호스트명 검증을 포함하며 별도 인증서 설정이 필요합니다. Supabase의 SSL 강제 설정은 별도로 관리하고, 변경 시 DB 재시작이 발생하므로 팀과 조율한 뒤 적용·재검증합니다. [공식 SSL 안내](https://supabase.com/docs/guides/platform/ssl-enforcement), [RLS 안내](https://supabase.com/docs/guides/database/postgres/row-level-security)를 참고하세요.

### 현재 범위와 후속 작업

`feat/supabase-db`는 Supabase 연결 기반과 Alembic 접속 검증까지 다룹니다. 실제 Supabase 접속·앱 측 TLS·기본 스키마 권한 검사를 수행했고, `alembic current` 접속 성공은 개발자가 확인했습니다. 당시 검사에서 풀러→DB SSL은 `false`, 관리 계정의 RLS 우회 권한은 `true`로 보고됐습니다. 이를 운영 보안 설정 완료로 간주하지 않습니다.

실제 Supabase 테이블의 생성·수정·삭제, migration 적용, 테이블별 RLS 검증은 이번 범위에 포함하지 않습니다. 도메인 모델·revision·권한·RLS 정책 및 사용자별 접근 검증은 후속 기능 PR에서 함께 추가합니다. 실제 데이터 취급·배포 전에는 SSL 설정과 최소 권한 실행 계정도 확인해야 합니다.

스키마 적용이 승인된 후속 작업에서는 대상 DB를 확인한 뒤 `uv run alembic upgrade head` 또는 오류 출력을 제한하는 `uv run python scripts/migrate.py`를 사용합니다. 두 명령 모두 DB를 변경할 수 있으므로 접속 확인 용도로 실행하지 마세요. revision이 없어도 Alembic 관리 테이블이 생성될 수 있습니다.

## 검증

```powershell
uv run python scripts/check.py
```

Ruff lint·format 검사, pytest, Git 공백 검사를 순서대로 실행합니다. 개별 실행 명령은 다음과 같습니다.

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python -m pytest -q
```

로컬 DB 변경 테스트는 임시 SQLite를 사용합니다. Alembic 테스트는 `DATABASE_URL`과 `MIGRATION_DATABASE_URL`을 모두 임시 DB로 덮어쓰고 연결 직전에 대상이 맞는지 확인합니다. URL 변환·SSL·접속 정보 비노출 테스트는 가짜 URI와 모의 객체를 사용하며 실제 Supabase에 접속하지 않습니다.

`TEST_DATABASE_URL`을 테스트 프로세스 환경변수로 지정하면 PostgreSQL 검사도 실행합니다. 지정하지 않으면 해당 테스트는 제외됩니다. `.env`에 적는 것만으로 활성화되지는 않으며 실제 Supabase를 넣지 마세요. 인증 migration 테스트는 폐기 가능한 로컬/CI superuser 클러스터와 `_test`로 끝나는 접속 DB만 허용합니다. 생성한 임시 DB에서 upgrade·downgrade·RLS·권한을 검증하고 임시 DB·자신이 만든 검사 역할만 정리합니다. 원래 접속 DB의 테이블은 변경하지 않습니다. 상세 안전 조건과 미구현 항목은 [인증 설계](docs/auth-design.md)를 확인하세요. SQLite 테스트 통과를 실제 PostgreSQL·Supabase 검증으로 간주하지 않습니다.

GitHub CI는 같은 검사와 별도 PostgreSQL 마이그레이션·Docker 빌드·컨테이너 상태 확인을 수행합니다. 개발 환경에 Docker 엔진이 실행 중이어야 컨테이너 검증이 가능합니다.

## 회원 인증

Supabase는 DB로만 사용하며 인증은 FastAPI에서 처리합니다. 실제 `.env`는 자동 수정하지 않습니다. `AUTH_JWT_KEY`와 `AUTH_CSRF_KEY`를 각각 독립적인 안전한 난수로 생성해 로컬 `.env` 또는 배포 비밀 저장소에 넣으세요. 각 키는 최소 32바이트이고 서로 달라야 합니다. 생성한 값은 채팅·로그·Git에 붙이지 마세요. 개발 환경에서 키가 없으면 상태 확인은 유지하지만 인증 API는 503을 반환하며, 운영 환경은 시작 시 설정을 거부합니다.

호스트에서 실행하는 Uvicorn은 루트 `.env`를 읽지만 기본 Compose의 API 서비스는 인증 키를 자동 전달하지 않습니다. 컨테이너에서 인증을 사용하려면 실행 환경에 두 키를 별도로 주입해야 합니다. `.env` 전체를 이미지에 복사하거나 DB 비밀번호를 인증 키로 재사용하지 마세요.

| API | 기능 |
| --- | --- |
| `POST /api/v1/auth/signup` | 이메일·비밀번호 회원가입, 201. 자동 로그인하지 않음 |
| `POST /api/v1/auth/login` | 로그인, Access Token·CSRF 응답과 Refresh 쿠키 |
| `GET /api/v1/auth/me` | Bearer Access Token으로 현재 사용자 확인 |
| `POST /api/v1/auth/csrf` | 페이지 새로고침 후 CSRF 토큰 초기화 |
| `POST /api/v1/auth/refresh` | Refresh Token 교체·Access Token 갱신 |
| `POST /api/v1/auth/logout` | 현재 세션만 폐기하고 쿠키 삭제 |

가입·로그인 JSON은 `email`, `password`이며 비밀번호는 15~128자입니다. 모든 인증 POST는 허용된 정확한 `Origin`과 `Content-Type: application/json`이 필수입니다. 프론트는 `credentials: "include"`로 쿠키를 전송하고 갱신·로그아웃에 `X-CSRF-Token`을 추가합니다. 새로고침 후 `/auth/csrf` → `/auth/refresh` 순으로 복구하며 갱신은 다중 탭까지 직렬화해야 합니다.

Swagger에서 인증 POST를 직접 실행하려면 Swagger가 열린 API Origin(예: `http://localhost:8000`)도 개발용 `CORS_ORIGINS`에 명시해야 합니다. Host 헤더를 근거로 출처를 자동 허용하지 않습니다. CLI 요청도 허용 Origin 헤더를 직접 지정하세요.

Access Token은 최대 15분, 세션·Refresh는 최초 로그인부터 최대 7일이며 갱신으로 연장되지 않습니다. 사용한 Refresh Token 재사용은 해당 세션을 폐기합니다. 개발 HTTP 쿠키와 운영 HTTPS `__Host-` 쿠키를 구분하며 운영은 정확한 HTTPS CORS Origin만 허용합니다. `SameSite=Lax`이므로 cross-site 배포는 추가 설계가 필요합니다. 인증 POST의 프로세스별 요청 제한은 운영 gateway의 공유 제한을 대신하지 않습니다.

실제 Supabase에 테이블을 자동 생성하지 않습니다. 스키마 적용과 최소 권한 DB 계정·RLS·풀러→DB SSL 검증은 대상 확인·승인 후 별도 수행합니다. PostgreSQL 전용 테스트 URL이 없으면 마이그레이션·RLS·동시 갱신 검증을 skip하며 실제 Supabase로 대체하지 않습니다. 상세 정책과 다른 모듈의 `CurrentUser` 연동은 [인증 설계](docs/auth-design.md)를 참고하세요.

## 구조와 작업 규칙

내 정보 기능은 `GET/PATCH /api/v1/me`, `GET /api/v1/me/options`를 제공합니다. Bearer 인증으로 본인의 거주 지역·생년월일·교통카드·주 이용 수단을 조회·부분 수정합니다. 미등록 조회는 빈 상태를 반환하며 DB를 변경하지 않습니다. 프로필 모델과 revision `20261127_0002`는 인증 revision `20261030_0001` 다음에 적용하도록 작성했고 실제 Supabase에는 적용하지 않았습니다. 상세 코드·개인화 서비스 계약·검증 경계는 [내 정보 API](docs/user-profile.md)를 확인하세요.

프로젝트 세팅과 기능 개발은 `작업 브랜치 → develop` PR로 통합하고, 배포는 `develop → main` PR로 진행합니다.

```text
app/
  api/
    health.py    # 프로세스·DB 연결 상태
    v1/router.py # 전체 기능 라우터 연결
  core/          # 설정·DB 세션·공통 오류
  models/        # Alembic에서 사용할 전체 모델 등록
  modules/
    auth/        # 회원가입·로그인·토큰
    users/       # 내 정보·사용자 조건
    policies/    # 정책·버전·출처·변경사항
    todos/       # 개인별 할 일·체크리스트
    chat/        # 정책 기반 챗봇·대화
    notifications/ # 알림 조회·읽음·생성
  main.py        # 앱 조립·CORS·요청 ID
alembic/         # migration 환경
tests/           # 동작 검증
scripts/         # 공통 검사 진입점
.agents/skills/  # 저장소 커밋·PR 스킬
```

- [에이전트 작업 지침](AGENTS.md)
- [전체 서버 구조와 모듈 연결](docs/architecture.md)
- [팀 전체 구현 단계와 연동 기준](docs/implementation-plan.md)
- [회원 인증 정책·DB 모델·migration 검증](docs/auth-design.md)
- [기능별 브랜치·커밋·PR 규칙](docs/branch-strategy.md)
- [하네스 구성과 공식 문서](docs/harness.md)

인증·내 정보·To-Do·챗봇 모듈에는 API·서비스·repository·스키마·모델을 구현했습니다. 정책 모듈은 버전·출처·대상 조건·필요 행동 모델과 검수 JSON 등록 CLI를 제공하며 HTTP 조회 API는 후속 작업입니다. 알림은 아직 빈 라우터입니다. 개인별 담당 계획은 `docs/workstreams/`에 분리해 관리하며 다른 팀원의 개발 범위를 제한하지 않습니다.

## 정책 데이터

상담은 [챗봇 API·근거·Gemini 설정](docs/policy-chatbot.md)을 따릅니다. 키와 모델은 기본값이 없으며 실제 외부 연결은 별도 검증합니다. 대화는 본인만 조회하며 같은 request_id 재전송을 중복 저장하지 않습니다.

개인별 할 일은 [To-Do API·재계산 규칙](docs/personalized-todos.md)을 따른다. 정책·조건 확인 후 명시적으로 동기화하며 완료 이력을 보존한다. revision `20261127_0100`은 실제 Supabase에 자동 적용하지 않는다.

공식 출처와 검수 기준은 [데이터.md](데이터.md), 저장 구조·모듈 계약·등록 방법은 [정책 데이터 구현](docs/policy-data.md)에 정리했습니다. 실제 정책과 구분한 [예시 JSON](examples/policies.example.json)을 다음 명령으로 검증할 수 있습니다. 기본 실행은 DB에 접속하지 않습니다.

```powershell
uv run python -m scripts.import_policies examples/policies.example.json
```

`--apply`를 명시하면 `DATABASE_URL`의 DB에 배치 전체를 트랜잭션으로 등록합니다. 스키마를 자동 생성하지 않습니다. 대상·권한을 확인하기 전에는 실제 Supabase에서 실행하지 마세요. revision `20261127_0003`은 네 정책 테이블과 PostgreSQL RLS 기본 차단을 추가하며 실제 Supabase에는 적용하지 않았습니다. API 수집기는 아직 구현하지 않았으므로 `PUBLIC_DATA_API_KEY`는 이 CLI에서 사용하지 않습니다.
