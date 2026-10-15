---
name: boso-commit
description: Prepare and create a scoped BoSo Git commit when the user asks to commit or finish an authorized commit workflow. Inspect the actual diff, verify relevant changes, and preserve unrelated work.
---

# BoSo 커밋

루트 `AGENTS.md`와 `docs/branch-strategy.md`를 읽고 현재 요청에 맞는 커밋을 만든다. 커밋을 설명해 달라는 요청에는 Git 상태를 변경하지 않는다.

1. `git status --short`, `git branch --show-current`, `git diff`, `git diff --cached`로 브랜치와 변경을 확인한다. untracked 파일은 내용을 별도로 읽는다.
2. 기능 브랜치인지 확인한다. `main`·`develop`에서 작업 중이면 관련 기능 브랜치를 먼저 만든다. 사용자가 직접 지정한 대상이 있으면 그 지시를 따른다.
3. 요청한 범위의 변경만 골라 검토한다. 사용자 문서·이미지와 다른 작업은 보존한다. 기존 staged 변경도 사용자 소유일 수 있으므로 임의로 unstage하거나 함께 커밋하지 않는다.
4. 코드·설정 변경에는 `uv run python scripts/check.py`를 실행한다. 문서만 바뀌면 링크·명령·범위를 검토하고 `git diff --check`를 실행한다. DB 변경에는 PostgreSQL 검증도 포함한다. 실패를 고치거나 구체적인 미검증 사유를 남긴다.
5. 파일 경로를 명시해 `git add -- <paths>`로 stage한다. `git add .`를 기본으로 사용하지 않는다. `git diff --cached --stat`, `git diff --cached`, `git diff --cached --check`로 실제 포함 내용을 재확인한다.
6. `<type>(<scope>): <한국어 설명>` 제목으로 커밋한다. `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci` 중 실제 diff에 맞는 type을 고른다. 다른 type도 필요한 경우 Conventional Commits 문법 안에서 사용할 수 있다.
7. `git log -1 --oneline`, `git status --short`로 결과를 확인하고 브랜치·해시·검증 결과·남은 변경을 알린다. push나 PR 생성은 해당 권한이 주어진 경우에만 이어간다.

커밋 실패 시 훅을 건너뛰거나 사용자 Git 설정을 바꾸지 않는다. 인증·서명·작성자 설정이 필요한 경우 완료된 작업과 해결이 필요한 항목을 보고한다. 승인 없이 amend 또는 이력 재작성으로 해결하지 않는다.

## 근거

- [Git staging 문서](https://git-scm.com/docs/git-add)
- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)

제목의 한국어 설명, 기능별 브랜치, 명시적 경로 staging은 BoSo 팀 규칙이다.
