---
name: techblog
description: 전달받은 자료(논문 PDF, 문서 PDF, 마크다운, URL, 붙여넣은 텍스트)를 한국어 기술 블로그 글로 정리하거나 기존 글의 어투를 바꾼다. 토스, 카카오, 당근 기술 블로그 문체를 참고하고 사실 대조와 검사 스크립트로 AI 문체 패턴을 줄인다. Default(합니다체)와 Casual(해요체)을 지원하며 어투만 바꿀 때 내용은 보존한다. "$techblog", "/techblog", "기술 블로그 글로 정리해줘", "아티클로 써줘", "블로그 포스트로 요약해줘" 같은 요청에 쓴다.
license: MIT
allowed-tools: Read Write Edit Glob Grep WebFetch Agent Bash(python "${CLAUDE_SKILL_DIR}/scripts/*) Bash(python ${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/*) Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*)
metadata:
  version: "0.5.1"
  repository: https://github.com/KANG-YEONWOOK/Skill-Techblog
---

# techblog

이 스킬은 자료를 읽고 그 핵심을 한국어 기술 블로그 아티클로 쓴다. 글의 독자는 자료의 분야를 아는 개발자이고, 글은 토스, 카카오, 당근 기술 블로그에 실린 글처럼 읽혀야 한다. 글의 모든 문장은 따로 읽어도 무엇에 대한 말인지 알 수 있어야 한다.

글은 초안과 후처리로 나눠 쓴다. 1~5단계에서는 모든 글에 같은 규칙으로 초안을 쓰고 점검한다. 6단계(후처리)에서는 초안을 이 글의 독자 입장에서 다시 읽고 이 글에 맞게 고친다.

Claude Code와 Codex에서 사용한다. 먼저 [실행 환경 안내](references/runtime.md)를 읽고 현재 환경의 입력, 도구, 스킬 경로를 확인한다. 검사 스크립트는 Python 3.8 이상이며 외부 패키지가 필요 없다.

Claude Code 호출 인자: $ARGUMENTS

Codex에서는 `$techblog`와 함께 보낸 사용자 요청을 입력으로 삼는다. `$ARGUMENTS`가 치환되지 않았거나 자연어로 호출했다면 현재 사용자 요청에서 자료와 옵션을 읽는다.

## 인자 해석

- 입력에 `casual`, `Casual`, `해요체`가 있으면 Casual 글을 쓴다. `default`, `Default`, `합니다체`가 있거나 어투를 지정하지 않았으면 Default 글을 쓴다.
- `-o <경로>`는 글을 저장할 파일 경로다. 이 인자가 없으면 현재 작업 디렉터리에 글 주제를 나타내는 영문 kebab-case 이름(예: `cache-invalidation-latency.md`)으로 저장한다.
- `--retone`이 있으면 입력 파일을 완성된 아티클로 보고 7단계(어투 적용)만 한다. 6단계(후처리)는 하지 않는다. `--retone` 없이 이미 쓴 글의 어투만 바꿔 달라고 요청해도 `--retone`으로 본다. 출력 경로가 없으면 `<입력 이름>.<casual|default>.md`에 저장한다.
- `--keep-work`가 있으면 작업 파일을 지우지 않는다.
- 나머지 입력은 자료(파일 경로, URL)와 추가 지시(독자, 분량, 강조할 부분)다. 입력에 자료가 없으면 대화에 붙여넣은 텍스트를 자료로 쓴다. 붙여넣은 텍스트도 없으면 무엇을 정리할지 사용자에게 묻는다.

## 파일

- 글은 `<이름>.md`에 저장한다.
- 작업 파일은 출력 파일과 같은 폴더에 만든다. fact sheet는 `<이름>.facts.md`이고, Casual 글을 쓸 때만 만드는 Default 초안은 `<이름>.draft.md`다. 6단계를 시작할 때 스크립트가 후처리 전 초안을 `<이름>.unrevised.md`에 복사하고 반복 후보를 `<이름>.repeats.md`에 적는다. 작업 파일은 8단계에서 지운다.
- 후처리 대상은 합니다체 글이다. Default 글이면 출력 파일 `<이름>.md`, Casual 글이면 Default 초안 `<이름>.draft.md`다.

## 작업 순서와 필수 문서

아래 문서는 각 단계의 실행 지침이다. 해당 단계에 들어가기 전에 지정한 문서를 끝까지 읽는다. 도구 출력이 잘리면 나머지를 나눠 읽는다. 모든 `references/`와 `scripts/`는 이 `SKILL.md`가 있는 디렉터리 기준이다. 검사 명령과 실행 오류 처리도 [runtime.md](references/runtime.md)를 따른다.

### 새 글

1. [drafting.md](references/drafting.md)를 읽고 1~4단계를 수행한다. 자료 전체 읽기, fact sheet 작성, 개요, Default 초안 작성 순서다. Casual도 먼저 합니다체 초안을 쓴다. [style-guide.md](references/style-guide.md)는 3단계에서 읽고, AI 패턴 문서는 초안을 쓰기 전에 읽지 않는다.
2. [validation.md](references/validation.md)를 읽고 5단계를 수행한다. 문체 검사, 문장별 단독 읽기, fact sheet 대조, [rubric.md](references/rubric.md)의 J1~J9 점검을 한다. [ai-patterns.md](references/ai-patterns.md)는 이 단계에서 읽는다.
3. [finalization.md](references/finalization.md)를 읽고 6~8단계를 수행한다. [revision.md](references/revision.md)에 따른 독립 후처리(도구가 없으면 직접 수행), Casual 어투 적용, 작업 파일 정리와 결과 보고 순서다. 어투를 적용할 때 [tone.md](references/tone.md)를 읽는다.

### 완성된 글의 어투만 변환

`--retone` 또는 같은 뜻의 요청이면 [finalization.md](references/finalization.md)의 7~8단계와 [tone.md](references/tone.md)를 따른다. 1~6단계는 수행하지 않는다. 입력은 수정·삭제하지 않고 fact sheet와 후처리 파일을 만들지 않는다. 원문의 어투 외 lint 문제는 보고만 한다.
