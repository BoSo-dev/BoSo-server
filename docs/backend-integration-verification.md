# 백엔드 기능 연결 검증

검증일: 2026-11-28. 대상은 Docker의 폐기 가능한 PostgreSQL 17이며 실제 Supabase가 아니다. `.env`를 수정하지 않고 테스트 프로세스에만 `TEST_DATABASE_URL`을 주입했다. 기존 fixture가 로컬 `*_test` 접속만 허용하고 테스트별 임시 DB를 생성·삭제한다. 애플리케이션 URL과 마이그레이션 URL도 그 임시 DB로 격리한다.

## 추가한 HTTP 통합 테스트

`tests/test_backend_integration.py`는 기존 PostgreSQL·인증 fixture와 Alembic head를 사용한다. 운영 API를 수정하지 않았다.

- 두 회원 가입·로그인 → 자기 인증 확인 → 내 정보 저장과 타 회원 프로필 분리.
- 정책 목록·상세 → 내 조건에 맞는 적격 판정과 다른 회원의 정보 부족 판정.
- To-Do 생성 → 반복 동기화 중복 방지 → 타 회원 조회·수정 차단 → 완료 상태·요약 반영.
- 새 할 일·마감 임박 알림 → 중복 방지 → 본인 읽음 처리·반복 처리 → 타 회원 접근 차단.
- 챗봇 대화 → 서버가 검증한 출처와 본인 To-Do 연결 → 같은 요청 재전송 중복 방지 → 타 회원 대화 접근 차단.
- 잘못된 CSRF·Origin 차단 → Refresh Token 갱신 → 세션 만료 거부 → 현재 세션 로그아웃 후 보호 API 접근 차단 → 다른 회원 세션 유지.
- 실제 K-패스 파일을 테스트 DB에만 불러와 추가 확인이 필요한 상태에서 To-Do·알림을 생성하지 않는 흐름.

적격 흐름의 정책은 가상 테스트 자료이며 이 테스트에서만 사용한다. 실제 K-패스를 자동 적격으로 변경하거나 사용자에게 지급을 보장하지 않는다. Gemini는 네트워크 호출 대신 테스트 응답을 주입한다. `external_used` 필드 확인은 내부 처리 경로의 검증이며 실제 Gemini 호출 성공을 의미하지 않는다.

## 재실행

로컬 전용 PostgreSQL을 준비하고 해당 프로세스에만 `TEST_DATABASE_URL`을 지정한다. 외부 서비스 URL이나 Supabase 주소를 넣지 않는다. fixture가 역할 생성·삭제도 수행하므로 다른 프로젝트와 공유하지 않는 전용 클러스터를 사용한다.

```powershell
uv run python -m pytest tests/test_backend_integration.py -q
uv run python scripts/check.py
```

추가 테스트 2개는 PostgreSQL에서 통과했다. 전체 `scripts/check.py` 검사도 **450개 통과, 제외 0개**로 완료했다. Ruff lint·format과 Git 공백 검사도 통과했다. 기존 SQLite 표현식 인덱스 반영 관련 경고가 4회 발생했으며 PostgreSQL 마이그레이션·RLS·동시성 테스트는 모두 실행됐다. 검증용 컨테이너는 종료 후 제거한다.

브라우저·프론트엔드 연결, 실제 Gemini 호출·응답 품질, 운영 DB 최소 권한 계정과 배포 환경 검증은 별도 작업이다. `.env`는 Git에서 제외되어 있으며 새 파일의 환경변수 비밀 값 포함 여부 검사도 통과했다. 커밋·push·PR은 수행하지 않았다.
