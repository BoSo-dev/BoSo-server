# 정책 상담 챗봇

회원·프로필·정책 데이터·To-Do 계약이 선행한다. `20261127_0110`은 `20261127_0100` 다음에 대화와 질문/응답 쌍을 저장한다. 등록된 정책과 내부 조회 서비스를 사용하므로 정책 HTTP API 구현을 기다리지 않아도 동작한다.

## API

모든 경로는 Bearer 인증·본인 소유권 검증·no-store를 적용한다.

| 경로 | 내용 |
| --- | --- |
| POST /api/v1/chat/conversations | `{}` 또는 title, 대화 생성 |
| GET /api/v1/chat/conversations | 본인 대화 목록, limit/offset |
| GET /api/v1/chat/conversations/{id}/messages | 질문/답변 쌍 목록, limit/offset |
| POST /api/v1/chat/conversations/{id}/messages | request_id UUID, question 1..2000자, 선택 policy_ids 최대 5개 |

메시지 목록의 한 item은 turn_number·question·answer·sources·related_todos·needs_more_info·external_used를 포함한다. 화면은 각 쌍을 사용자/챗봇 메시지로 표현할 수 있다. 같은 request_id와 같은 본문은 기존 응답을 반환하고, 본문이 다르면 409다. 대화별 행 잠금과 UNIQUE로 동시 재전송을 직렬화한다. 외부 응답 실패 시 대화의 질문/답변 쌍을 부분 저장하지 않는다. DB commit 실패 후 재시도는 외부 호출이 반복될 수 있으므로 완전한 외부 과금 exactly-once를 보장하지 않는다.

## 근거와 개인화

정책 ID를 지정하면 현재 기준일의 해당 정책 버전을 조회한다. 생략하면 제목·요약의 질문 단어로 최대 5개를 조회하고, 이어지는 질문은 직전 대화의 정책 ID로 최신 버전을 다시 조회한다. 이 방식은 전문 검색·벡터 검색이 아니며 모든 자연어 질문에 정책을 찾아준다고 보장하지 않는다.

정책이 없으면 Gemini를 호출하지 않고 정보 부족 안내를 저장한다. 예시 정책은 근거로 사용하지 않는다. 서버가 대상 조건을 eligible/not_eligible/unknown으로 판정하고 종료·만료 정책은 비활성으로 전달한다. 모델이 대상 판정이나 마감일을 새로 정하거나 할 일을 수정하지 않는다.

모델이 반환한 version_id/source_key를 실제 전달한 근거 목록과 대조한다. 허용된 출처가 없거나 가짜 참조가 포함되면 답변을 고정된 정보 부족 안내로 교체한다. URL은 모델 출력에서 받지 않고 검수 DB에서 구성한다. 올바른 출처 ID가 있다고 답변 문장 전체의 사실성이 자동 검증되는 것은 아니므로 정책 원문·검수 품질과 응답 평가가 필요하다.

Gemini에는 질문, 최근 최대 3개의 질문/응답 쌍, 최대 5개 정책의 제한된 본문·행동·공식 근거 키, 서버의 판정만 전달한다. 내부 사용자 ID·이메일·생년월일 원문·인증키는 프롬프트에 추가하지 않는다. 사용자가 질문에 적은 내용은 외부 API로 전송될 수 있다. 원문 질문·답변은 개인 대화 DB에 저장하며 HTTP 로그에는 남기지 않는다. 보관 기간·삭제·운영 접근 권한은 배포 정책에서 확정한다.

related_todos는 인증 사용자의 관련 정책에 속하는 보관되지 않은 할 일만 반환한다. 상담이 할 일을 생성/완료/취소하지 않는다.

## Gemini 설정과 장애

루트 .env 또는 배포 비밀 저장소에 GEMINI_API_KEY와 GEMINI_MODEL을 직접 설정한다. 기본 모델·키는 없으며 실제 호출 가능한 모델 이름은 Gemini 프로젝트에서 선택한다. 기존 .env를 덮어쓰지 않는다. 환경변수를 바꾸면 프로세스를 재시작한다.

표준 라이브러리 HTTPS 클라이언트를 사용한다. 호스트는 Google 공식 API로 고정하고 인증키는 x-goog-api-key 헤더에만 넣는다. redirect를 따라가지 않는다. timeout 기본 10초(최대 30초), 응답 최대 64 KiB, 출력 토큰 기본 1024(최대 2048)다. 키·모델 미설정은 503, upstream 장애·429·timeout은 고정된 503 오류, 잘못된/불완전 응답은 502다. 드라이버·외부 응답 원문·키를 오류에 포함하지 않는다.

외부 호출은 사용자별 프로세스당 분당 10회로 제한하고 메모리 항목은 4096개로 제한한다. 운영에서는 여러 worker에 공유되는 gateway quota와 프로젝트 사용량 제한이 필요하다. 실제 비용·사용 한도·가용 모델은 공급자 계정 설정을 따른다.

공식 명세: [generateContent](https://ai.google.dev/api/generate-content), [구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output). JSON 응답 형태·근거 검증·개인화 판정·한도는 BoSo 구현 선택이다.

## DB·검증

chat_conversations는 사용자 FK CASCADE, chat_turns는 대화 FK CASCADE다. 요청 ID·turn 번호 UNIQUE와 해시/번호 CHECK를 적용한다. RLS 기본 차단·클라이언트 직접 권한 회수를 적용하며 실제 Supabase의 역할이나 auth.users를 변경하지 않는다.

기능 검사는 `uv run python -m pytest tests/test_chat.py tests/test_chat_migrations.py`, 전체 검사는 `uv run python scripts/check.py`다. provider 대역으로 정상 응답·가짜 근거·장애·비밀 비노출을 확인한다. 실제 Gemini 호출·모델 가용성·과금·실제 Supabase 적용은 미검증이며 ZIP의 VALIDATION.md에 실행 범위를 기록한다.
