---
name: boso-pr
description: Prepare, create, or update a BoSo pull request using its actual branch diff and verification evidence. Use for PR requests; drafting alone does not authorize pushing, publishing, requesting reviewers, or merging.
---

# BoSo PR

`AGENTS.md`, `docs/branch-strategy.md`, `.github/pull_request_template.md`를 읽는다. 요청이 본문 작성인지 실제 게시인지 구분하고 기존 사용자 허용 범위를 유지한다.

1. `git status --short`, `git branch --show-current`, `git remote -v`로 대상을 확인한다. 원격 refs를 읽어 base·head를 확인한다. 원격 설정이나 인증 정보를 임의로 바꾸지 않는다.
2. 초기 세팅은 `main`을 base로 한다. 이후에는 실제 존재하는 `develop`을 우선한다. 의존 브랜치 위의 PR이면 해당 브랜치를 base로 명시하고 의존 관계를 본문에 적는다. 존재하지 않는 base를 추정해 게시하지 않는다.
3. `git log <base>..HEAD --oneline`과 `git diff <base>...HEAD`를 읽는다. 변경 전의 문제와 변경 후 동작을 중심으로 제목·본문을 작성한다. 대화 이력, 이전에 포기한 설계, 무관한 작업은 넣지 않는다.
4. 관련 검증을 실행하고 실제 결과를 기록한다. 실행하지 않은 CI·Docker·Supabase 연결을 성공으로 표시하지 않는다. API·환경변수·마이그레이션 변경 및 배포 시 필요한 조치를 포함한다.
5. 게시 요청이 없으면 제목·base·head·본문 초안을 제공하고 끝낸다. 게시 요청이 있으면 `gh auth status` 또는 사용 가능한 GitHub 연결을 확인한다. 인증이 없으면 초안까지 완성하고 필요한 인증을 보고한다.
6. 원격 head가 없다면 push가 요청 범위에 포함되는지 확인하고, 허용된 경우에만 `git push -u origin <branch>`를 수행한다. 기존 PR을 먼저 확인해 중복 생성을 피한다.
7. 제목은 `<type>(<scope>): <설명>`, 본문은 한국어로 작성한다. `gh`에서는 임시 UTF-8 파일에 실제 줄바꿈을 보존하고 `--body-file`로 전달한다. 저장소 문서가 아닌 PR 임시 파일을 커밋에 넣지 않는다.
8. 기존 PR을 갱신할 때 이미지, 이슈 링크, 사용자가 적은 중요 내용을 보존한다. 게시 후 base·head·URL·상태를 확인해 보고한다.

게시 상태는 사용자가 지정한 값을 따른다. 지정이 없으면 draft로 생성한다. PR 생성 권한만으로 리뷰어 지정·리뷰 댓글 전송·merge까지 수행하지 않는다.

## 근거

- [GitHub PR 템플릿](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/creating-a-pull-request-template-for-your-repository)
- [GitHub CLI PR 생성](https://cli.github.com/manual/gh_pr_create)

base 선택, 한국어 본문, 기본 draft 상태는 BoSo 팀 규칙이다.
