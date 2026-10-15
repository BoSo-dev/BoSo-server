# BoSo 공통 서버 구조

## 구성과 현재 상태

하나의 FastAPI 서버 안에서 기능별 모듈을 나누는 구조다. 모든 기능이 설정·DB 세션·오류 처리·테스트·CI를 공유한다. 현재 공통 세팅은 아래 모듈의 빈 라우터를 연결한 상태이며, 실제 업무 API는 기능별 브랜치에서 추가한다.

| 모듈 | 책임 | 기본 API prefix |
| --- | --- | --- |
| `auth` | 가입·로그인·토큰 갱신·로그아웃 | `/api/v1/auth` |
| `users` | 내 정보·개인화 조건·보유 교통카드 | `/api/v1/me` |
| `policies` | 정책·버전·출처·대상 조건·변경사항 | `/api/v1/policies` |
| `todos` | 개인별 할 일·체크리스트·진행 상태 | `/api/v1/todos` |
| `chat` | 정책 기반 상담·대화·근거 연결 | `/api/v1/chat` |
| `notifications` | 알림 생성·조회·읽음 처리 | `/api/v1/notifications` |

위 prefix는 라우터 연결을 위한 공통 기본값이며 아직 공개된 업무 엔드포인트 목록이 아니다. 기존 `/health/live`, `/health/ready`만 실행 가능하다. 추가 도메인·별도 경로가 필요하면 제공 모듈과 API 연결 파일을 함께 갱신한다.

## 코드 배치

```text
app/
  main.py                    # 앱 구성, 공통 미들웨어
  api/
    health.py                # 상태 확인
    v1/router.py             # 전체 도메인 라우터 조립
  core/
    config.py                # 환경변수·설정
    db.py                    # Base·엔진·요청 세션
    dependencies.py          # 응답 전 트랜잭션을 마치는 DbSession
    errors.py                # AppError·공통 오류 응답
  models/__init__.py         # 전체 ORM 모델 등록 지점
  modules/
    auth/
    users/
    policies/
    todos/
    chat/
    notifications/
alembic/                     # DB 스키마 이력
tests/                       # 공통·도메인·통합 검증
```

각 모듈의 `__init__.py`와 `router.py`는 생성되어 있다. 기능 구현 시 같은 모듈에 `schemas.py`(입출력), `service.py`(업무 규칙), `repository.py`(DB 조회), `models.py`(ORM)를 필요에 맞게 추가한다. 외부 API 클라이언트는 사용하는 모듈 안에 둔다.

요청 처리는 `router → service → repository → DB`로 이어진다. 라우터는 입력·인증 의존성·응답 변환을, 서비스는 업무 규칙과 다른 서비스 연결을, repository는 조회·저장을 담당한다. 트랜잭션의 성공·실패 기준은 서비스에서 정하고 요청 DB 의존성은 공통 `DbSession`을 사용한다. 비동기 라우터에서 동기 DB·외부 클라이언트를 직접 실행해 이벤트 루프를 막지 않는다.

`DbSession`은 `get_db`를 `scope="function"`으로 연결해 성공 응답 전에 commit·rollback과 세션 종료를 완료한다. 이를 사용하는 인증 등 상위 의존성도 function scope로 선언한다. 스트리밍·백그라운드 작업은 종료된 요청 세션을 재사용하지 않고 필요한 값을 미리 조회하거나 별도 세션을 연다. [FastAPI의 의존성 종료 시점 안내](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope)를 따른다.

도메인 모델은 공통 `Base`를 상속하고 `app/models/__init__.py`에서 import해 Alembic metadata에 등록한다. 같은 모델을 여러 모듈에 중복 정의하지 않는다. 도메인 서비스는 필요한 서비스를 명시적으로 호출하며 다른 라우터를 직접 호출하지 않는다. `core`는 도메인을 import하지 않는다.

## 기능 사이의 연결

- 회원 모듈은 인증된 사용자 식별자를 제공하고 내 정보 모듈은 지역·나이·교통카드 등 개인화 조건을 제공한다.
- 정책 모듈은 출처가 있는 정책 버전·대상 조건·필요 행동을 제공한다. 정책 조회·할 일·챗봇이 이 정보를 공동 사용한다.
- To-Do 모듈은 조건 판정·할 일 생성·체크 상태의 기준을 소유한다. 챗봇은 관련 할 일을 연결하고 알림은 새 할 일·마감 상태를 참조한다.
- 알림 생성 시점과 재실행 방식은 To-Do·알림 기능에서 함께 정한다. 외부 발송·스케줄러 처리는 DB 반영 성공 여부와 중복 실행을 고려한다.
- 챗봇의 설명과 대상 여부 판정을 구분한다. 검수된 정책과 허용된 사용자 조건만 외부 AI에 전달한다.

현재 단계에는 위 서비스·테이블·외부 호출이 없다. 후속 PR은 제공할 ID·스키마·서비스 입출력과 오류 동작을 문서화해 연동한다.

## 공통 API·프론트엔드·검증

- 프론트엔드는 서버의 OpenAPI와 환경별 CORS 설정을 기준으로 연동한다. 이 저장소의 개인 작업 계획이 프론트엔드나 다른 팀원의 기능을 제한하지 않는다.
- 성공 응답은 기능별 Pydantic 모델, 오류 응답은 공통 `AppError` 형식을 사용한다. 토큰·DB 연결 정보·사용자 질문 원문을 로그에 남기지 않는다.
- 테스트는 `tests/test_<기능>.py` 또는 `tests/<기능>/`에 둔다. 공통 fixture를 재사용하고 사용자 간 접근, 정책 경계 조건, 외부 장애를 기능에 맞게 검증한다.
- 공통 기반 변경은 `uv run python scripts/check.py`, DB 변경은 PostgreSQL·Alembic 검사까지 수행한다. 실제 외부 연결이 없는 검증은 대역임을 기록한다.

라우터 조립 방식은 [FastAPI 공식 안내](https://fastapi.tiangolo.com/tutorial/bigger-applications/)를 참고했다. 도메인 목록·서비스 경계·파일 배치는 BoSo의 공통 개발 구조다.
