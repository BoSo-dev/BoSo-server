# 작업 하네스

## 구성과 근거

OpenAI 공식 문서의 저장소 지침과 스킬 구조를 참고해 BoSo에서 실제 사용할 작업 흐름을 구성했다. 아래 파일명·검색 위치는 공식 문서에 근거하고, 한국어 제목·브랜치명·검증 명령·draft PR 기본값은 이 저장소가 정한 규칙이다.

| 구성 | 역할 |
| --- | --- |
| `AGENTS.md` | 팀 공통 실행·검증, 코드·DB·보안 기준, 스킬 연결 |
| `docs/architecture.md` | 전체 도메인의 경계와 코드·API 연결 방식 |
| `docs/implementation-plan.md` | 팀 전체 구현 단계·의존 관계·완료 기준 |
| `docs/workstreams/` | 개별 담당 작업의 맥락·범위·진행 계획 |
| `.agents/skills/boso-commit/SKILL.md` | diff 검토 → 범위별 staging → 검증 → 커밋 |
| `.agents/skills/boso-pr/SKILL.md` | base·head 확인 → diff 기반 본문 → 검증 → 허용된 게시 |
| `scripts/check.py` | 로컬·CI 공통 Ruff·pytest·공백 검사 |
| `.github/workflows/ci.yml` | Python 3.12·3.14, PostgreSQL, 마이그레이션, Docker 검증 |
| `.github/pull_request_template.md` | 실제 변경·검증·설정·남은 확인 사항 |

Codex는 `AGENTS.md`를 상위 디렉터리에서 작업 디렉터리 순으로 적용하며, 더 가까운 디렉터리의 지침이 해당 범위를 구체화한다. 현재 저장소에는 공통 지침 하나만 두었다.

개별 작업 문서는 그 작업을 수행할 때 참고한다. 개인이 이번에 구현하지 않는 기능을 루트 지침에서 금지하거나, 개인의 구현 방식을 팀 전체 제약으로 적용하지 않는다. 하위 `AGENTS.md`가 필요해지면 해당 코드의 기술 규칙만 구체화한다.

스킬은 이름·설명으로 발견되고 선택 시 본문을 읽는 방식이다. 저장소의 `.agents/skills/`에 넣어 팀과 함께 버전 관리한다. 현재 세션에서는 루트 지침의 경로로 직접 읽어 사용할 수 있고, 새 세션에서는 발견 목록을 확인한다.

## 사용 예

```text
$boso-commit 회원 기능 변경을 검증하고 커밋해줘.
$boso-pr 현재 브랜치의 PR 제목과 본문을 작성해줘.
$boso-pr 현재 브랜치를 push하고 draft PR을 만들어줘.
```

첫 번째 요청은 로컬 커밋, 두 번째는 초안 작성, 세 번째는 원격 게시까지 포함한다. 원격 인증이 없더라도 가능한 검증과 초안 작성은 먼저 완료한다. 전역 설정 변경이나 추가 승인 절차를 하네스가 요구하지는 않는다.

## 검증과 한계

```powershell
uv sync --locked --extra dev
uv run python scripts/check.py
```

스킬을 수정하면 YAML frontmatter의 `name`·`description`, 상대 링크, 실제 명령, 허용 범위를 확인한다. 스킬 생성 환경에 OpenAI `skill-creator`가 설치되어 있다면 해당 `scripts/quick_validate.py`로 스키마도 검사할 수 있다. 이 도구는 프로젝트 런타임이나 CI의 필수 의존성이 아니다.

현재 CI는 구성을 제공한 상태이며 원격 실행 여부는 PR·Actions 결과로 별도 확인한다. Docker·실제 Supabase 연결 검증은 해당 실행 환경과 자격 증명이 있어야 한다. 로컬 검사 통과를 외부 검증 성공으로 바꾸어 보고하지 않는다.

## 공식 참고 문서

- [OpenAI: AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [OpenAI: Build skills](https://learn.chatgpt.com/docs/build-skills)
- [OpenAI: 저장소 스킬·지침·CI 운영 사례](https://developers.openai.com/blog/skills-agents-sdk)
- [Git: staging](https://git-scm.com/docs/git-add)
- [Conventional Commits 명세](https://www.conventionalcommits.org/en/v1.0.0/)
- [GitHub: PR 템플릿](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/creating-a-pull-request-template-for-your-repository)
- [GitHub CLI: PR 생성](https://cli.github.com/manual/gh_pr_create)
- [uv: GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/)
