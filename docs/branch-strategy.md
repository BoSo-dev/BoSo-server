# 브랜치·커밋·PR 운영

## 브랜치

하나의 브랜치에는 하나의 기능 또는 검토 가능한 공통 세팅을 담는다.

| 브랜치 | 용도 |
| --- | --- |
| `main` | 검토를 거친 기준·배포 버전 |
| `develop` | 모든 개발 작업의 분기 기준·PR 통합 대상 |
| `chore/project-setup` | 최초 프로젝트 세팅·작업 하네스 |
| `feat/supabase-db` | Supabase 연결·DB 운영 환경 |
| `feat/auth` | 회원 기능 |
| `feat/user-profile` | 내 정보·개인화 조건 |
| `feat/policy-data` | 정책 데이터 모델·파일 관리 |
| `feat/policy-api` | 정책 목록·상세 조회 |
| `feat/personalized-todos` | 개인별 할 일·체크리스트 |
| `feat/policy-chatbot` | 정책 근거 기반 상담·대화 |
| `feat/in-app-notifications` | 새 할 일·마감 알림·읽음 처리 |
| `chore/deployment` | 공통 운영·배포 환경 |
| `fix/<내용>` | 기존 기능 오류 수정 |

개발 흐름은 `작업 브랜치 → develop → main`이다. 프로젝트 세팅도 `chore/project-setup → develop` PR로 검토·통합한다. 배포 시에는 `develop → main` PR을 사용한다.

초기 `develop`은 현재 `main` 커밋에서 생성한다. 세팅 변경은 작업 브랜치에 push하고 PR을 통해 통합한다. `develop` 생성과 PR 대상 지정은 실제 refs를 확인해 수행하며, 브랜치 보호 변경·PR merge는 별도 요청 범위에 따른다.

기능 브랜치는 세팅이 통합된 최신 `develop`에서 만든다. 선행 PR 병합 전 구현이 필요하면 해당 선행 브랜치에서 분기하고, PR base·의존 관계를 명시한다. 무관한 기능들을 `feat/backend-mvp` 하나에 모으지 않는다.

이 목록은 팀 전체 작업을 나누는 기준이며 특정 팀원의 담당표가 아니다. 담당자와 순서는 개별 작업 문서·이슈·PR에서 정한다. 목록에 없는 기능도 팀 요구사항에 맞는 브랜치를 추가할 수 있다.

## 병렬 작업과 공통 파일

- 각 팀원은 담당 도메인의 `app/modules/<기능>/`에서 작업한다. 기존 모듈의 라우터는 연결되어 있으므로 엔드포인트를 추가할 때 `app/main.py`를 수정할 필요가 없다.
- 모델 등록 파일, 환경변수, 공통 DB·오류 처리, API 연결 파일 변경은 PR에 영향 범위를 적고 충돌 시 상대 변경을 보존한다.
- 도메인 테이블과 Alembic revision은 해당 기능 PR에 포함한다. 병합 전 최신 기준과 revision 그래프를 확인하고 여러 head가 생기면 의미에 맞게 연결·병합한다. 운영에 적용된 revision을 덮어쓰지 않는다.
- 교차 기능이 의존하는 사용자 식별자, 정책 버전, 할 일 연결 등은 제공 기능의 Pydantic 스키마·서비스 계약과 함께 문서화한다. 프론트엔드는 OpenAPI를 기준으로 연동한다.

## 커밋

제목은 `<type>(<scope>): <설명>`이며 설명은 한국어로 작성한다.

예: `chore(setup): FastAPI 기반과 작업 하네스 구성`, `feat(auth): 이메일 로그인과 토큰 갱신 구현`.

커밋은 기능 코드와 그에 필요한 테스트·마이그레이션·문서를 함께 포함한다. 사용자 참고 PDF·이미지, `.env`, 실행 산출물을 섞지 않는다. 반복 절차는 [boso-commit](../.agents/skills/boso-commit/SKILL.md)을 따른다.

## PR

PR 제목은 커밋과 같은 형식을 사용하고 [.github/pull_request_template.md](../.github/pull_request_template.md)에 맞춰 실제 변경과 검증 결과를 적는다. 실행하지 않은 검증과 필요한 외부 설정을 명시한다.

CI 성공과 다른 팀원의 검토를 거쳐 병합하는 것을 팀 운영 기본값으로 한다. 원격 보호 규칙은 아직 설정하지 않았다. 병합 방식은 squash를 권장한다. 반복 절차는 [boso-pr](../.agents/skills/boso-pr/SKILL.md)을 따른다.
