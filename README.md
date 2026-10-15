# BoSo-server

교통카드 정책 변화 요약, 개인별 할 일 관리, 정책 상담 챗봇을 제공하는 BoSo의 백엔드 저장소입니다. FastAPI, SQLAlchemy, Alembic, PostgreSQL을 사용하며 Supabase PostgreSQL 연동을 대상으로 합니다.

`chore/project-setup`은 모든 팀원이 함께 사용할 실행 환경, 전체 도메인의 모듈 틀, API 연결 지점, 작업 하네스를 제공합니다. 각 기능의 업무 로직과 테이블은 기능별 브랜치에서 추가합니다.

## 빠른 시작

Python 기준 버전은 3.12이며 uv가 해당 버전을 설치·선택합니다. 호환성 검사는 Python 3.12와 3.14를 대상으로 합니다. [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 uv를 준비하세요.

```powershell
uv sync --locked --extra dev
Copy-Item .env.example .env
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --no-access-log
```

`.env`가 이미 있으면 복사하지 말고 필요한 항목만 추가하세요. macOS/Linux에서는 `Copy-Item` 대신 `cp`를 사용합니다.

- Swagger: <http://localhost:8000/docs>
- 프로세스 상태: `GET /health/live`
- DB 연결 상태: `GET /health/ready`

상태 확인 이외의 기능 API는 아직 없습니다. `/health/ready`는 DB 연결만 검사합니다. 세팅 단계에는 도메인 테이블 migration이 없고 `alembic upgrade head`는 이후 migration 실행을 위한 환경을 확인합니다.

Docker 전체 실행은 `docker compose up --build`입니다. 이 Compose 파일은 로컬 개발용이며 DB 포트는 localhost에만 공개합니다. `docker compose down`으로 중지하고 데이터는 볼륨에 보존합니다.

## Supabase 연결 준비

Dashboard → Connect에서 Direct connection 또는 Session pooler 주소를 가져와 `.env`의 `DATABASE_URL`에 넣습니다. `postgresql://`를 `postgresql+psycopg://`로 바꾸고 `sslmode=require`를 지정합니다. 비밀번호의 예약 문자는 URL 인코딩합니다. IPv4 환경에서는 Session pooler를 사용합니다.

```dotenv
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
```

프로젝트 URL·anon key 대신 PostgreSQL 연결 문자열을 사용하는 방식입니다. 연결 문자열은 서버에서만 사용하고 커밋하지 않습니다. 로컬 Compose의 API는 로컬 DB를 사용하도록 구성되어 있으므로 Supabase 테스트는 `.env`와 호스트 실행 명령으로 진행하세요. 실제 Supabase 스키마·RLS·연결 검증은 별도 `feat/supabase-db` 브랜치에서 구현합니다. [공식 연결 안내](https://supabase.com/docs/guides/database/connecting-to-postgres)를 참고하세요.

## 검증

```powershell
uv run python scripts/check.py
```

Ruff lint·format 검사, pytest, Git 공백 검사를 순서대로 실행합니다. 로컬 테스트는 임시 SQLite를 사용합니다. `TEST_DATABASE_URL`을 테스트용 PostgreSQL로 지정하면 DB 연결 테스트도 실행합니다. 운영 DB를 테스트 대상으로 사용하지 마세요.

GitHub CI는 같은 검사와 별도 PostgreSQL 마이그레이션·Docker 빌드·컨테이너 상태 확인을 수행합니다. 개발 환경에 Docker 엔진이 실행 중이어야 컨테이너 검증이 가능합니다.

## 구조와 작업 규칙

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
- [기능별 브랜치·커밋·PR 규칙](docs/branch-strategy.md)
- [하네스 구성과 공식 문서](docs/harness.md)

기능별 디렉터리에는 현재 빈 라우터만 연결되어 있습니다. `/api/v1/*` 업무 API가 구현된 상태는 아닙니다. 개인별 담당 계획은 `docs/workstreams/`에 분리해 관리하며 다른 팀원의 개발 범위를 제한하지 않습니다.
