# 실행 환경

글쓰기 규칙과 Python 검사기는 Claude Code와 Codex가 공유한다. 이 문서는 입력과 도구 사용의 차이만 다룬다.

## 입력과 경로

- Claude Code: `/techblog` 또는 `/techblog:techblog` 뒤의 인자가 `$ARGUMENTS`에 들어온다. 자연어 요청도 같은 규칙으로 읽는다.
- Codex: `$techblog`와 함께 보낸 사용자 요청에서 옵션과 자료를 읽는다. 플러그인에서는 스킬 선택기에 표시되는 techblog 스킬을 선택할 수도 있다. `$ARGUMENTS`는 Codex가 치환하는 변수가 아니다.
- 스킬 기준 경로는 **지금 읽은 `SKILL.md`가 있는 디렉터리**다. 모든 `references/`와 `scripts/` 경로는 그 디렉터리를 기준으로 해석한다. 사용자 자료와 출력의 상대 경로는 사용자의 작업 폴더 기준이다.
- Claude Code가 치환하는 `${CLAUDE_SKILL_DIR}`는 frontmatter의 Bash 사전 허용에 사용한다. Codex에서 이 변수를 만들거나 셸에 이미 있다고 가정하지 않는다. 명령과 subagent prompt에는 실제 절대 경로를 쓴다.

## 파일과 검사기

| 작업 | Claude Code | Codex |
|---|---|---|
| 파일 읽기·찾기 | Read, Glob, Grep | 제공된 파일 도구 또는 셸의 `cat`, `sed`, `rg` |
| 파일 생성·수정 | Write, Edit | 제공된 파일 편집 도구 또는 `apply_patch` |
| Python 검사기 | Bash | 제공된 셸 실행 도구 |
| URL 본문 | WebFetch | 웹 열기·가져오기 도구 또는 허용된 HTTP 다운로드 |
| 독립 후처리 | Agent의 general-purpose subagent | 사용 가능한 subagent 도구, 대화 상속 없이 실행 |

도구 이름을 흉내 내거나 없는 도구를 호출하지 않는다. macOS/Linux에서는 `python3`, Windows에서는 `python`을 사용한다. 사용할 수 있는 Python 3.8 이상 실행 파일이 따로 있으면 그 경로를 쓴다. 검사기는 외부 패키지가 필요 없다. 검사는 개별 명령으로 실행하고 경로를 인용한다. Claude의 `allowed-tools`는 Codex에 실행 권한을 부여하지 않으며 현재 환경의 권한 정책을 따른다.

## PDF와 URL

### Claude Code

- PDF는 Read의 `pages`를 사용하고 긴 문서는 20쪽 이하씩 나눠 마지막 쪽까지 읽는다.
- WebFetch에는 요약 없이 본문을 요청한다. 결과가 일부만 담겼으면 나머지 절을 이어 읽는다. PDF가 로컬 파일로 반환되면 그 파일을 Read로 읽는다.
- Claude의 Bash 사전 허용은 검사기에 한정된다. PDF 추출 명령을 반복해서 시도하지 않는다.

### Codex

- PDF를 읽는 기능이 제공되어 있으면 먼저 사용한다. 없다면 설치된 `pdftotext -layout`으로 본문을 추출해 끝까지 읽는다. 출력이 잘리면 구간을 나눠 읽는다.
- 표, 그림과 연결된 수치 및 추출 순서가 모호한 부분은 해당 페이지를 PDF 이미지 도구 또는 `pdftoppm`으로 렌더링해 확인한다. 텍스트 추출만으로 행·열의 대응을 추측하지 않는다.
- 웹 도구의 본문이 잘리면 해당 문서의 나머지 내용을 이어 읽는다. PDF URL은 PDF 열기 기능이나 허용된 다운로드로 읽는다. 검색 요약이나 초록은 본문을 대신하지 않는다.
- 추출물과 페이지 이미지는 이번 실행의 임시 폴더에 둔다. 원본 파일을 덮어쓰지 않는다. 필요한 도구가 없거나 본문에 접근하지 못하면 읽지 못한 범위를 알리고 읽을 수 있는 원문을 요청한다. 패키지를 자동 설치하거나 불완전한 자료로 완성본이라고 보고하지 않는다.

## 후처리 context

- 독립 subagent가 지원되면 초안 작성 대화를 상속하지 않게 실행한다. `fork_context`나 `fork_turns` 같은 설정이 있으면 상속을 끈다. 별도 모델은 지정하지 않는다.
- subagent에는 SKILL.md 6단계의 prompt와 실제 파일 경로만 넘긴다. 붙여넣은 자료는 fact sheet의 별도 `원문` 절에 그대로 보관하고 그 절을 자료 위치로 지정한다. subagent도 원문을 다시 확인할 수 있어야 한다.
- 독립 실행 도구가 없으면 현재 agent가 revision.md 순서를 따라 직접 후처리한다. 이 경우 독립 검토를 했다고 보고하지 않는다. 후처리를 위해 별도 CLI 설치나 인증을 시도하지 않는다.
