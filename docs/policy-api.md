# 정책 조회 API

기준 브랜치는 팀원 기능이 병합된 develop(`ab7aded`)이다. 기존 정책 테이블·검수 등록 CLI·To-Do·챗봇의 내부 계약을 유지하고 HTTP 조회만 추가한다. DB 모델·revision·환경변수는 변경하지 않는다.

## 경로

| 메서드·경로 | 인증 | 동작 |
| --- | --- | --- |
| GET /api/v1/policies | 없음 | 현재 적용 버전 목록·검색·카테고리·상태·페이지 |
| GET /api/v1/policies/categories | 없음 | 기존 네 카테고리 코드·한국어 표시명 |
| GET /api/v1/policies/for-me | Bearer | 본인 조건에 따른 적격/비대상/미확인 목록 |
| GET /api/v1/policies/{policy_id} | 없음 | 현재 버전의 내용·대상 조건·필요 행동·공식 출처 |
| GET /api/v1/policies/{policy_id}/sources | 없음 | 현재 버전의 공식 출처 목록 |
| GET /api/v1/policies/{policy_id}/versions | 없음 | 공개된 버전 이력·페이지 |
| GET /api/v1/policies/{policy_id}/versions/{version} | 없음 | 지정한 공개 버전의 상세 |
| GET /api/v1/policies/{policy_id}/changes | 없음 | 변경 전·후 상세와 변경 필드 |

경로의 policy_id는 BoSo UUID이고 version은 양의 정수다. UUID·숫자·enum·길이·페이지 범위가 잘못되면 공통 422 오류다. 없는 정책·예시 정책·미래 버전은 404다. 관리자 쓰기 API는 제공하지 않는다.

## 목록과 공개 기준

공개 정책은 is_example=false이며 effective_from이 한국 날짜의 오늘 이전/당일인 버전이다. 수정일·검수일을 적용 시작일로 대신 사용하지 않는다. 미래 적용 버전은 목록·검색·상세·이력·비교에서 공개하지 않는다. 별도 게시 상태/게시 예약 시각이 없는 현재 모델에서 적용 시작일을 공개 기준으로 선택한 것이다.

정책별로 적용 시작일·버전 번호가 가장 큰 버전을 먼저 고른 뒤 검색·카테고리·상태를 필터링한다. 새 버전이 종료되거나 검색어·카테고리가 달라졌다고 예전 버전을 목록에 다시 노출하지 않는다. 같은 적용 시작일의 정정은 큰 버전 번호가 우선한다. 종료일은 해당 날짜까지 포함한다.

- q: 제목·요약·본문의 대소문자 구분 없는 부분 검색. 앞뒤 공백을 제거하고 1..100자만 허용한다. 공백만 있는 검색어는 거부한다. `%`·`_`는 와일드카드가 아니라 실제 문자로 검색한다. 검색 이력은 저장하지 않는다.
- category: transport_card / transport_fare / transport_support / transport_service.
- state: active(기본) / ended / expired / all. ended는 명시적 종료, expired는 종료일 경과다.
- limit: 기본 20, 1..100. offset: 기본 0, 0..1,000,000. 과도한 숫자는 DB에 전달하기 전에 422로 거부한다. 적용 시작일 내림차순·고정 정책 키 순으로 정렬한다. 결과가 없는 페이지도 전체 total을 반환한다.
- response: items / total / limit / offset / reference_date. 목록은 긴 본문·행동·출처를 중복 반환하지 않는다.

일반 목록의 total과 항목 조회는 두 SQL 문장이다. READ COMMITTED에서 조회 사이 새 정책이 등록되면 차이가 있을 수 있으므로 다시 조회한다. 한 페이지의 버전 선택·필터는 같은 SQL에서 수행한다. 검색은 부분 문자열이며 형태소·동의어·벡터 검색을 제공하지 않는다.

## 상세·이력·비교

요약에는 policy_id·policy_key·version_id·version·제목·카테고리·요약·state·is_current·적용 기간·검수일을 제공한다. 상세는 본문·변경 설명·대상 조건·검수된 공식 출처·행동 UUID/키/기한을 추가한다. 검수자 식별자·내부 해시·회원정보는 공개 응답에서 제외한다. 등록 데이터가 없으면 빈 목록을 반환하며 실제 정책을 임의로 생성하지 않는다.

현재 버전이 아닌 공개 이력은 state=superseded, is_current=false로 구분한다. 이력의 행동·출처는 해당 버전의 원래 내용을 보존하며 현재 적격 판정이나 할 일 생성에 사용하지 않는다. 기존 내부 get_policy_context/get_version_context의 반환 구조·동작은 유지한다.

changes의 from_version과 to_version은 선택적인 양의 정수다. 기본 to는 현재 공개 버전, 기본 from은 to의 직전 버전이다. 최초 버전은 before=null이다. 없는/다른 정책의/미래 버전은 404, from>=to는 422다. 제목·카테고리·요약·본문·적용 기간·조건·출처·행동·lifecycle을 비교한다. 버전마다 새로 생성되는 행동 UUID를 제외하고 행동 키와 실제 내용으로 비교한다. change_summary는 검수자가 기록한 변경 설명으로 보존한다.

## 본인 맞춤 조회

for-me는 검증된 CurrentUser의 ID와 내 정보 서비스만 사용한다. 임의 사용자 ID 입력이나 생년월일·지역을 쿼리로 받지 않는다. To-Do의 evaluate_eligibility를 재사용해 eligible/not_eligible/unknown과 이유 필드명을 반환한다. 추가 확인·미입력·other_or_none을 자동 적격으로 판단하지 않는다. 비활성 정책은 항상 not_eligible다.

일반 목록 필터에 eligibility=eligible/not_eligible/unknown을 추가할 수 있다. 대상 판정 후 total과 페이지를 계산한다. SQL 후보를 스트리밍하고 페이지 항목만 보관한다. 조건 필터의 정확한 total을 계산하려면 후보 전체를 평가하므로 큰 데이터셋에서는 별도 검색/인덱싱 최적화가 필요하다. 프로필은 요청당 한 번 읽으며 정책별로 회원정보를 재조회하지 않는다.

개인화 응답·인증 오류는 Cache-Control:no-store와 Pragma:no-cache를 적용한다. 개인 조건 원문은 응답에 추가하지 않는다. GET 요청은 프로필·To-Do·대화·알림을 생성하거나 수정하지 않는다. 기존 To-Do·챗봇·알림 서비스의 정책 조회 경계는 변경하지 않는다.

## 검증과 운영 범위

`uv run python scripts/check.py`가 통합 검사다. 새 기능은 `uv run python -m pytest tests/test_policy_api.py tests/test_policy_api_postgres.py`로 확인한다. PostgreSQL 테스트는 기존 disposable local *_test fixture만 사용하며 TEST_DATABASE_URL이 없으면 제외한다. 실제 Supabase로 대체하지 않는다.

예시/미래 버전 숨김, 상태·검색 필터의 과거 버전 복귀 방지, 동일 날짜 정정, 종료일 경계, 빈 페이지 total, LIKE 문자 이스케이프, 공개 버전 간 비교, 본인 조건·인증·캐시·읽기 전용을 검증한다. 기존 정책 데이터와 팀원 기능의 회귀 테스트도 함께 실행한다.

실제 Supabase 적용·실제 정책 등록·외부 API 수집·Gemini 실제 호출·프론트엔드 연동·배포·GitHub CI는 로컬 결과로 완료했다고 간주하지 않는다. 이번 작업에서 실제 .env·DB 비밀번호·테이블·데이터는 변경하지 않는다.

최종 로컬 검사는 Python 3.12.15와 폐기 가능한 PostgreSQL 17에서 `uv run --locked --extra dev python scripts/check.py`로 실행했다. **448개 통과, 제외 0개**이며 Lint·포맷·Git 공백 검사도 통과했다. 새 API 테스트 19개와 PostgreSQL 조회 테스트 1개, 기존 428개 회귀 검사를 포함한다. 기존 SQLite 이메일 표현식 인덱스 reflection 경고 4건이 있었고 PostgreSQL metadata 검사는 통과했다. 검사 컨테이너는 정리했고 `.env`는 검사 전후 동일했다. migration head는 기존 `20261127_0120`을 유지한다.
