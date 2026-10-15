# BoSo 작업 지침

## 현재 범위

- FastAPI + SQLAlchemy + Alembic, Supabase PostgreSQL을 사용하는 서버다.
- 이번 담당 기능은 회원, 교통 정책 목록·상세 조회, 정책 데이터 등록·관리, Supabase DB 연동이다.
- 관리자 API·권한·화면은 제외한다. 정책 데이터 관리는 검수 파일을 가져오는 CLI로 구현한다.
- To-Do, 챗봇, 알림, 프론트엔드는 별도 요청 전까지 구현하지 않는다.
- `docs/implementation-plan.md`에서 현재 구현 단계와 후속 작업을 확인한다. 계획과 구현 완료를 구분한다.

## 시작점과 명령

- `git status --short`와 현재 브랜치를 먼저 확인한다. 사용자 변경 및 기획 PDF·화면 PNG를 보존하고 관련 없는 파일을 커밋에 섞지 않는다.
- Python 기준 버전은 `.python-version`, 의존성 정의는 `pyproject.toml`, 실제 설치 버전은 `uv.lock`이다.
- 설치: `uv sync --locked --extra dev`
- 실행: `uv run uvicorn app.main:app --reload --no-access-log`
- 통합 검사: `uv run python scripts/check.py`
- 자동 정리: `uv run ruff check --fix .` 및 `uv run ruff format .` — 자신이 수정하는 파일 범위에 한해 실행한다.
- 마이그레이션: `uv run alembic upgrade head`. 기본 DB는 로컬 PostgreSQL이며 Supabase 주소는 `.env`로 주입한다.
- 로컬 DB: `docker compose up -d db`. Docker가 없거나 미실행 상태면 그 사실을 보고하고 가능한 로컬 검증을 완료한다.
- 사용자 `.env`의 값·DB 비밀번호·JWT·Supabase 키를 도구 출력, 로그, 커밋, PR에 노출하지 않는다.

## 구현 규칙

- 상태 확인은 `/health/*`, 기능 API는 `/api/v1/*`에 둔다.
- API 경로·입출력은 Pydantic/OpenAPI로 정의한다. API 계층, 업무 서비스, DB 조회 코드를 기능별로 분리한다.
- 동기 SQLAlchemy를 쓰는 엔드포인트는 `def`로 선언한다. 세션은 요청 단위이며 성공 시 commit, 실패 시 rollback한다.
- 테이블 변경은 모델과 Alembic revision을 함께 추가하고 `app/models/__init__.py`에 모델을 등록한다. 서버 시작 시 `create_all()`로 운영 스키마를 변경하지 않는다.
- 운영 대상은 PostgreSQL이다. SQLite 테스트만 통과한 것을 Supabase 연동 완료로 보고하지 않는다.
- Supabase 연결 문자열은 서버에서만 사용한다. RLS·스키마 변경은 이후 DB 연동 브랜치에서 명시적으로 구현·검증한다.
- 정책의 공식 출처 URL·검수일·적용 기간·변경 전후 내용을 보존한다. 예시 데이터는 실제 정책과 구분한다.
- 오류는 `code`, `message`, `details`, `request_id`를 사용하고 DB·인증 관련 내부 값을 응답에 담지 않는다.
- 회원 기능에는 비밀번호 해시, 토큰 만료·갱신·폐기, 사용자별 접근 제어를 포함한다. 인증 정보를 평문 저장하지 않는다.
- 기능 변경은 정상·오류·경계 조건을 검증한다. 인증은 다른 사용자의 데이터 접근 및 만료·폐기를, DB 변경은 PostgreSQL 마이그레이션을 검증한다.
- CI에서 실제 실행하지 않은 외부 연결, 배포, Gemini 호출 등을 완료했다고 쓰지 않는다.

## 브랜치·커밋·PR

- 기능마다 브랜치를 나눈다. 브랜치 이름과 초기 저장소 예외는 `docs/branch-strategy.md`를 따른다.
- 커밋 작업 시 `.agents/skills/boso-commit/SKILL.md`를 읽고 적용한다.
- PR 작성·갱신 시 `.agents/skills/boso-pr/SKILL.md`를 읽고 적용한다.
- 커밋·PR 제목은 `<type>(<scope>): <설명>` 형식을 사용한다. 설명·본문은 한국어를 기본으로 한다.
- 로컬 커밋, 원격 push, PR 게시, merge는 각각 사용자 요청과 기존 허용 범위에 맞게 수행한다. 스킬을 읽는 것 자체가 외부 쓰기 권한을 주지는 않는다.
- 사용자 변경을 지우는 reset/checkout, 강제 push, 기존 커밋 amend는 명시적 요청 없이 수행하지 않는다.
- PR 전에는 실제 diff를 읽고 관련 검사 결과와 미검증 사항을 기록한다. 사람이 검토할 수 있는 변경 단위로 유지한다.

## 하네스 유지

- 공통 규칙은 이 파일, 반복 작업은 `.agents/skills/`, 실행 검증은 `scripts/check.py`와 `.github/workflows/ci.yml`에 둔다.
- 실제 명령·구조가 바뀌면 관련 지침과 README를 같은 변경에서 수정한다. 실행되지 않는 가상 절차를 늘리지 않는다.
- 개인 Codex 설정, 승인 정책, 전역 Git 설정은 이 저장소의 세팅을 위해 변경하지 않는다.
- 설계 근거와 공식 문서는 `docs/harness.md`에 연결한다. 출처의 요구사항과 BoSo가 선택한 팀 규칙을 구분한다.
