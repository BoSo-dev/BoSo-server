# 정책 데이터 모델과 검수 파일 등록

## 범위와 브랜치

`feat/policy-data`는 정책 ORM·Alembic revision·검수 JSON·등록 CLI·다른 모듈의 조회 계약을 구현한다. 정책 HTTP 목록·검색·상세는 다음 `feat/policy-api`에서 추가한다. 관리자 API, 자동 크롤러, API 수집기, 대상 적격 판정, 개인별 To-Do 생성, 챗봇·알림은 이 변경에 포함하지 않는다.

내 정보 PR [#4](https://github.com/BoSo-dev/BoSo-server/pull/4)의 지역·교통 코드 계약과 revision `20261127_0002`에 의존한다. 선행 코드 `3fa12570bf7d8a790776ed6a43bd626df52bfdb1`을 기반으로 작성했다. 통합 순서는 내 정보 → 정책 데이터이며, 선행 PR이 병합되면 정책 PR의 base·실제 diff·migration head를 확인한다.

출처·라이선스·실제 조회 결과는 루트 [데이터.md](../데이터.md)를 참고한다. 실제 정책 자료는 아직 등록하지 않았으며 예시 JSON은 운영 정책이 아니다.

## 모델과 제약조건

| 테이블 | 내용 | 주요 제약 |
| --- | --- | --- |
| `policies` | 고정 UUID·고유 `policy_key`·예시 여부·생성 시각 | 정책 키 UNIQUE, 빈 키 금지 |
| `policy_versions` | 버전 번호, 제목·카테고리·요약·본문·변경 요약, 생명주기, 적용 기간, 검수일·검수자, 대상 조건 JSON, SHA-256, 생성 시각 | `(policy_id, version)` UNIQUE, 양의 버전, 해시 길이 64, 기간·카테고리·생명주기 CHECK |
| `policy_sources` | 버전별 출처 키·유형·공개 URL·제목·외부 ID·확인일·이용조건 확인 | `(version_id, source_key)` UNIQUE, 유형·재사용 확인 CHECK |
| `policy_actions` | 버전별 행동 키·제목·설명·검증된 마감일·공개 URL | `(version_id, action_key)` UNIQUE, 마감일 인덱스 |

모든 PK는 UUID다. 적용일·검수일·마감일은 Date, 생성 시각은 timezone 지원 DateTime이다. 정책 버전 조회에는 `(policy_id, effective_from, version)` 인덱스를 사용한다. FK는 `RESTRICT`로 연결하여 부모 삭제로 버전·근거·행동 이력이 사라지지 않게 한다. 관리자가 직접 SQL로 이력을 덮어쓰는 것까지 DB trigger로 차단하지는 않으며, 업무 코드의 쓰기 경로는 append-only CLI다.

revision `20261127_0003`은 `20261127_0002` 다음에 네 테이블을 추가한다. PostgreSQL에서는 `public` 스키마의 해당 테이블만 변경한다. RLS를 활성화하고 PUBLIC 및 존재하는 `anon`, `authenticated`, `service_role`의 직접 테이블 권한을 회수한다. 허용 RLS 정책은 생성하지 않는다. Supabase `auth.users`·기존 테이블·기본 권한·역할은 변경하지 않는다. downgrade는 행동 → 출처 → 버전 → 정책 순으로 삭제한다.

서버 실행 계정은 DB 소유자·superuser·BYPASSRLS 계정이 아니면 별도 권한·RLS 설계가 필요하다. 이번 revision에 임의의 운영 역할명이나 전면 허용 정책을 추가하지 않는다. 실제 Supabase 적용·권한 분리·풀러→DB SSL 검증은 배포 전 별도로 수행한다.

## JSON 형식과 검증

[examples/policies.example.json](../examples/policies.example.json)은 실제 정책이 아닌 형식 예시다. 파일 최상위는 `schema_version: 1`과 `policies`이며 파일당 최대 100개 정책, 1 MiB다. 한 파일에는 같은 정책의 버전을 하나만 넣는다. 여러 순차 버전은 파일을 나누어 순서대로 등록한다. JSON 중복 키, 알 수 없는 필드, 부적절한 기간·유형·중복 행동/출처, 미래 검수일, 검수일 이후의 출처 확인일을 거부한다.

주요 필드:

- `policy_key`: 영문 소문자로 시작하는 최대 64자의 영문 소문자·숫자·`_`·`-`. 외부 ID와 별개이며 생성 후 고정한다.
- `version`: 1부터 시작하는 연속 정수. 동일 버전·동일 내용은 건너뛰고 동일 버전의 다른 내용은 거부한다. 새 버전의 적용 시작일·검수일은 직전 버전보다 과거로 이동할 수 없다. 같은 적용일의 정정은 더 큰 버전 번호로 등록한다.
- `is_example`: 정책 단위로 고정하는 실제 boolean. 출처 `kind=example`과 실제 자료를 섞지 않는다. CLI는 운영 환경·원격 PostgreSQL·접속 대상 재정의 옵션이 있는 환경에 예시 등록을 거부한다. 호스트명이 로컬이어도 실제 연결 대상(예: 터널)이 개발용인지 운영자가 확인해야 한다. 내부 소비 서비스도 예시를 반환하지 않는다.
- `category`: `transport_card`, `transport_fare`, `transport_support`, `transport_service`. UI 표시명은 후속 조회 API에서 정한다.
- `lifecycle`: `active` 또는 `ended`. 종료는 종료 적용일부터 새 `ended` 버전을 등록한다. 종료 버전에 새 행동은 넣지 않는다.
- `effective_from`: 필수 ISO 날짜. `effective_until`: 선택적 ISO 날짜이며 해당 일자까지 포함한다. 출처에 적용 시작일이 없으면 추측하여 등록하지 않는다.
- `sources`: 최소 하나. `public_api`·`official_page`·`example`, 외부 서비스 ID, 확인일, 이용조건 확인 메모를 남긴다. `reuse_confirmed=true`는 검수자가 실제 이용 범위를 확인했다는 선언이며 허락을 대신하지 않는다.
- URL: HTTPS 공개 주소만 허용한다. 인증정보·쿼리·fragment·비표준 포트는 거부한다. API의 키 포함 호출 URL 대신 공개 데이터 설명 페이지를 기록한다. CLI는 URL을 열거나 크롤링하지 않으며 도메인의 공식 여부는 검수자가 확인한다.
- `actions`: 최대 30개. `action_key`는 동일 행동을 버전 간 추적하는 업무 키이며 각 행에는 별도 UUID가 있다. `due_date=null`은 기한 미확정/없음이며 날짜를 임의로 보충하지 않는다. 카드 사용 만료·신청 마감·정책 종료를 같은 마감으로 간주하지 않는다.

SHA-256은 정규화한 입력 전체(검수 정보·조건·출처·행동 포함)로 계산한다. 출처·행동·지역/카드/수단 목록의 순서만 바뀐 경우 같은 내용으로 처리한다. 기존 검수 내용을 바꾸는 경우 새 버전을 작성한다. 기존 버전의 출처·행동을 갱신하거나 삭제하는 CLI는 제공하지 않는다.

## 대상 조건과 연동 계약

`EligibilityRules`는 `age_min`, `age_max`, `region_codes`, `transport_cards`, `transport_modes`, `additional_requirements`, `requires_confirmation`을 제공한다. 입력된 서로 다른 조건 종류는 AND, 한 목록 안의 값은 OR를 뜻한다. 빈 목록·null은 해당 단순 조건을 제한하지 않는다는 의미다. 복잡한 OR 조합·예외·소득·가구·증빙 조건은 `additional_requirements`에 명시하고 `requires_confirmation=true`를 유지한다. 이 플래그는 기본 true다. 보수적으로 판단할 정보가 부족하면 적격으로 확정하지 않는다.

나이는 내 정보 서비스가 기준일에 계산한 만 나이를 사용한다. 지역·교통카드·수단은 내 정보 코드 계약을 사용한다. `other_or_none`은 카드 보유 여부를 확정하지 못하므로 적격 조건에 쓸 수 없다. `climate_card`만으로 단기권·패스나 세부 권종을 판정하지 않도록 이 조건에는 추가 확인 플래그를 강제한다. 검수된 데이터라고 해서 모든 사용자에게 적용되는 것은 아니다. 판정·할 일 생성 규칙의 구현은 To-Do 모듈이 담당한다.

후속 모듈은 라우터 대신 아래 내부 서비스를 호출한다.

| 함수 | 반환과 동작 |
| --- | --- |
| `get_policy_context(db, policy_id, reference_date=None)` | 해당 기준일에 적용될 가장 최신 버전의 `PolicySnapshot`. 기본 기준일은 한국 날짜 |
| `get_version_context(db, version_id)` | 저장된 버전 ID로 이력을 조회. 원래 적용 시작일을 기준으로 snapshot 반환 |

Snapshot은 정책·버전 UUID, 버전 번호, 정책 키, 검수 내용, 조건, 출처, 행동 UUID·키·기한, 기준일·상태를 포함한다. 참조일 이전/당일 적용 버전 중 시작일·버전 번호가 큰 것을 먼저 선택한 뒤 `active`·`ended`·`expired`를 판단한다. 최신 적용 버전이 종료/만료여도 과거 활성 버전으로 돌아가지 않는다. 미래 버전만 있으면 `POLICY_NOT_EFFECTIVE` 404다. 만료/종료 snapshot도 근거 확인을 위해 반환되므로 To-Do 생성 시에는 `state=active`를 반드시 확인한다. 특정 버전의 이력 조회를 현재 정책 조회로 대신 사용하지 않는다.

사용자 식별자·회원정보를 정책 테이블에 복사하지 않는다. To-Do는 사용자·정책 버전·행동 키의 중복 규칙과 완료 이력을, 챗봇은 답변에 사용한 버전·공식 URL을 보존해야 한다. 알림은 정책 수집이 아닌 To-Do의 확정 이벤트를 기준으로 연결한다. 구체적인 재생성·완료 유지·알림 시점은 각 기능에서 확정하며 이번 서비스가 자동 수행하지 않는다.

## 명령과 트랜잭션

저장소 루트에서 실행한다. 아래 기본 명령은 `.env`를 읽거나 DB에 접속하지 않고 파일만 검증한다.

```powershell
uv run python -m scripts.import_policies examples/policies.example.json
```

실제 검수 파일을 등록할 때는 대상 DB와 스키마 적용을 확인하고 명시적으로 실행한다. 이 문서 작성 중에는 실제 Supabase 등록·마이그레이션 명령을 실행하지 않았다.

```powershell
uv run python -m scripts.import_policies PATH_TO_REVIEWED_JSON --apply
```

`--apply`는 `DATABASE_URL`을 사용하고 스키마를 자동 생성하지 않는다. `MIGRATION_DATABASE_URL`은 Alembic 전용이다. 예시 입력을 실제 검수 파일로 복사하면서 예시 출처를 실재 출처로 위장하지 않는다. 정책별 upsert 후 행 잠금으로 최초 동시 등록도 직렬화하고, 배치 전체를 같은 트랜잭션에서 commit한다. 뒤 항목 실패·commit 실패 시 전체 rollback한다. 여러 정책의 잠금 순서를 키 기준으로 고정한다. SQLite는 기능 테스트용이며 동시성 보장은 PostgreSQL에서 검증한다.

출력은 성공 건수 또는 고정된 오류 코드만 포함한다. 입력 본문·파일 경로·검수자·DB URI·SQL·드라이버 오류 원문은 출력하지 않는다. 실제 등록 성공 출력은 commit 이후에만 발생한다. 중복 JSON 키·큰 파일·입력 오류·버전 충돌도 내용 비노출을 유지한다.

## 검증 범위

기본 검사: `uv run python scripts/check.py`. 기능 검사: `uv run python -m pytest tests/test_policy_data.py tests/test_policy_migrations.py`.

기존 CI의 PostgreSQL job은 head upgrade·Alembic check·전체 테스트를 실행하므로 새 revision과 정책 테스트도 실행 대상이다. 테스트는 기존의 로컬 disposable PostgreSQL fixture를 재사용하며 `TEST_DATABASE_URL`이 없으면 PG 실행 검증을 skip한다. 실제 Supabase로 대체하지 않는다. 세부 실행 결과는 작업 완료 보고·향후 PR에 기록한다. 자동 수집·실제 정책 데이터 등록·실제 Supabase RLS·배포·후속 API/To-Do/챗봇/알림은 이 검증에 포함되지 않는다.

2026-11-27 로컬 최종 검사에서는 Python 3.12.15와 폐기 가능한 PostgreSQL 17 컨테이너를 사용해 `scripts/check.py`를 실행했고 **386개 통과, 제외 0개**였다. Ruff lint·format·Git 공백 검사도 통과했다. 정책 upgrade·downgrade·Alembic metadata 일치, 권한 회수·RLS 기본 차단, 동시 최초 등록·충돌, 날짜 경계·불변 버전·배치 rollback·commit 실패·비밀 비노출을 검증했다. SQLite의 기존 이메일 표현식 인덱스 반영 한계 경고가 4회 발생했으며 PostgreSQL metadata 비교는 통과했다. 기본 CLI 실행은 DB 미접속 응답을 확인했다. 검사 컨테이너는 정리했고 `.env` 해시는 검사 전후 동일했다. 이 결과는 GitHub CI나 실제 Supabase 실행 결과를 대신하지 않는다.

SQLAlchemy의 [제약조건·인덱스](https://docs.sqlalchemy.org/en/20/core/constraints.html), Alembic의 [테이블 연산](https://alembic.sqlalchemy.org/en/latest/ops.html#alembic.operations.Operations.create_table)을 참고했고, 테이블·JSON 계약·등록 제한은 BoSo 구현 선택이다.
