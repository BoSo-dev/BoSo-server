# 브랜치·커밋·PR 운영

## 브랜치

하나의 브랜치에는 하나의 기능 또는 검토 가능한 공통 세팅을 담는다.

| 브랜치 | 용도 |
| --- | --- |
| `main` | 검토를 거친 기준·배포 버전 |
| `develop` | 팀이 생성한 이후 사용할 통합 브랜치 |
| `chore/project-setup` | 최초 프로젝트 세팅·작업 하네스 |
| `feat/supabase-db` | Supabase 연결·DB 운영 환경 |
| `feat/auth` | 회원 기능 |
| `feat/policy-data` | 정책 데이터 모델·파일 관리 |
| `feat/policy-api` | 정책 목록·상세 조회 |
| `fix/<내용>` | 기존 기능 오류 수정 |

초기 원격에는 `main`만 있으므로 세팅 PR은 `main`을 대상으로 준비한다. `develop`은 생성·사용이 확정되면 실제 ref를 확인해 기준으로 삼는다. 세팅 작업 자체가 브랜치 보호 변경이나 원격 merge를 포함하지는 않는다.

기능 브랜치는 세팅이 통합된 기준에서 만든다. 선행 PR 병합 전 구현이 필요하면 해당 선행 브랜치에서 분기하고, PR base·의존 관계를 명시한다. 무관한 기능들을 `feat/backend-mvp` 하나에 모으지 않는다.

## 커밋

제목은 `<type>(<scope>): <설명>`이며 설명은 한국어로 작성한다.

예: `chore(setup): FastAPI 기반과 작업 하네스 구성`, `feat(auth): 이메일 로그인과 토큰 갱신 구현`.

커밋은 기능 코드와 그에 필요한 테스트·마이그레이션·문서를 함께 포함한다. 사용자 참고 PDF·이미지, `.env`, 실행 산출물을 섞지 않는다. 반복 절차는 [boso-commit](../.agents/skills/boso-commit/SKILL.md)을 따른다.

## PR

PR 제목은 커밋과 같은 형식을 사용하고 [.github/pull_request_template.md](../.github/pull_request_template.md)에 맞춰 실제 변경과 검증 결과를 적는다. 실행하지 않은 검증과 필요한 외부 설정을 명시한다.

CI 성공과 다른 팀원의 검토를 거쳐 병합하는 것을 팀 운영 기본값으로 한다. 원격 보호 규칙은 아직 설정하지 않았다. 병합 방식은 squash를 권장한다. 반복 절차는 [boso-pr](../.agents/skills/boso-pr/SKILL.md)을 따른다.
