# 0.5.1 스킬 본문 잘림 수정 — 2026-10-11

Windows에서 Codex CLI 0.162.1, Claude Code 2.1.296, Python 3.12.3으로 검증했다. CLI 실행에는 모델이나 추론 수준을 지정하지 않았다. 아래 문체 검사의 WARN은 스킬 로딩 경고와 다른 진단이다.

## 원인과 재현

Codex 0.162.1의 [render.rs](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/ext/skills/src/render.rs#L21)는 `MAX_SKILL_PROMPT_BYTES = 8_000`을 정의한다. [host_prompt.rs](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/ext/skills/src/host_prompt.rs#L76)는 플러그인 스킬을 주입할 때 이 제한을 적용하고 초과하면 `Skill ... exceeded the main prompt context limit and was truncated.` 경고를 출력한다. UTF-8 문자 경계를 지키면서 앞부분만 남긴다. 파일을 통째로 읽은 뒤 제한하므로 frontmatter도 바이트 수에 포함된다.

기존 `SKILL.md`는 24,394바이트였다. 8,000바이트를 남기면 83번째 줄의 4단계 지침 중간에서 끊기고 5~8단계는 주입되지 않는다. 설치 캐시와 저장소 파일의 SHA-256도 같았다. 이 제한은 스킬 목록의 description 예산과 별개인 상수이므로 description만 줄이거나 모델 컨텍스트 설정을 늘리는 것으로 해결되지 않는다. Claude Code와 Codex가 같은 파일을 사용해도 호스트의 로딩 처리는 다르다.

같은 Codex 0.162.1에서 설치 경로를 포함한 명시적 스킬 링크로 로딩만 요청했다. 글쓰기와 도구 실행은 요청하지 않았다.

| 주입한 파일 | UTF-8 바이트 | 프로세스 종료 | 실제 런타임 결과 |
|---|---:|---:|---|
| `5895109`의 0.5.0 원본 | 24,394 | 0 | 보고된 잘림 경고 재현 |
| 0.5.1 수정본 | 5,455 | 0 | 잘림·로드 실패 경고 없음 |

Codex는 이 경고를 JSONL의 `item.completed` / `error`로 내보내면서도 종료 코드 0을 반환했다. 기존 실행기는 `$techblog` 텍스트만 사용했고 이 진단을 실패 조건으로 검사하지 않았다. 따라서 이전 보고서의 성공은 명시 주입 시 경고가 없다는 증거가 아니었다. [0.155.1 구현](https://github.com/openai/codex/blob/rust-v0.155.1/codex-rs/ext/skills/src/render.rs#L19)에도 같은 8,000바이트 제한이 있다.

## 보존한 동작과 수정 범위

- Claude Code와 Codex의 공통 진입점을 유지했다. 1~4단계는 `drafting.md`, 5단계는 `validation.md`, 6~8단계는 `finalization.md`로 옮겼다. 원본의 여덟 단계 각각을 대조해 문구가 그대로 남아 있음을 확인했다.
- 스크립트 명령 블록은 `runtime.md`로 그대로 옮겼다. Windows 문서 읽기에 UTF-8을 명시했고, 이전 단계 위치를 가리키던 runtime·rubric·dogfood 참조를 수정했다.
- Default/Casual, 양방향 retone, 작업 파일 이름과 정리, 독립 후처리와 직접 수행 경로를 유지했다. `lint_ko.py`, `revise_ko.py`, `tone_check.py`, 패턴·기준치 파일은 변경하지 않았다.
- 진입점 전체가 LF와 CRLF 모두 6,000바이트 이내인지 검사한다. 실제 설치 폴더만 복사해 내부 Markdown 링크와 검사기 실행을 확인한다.
- 실행기는 설치된 파일 경로를 포함한 명시 호출을 사용하고 경고를 실패 처리한다. UTF-8 subprocess 입출력과 PowerShell 명령 해석도 검증한다. 스킬과 세 plugin manifest의 버전은 0.5.1로 일치시켰다.

## 자동 검사와 실사용

단위·회귀 테스트 73개, Codex `quick_validate.py`, Claude marketplace와 plugin manifest 검사를 통과했다. Windows 기본 Python 실행에서도 통과한다. 수정 전에는 UTF-8 출력에 cp949를 적용하는 설치 경로 테스트 1개가 실패했다.

실사용 테스트는 새 프로필과 작업 폴더에 패키지를 복사하고 `--no-daemon --sandbox workspace-write`로 실행했다. Windows MXC를 명시해 같은 작업 폴더 쓰기 권한을 유지했다. 사용자 설정을 복사하거나 변경하지 않았고, 로그인 파일은 내용 복사 없이 링크로 참조한 뒤 제거했다. 이 호스트는 symlink 권한이 없어 같은 볼륨의 hard link를 사용했다.

| Codex 설치·동작 | 초 | 최종 Gate/FAIL/WARN | 확인 |
|---|---:|---|---|
| 플러그인: 노트 → Default | 171.8 | 0/0/0 | 원문과 작업 파일 보존, 후처리 검사 |
| 플러그인: 붙여넣은 노트 → Casual | 179.1 | 0/0/0 | Default 초안과 tone_check 통과 |
| 직접: Default → Casual retone | 76.0 | 0/0/0 | 원문·내용·구조 보존 |
| 플러그인: Casual → Default retone | 102.5 | 0/0/0 | 161문장 대응, 원문 보존 |
| 플러그인: Default → Casual retone | 113.4 | 0/0/1 | 161문장 대응, 어투 외 WARN은 보존 규칙에 따라 보고 |
| 직접: 노트 → Default, 기본 정리 | 160.0 | 0/0/1 | 작업 파일 제거, 입력과 결과 보존 |
| 플러그인: PEP 659 URL → Default | 240.6 | 0/0/1 | 웹 본문 읽기, 후처리 검사 |
| 플러그인: 노트 → Default, 직접 후처리 | 131.8 | 0/0/0 | 협업 호출 없이 revision.md 읽기와 검사 |
| 직접: PagedAttention PDF → Default | 643.3 | 0/0/0 | 16페이지 텍스트와 주요 페이지 이미지 확인, 후처리 검사 |

완료된 Codex 케이스는 모두 스킬 잘림·로드 실패 경고가 없었다. 생성 글에 검사기를 별도로 다시 실행했고, 원문 해시, 작업 파일 규칙, 실제 검사 명령 실행을 확인했다. 후처리 사본이 남은 케이스는 `must_fix = false`였고 어투 변환의 FAIL도 없었다. 명령 로그에서 새 참조 문서 읽기를 확인했다. retone은 fact sheet와 후처리 파일을 만들지 않았다.

PDF 실행은 이 호스트에 Poppler가 없어 설치된 `pypdf`로 전체 텍스트를 추출하고 Windows PDF API로 주요 페이지 9개를 렌더링했다. 최종 본문은 검사기 기준 7,122자였고 후처리 전후 수치·제목·코드 보존 검사를 통과했다.

| Claude Code 동작 | 초 | 최종 Gate/FAIL/WARN | 확인 |
|---|---:|---|---|
| 노트 → Default | 209.9 | 0/0/0 | 원문·작업 파일 보존, 후처리 검사 |
| Default → Casual retone | 120.8 | 0/0/0 | tone_check 통과, 원문 보존 |

Claude는 `--plugin-dir`로 수정본을 읽었고 사용자 설정·MCP·CLAUDE.md·auto memory는 실행 옵션으로 제외했다. 두 실행 모두 permission denial이 없었다. 첫 초안의 lint 오류는 실행 중 수정됐고, 마지막 결과를 별도 검사로 재확인했다.

추가로 초안 대화를 상속하지 않은 Codex agent에게 노트 → Default를 실행하게 했다. 지침에 따른 별도의 독립 후처리, 원문 보존, 초안·최종 Gate/FAIL/WARN 0과 후처리 검사 통과를 확인했다. 이 글은 1,443자로 리듬·밀도 항목의 자동 판정 대상보다 짧다는 제한도 보고했다.

## 관찰과 검증 범위

초기 Windows 실행은 OS 임시 폴더 아래의 helper 생성 제한과 준비되지 않은 프로필의 셸 실행 정책 때문에 글을 만들지 못했다. 이 실행을 성공으로 세지 않았다. OS 임시 디렉터리 밖의 새 폴더와 호스트에서 동작하는 MXC를 사용한 뒤 위 표의 검증을 완료했다. 사용자 권한 설정을 바꾸거나 샌드박스를 해제하지 않았다.

Codex 노트 결과에서 600요청/60초, 100토큰, 초당 10토큰, p99 1,850→420ms, 거절 비율 2.1→2.6%, Redis CPU +8%p 및 50,000 초과 미검증 조건을 대조했다. Claude Default에는 이전 0.5.0 검토에서도 관찰했던 “50,000개 이하 규모에서만 검증”이라는 일반화가 남았고, 충전 간격에 관한 파생 설명도 원문이 직접 밝힌 구현 세부와 구분해야 한다. 자동 검사 PASS가 모든 문장의 사실 충실성을 보장하지는 않는다. 이번 수정은 규칙의 로딩과 보존을 대상으로 하며 문체 알고리즘·품질 기준을 바꾸지 않았다.

이번 검증은 Windows 실행과 로컬 패키지 설치다. macOS/Linux 실사용, Codex 앱의 버튼 조작, Python이 없는 환경, GitHub에서 업데이트하는 전체 UI 흐름은 재실행하지 않았다. 기존 0.5.0 보고서는 아래에 그대로 남겼다.

원본 로그와 생성물은 `C:/Users/user/.codex/tmp/techblog-v051-20261011/`에 보관했다. `load-before`, `load-after`에는 경고 비교, 각 케이스 폴더에는 `meta.json`, `eval.json`, `run.jsonl`과 결과 파일이 있다. `preservation.json`에는 지침 이동 대조 결과가 있다. 초기 환경 실패 기록은 OS 임시 폴더의 `techblog-v051-20261010/`에 있다. 인증 내용·로그·생성 글은 저장소에 추가하지 않는다.

---

# 0.5.0 호환성 검증 — 2026-10-07

macOS에서 Codex CLI 0.155.1과 Claude Code 2.1.292를 실제 실행했다. Python은 3.9.6이다. Codex 모델은 CLI 기본값을 사용했고 별도 모델·추론 수준을 지정하지 않았다. Claude 실행 로그의 모델은 `claude-opus-5-5`였다.

## 설치와 자동 검사

- Python 단위·회귀 테스트 65개 통과. 설치 폴더만 복사한 뒤 다른 작업 폴더에서 검사기를 실행하는 테스트를 포함한다. 설치 경로와 작업 경로에 공백·한글을 넣고 Claude 경로 변수를 제거했다.
- Codex `quick_validate.py`와 `validate_plugin.py` 통과. 개발용 PyYAML은 `uv run --with pyyaml`의 격리된 환경에서만 사용했다.
- `claude plugin validate .`와 `claude plugin validate .claude-plugin/plugin.json` 통과.
- Codex 직접 설치는 프로젝트의 `.agents/skills/techblog`를 사용했다.
- Codex 플러그인은 별도 Codex 프로필에 로컬 마켓플레이스를 등록한 뒤 `codex plugin add techblog@skill-techblog`로 설치했다. CLI가 반환한 버전은 0.5.0이며 스킬은 설치 캐시에서 로드됐다.
- Claude는 `--plugin-dir`로 수정본을 로드했다. 기존 사용자 설정·MCP·CLAUDE.md·auto memory는 실행 옵션으로 제외했다.
- 개인 스킬 폴더와 기존 플러그인 설정은 바꾸지 않았다. GitHub에 아직 게시하지 않은 로컬 수정본이므로 원격 저장소 설치와 업데이트는 검증 범위에 포함하지 않는다.

## Codex 실행 결과

아래 판정은 프로세스 성공뿐 아니라 결과 파일, 실제 Python 검사기 호출, 자동 재검사와 원문 보존을 확인한 결과다. G/F/W는 최종 글의 Gate/FAIL/WARN 수다.

| 설치 | 입력·동작 | 초 | G/F/W | 확인 |
|---|---|---:|---|---|
| 직접 | 노트 파일 → Default | 144.9 | 0/0/1 | 후처리 2문장, 작업 파일 보존 |
| 플러그인 | 붙여넣은 노트 → Casual | 145.2 | 0/0/0 | Default 초안과 최종 28문장 대응, tone_check PASS |
| 직접 | Default → Casual retone | 44.3 | 0/0/0 | 161문장 대응, 원문·구조·수치 보존 |
| 플러그인 | Casual → Default retone | 47.0 | 0/0/0 | 161문장 대응, 원문·구조·수치 보존 |
| 직접 | 노트 파일 → Default, 기본 정리 | 158.8 | 0/0/1 | 검사 후 작업 파일 제거, 입력과 최종 글 보존 |
| 플러그인 | PEP 659 URL → Default | 255.8 | 0/0/1 | 웹 본문 읽기, 후처리 1문장, 검사 PASS |
| 직접 | PagedAttention 로컬 PDF → Default | 359.6 | 0/0/0 | 본문 추출, 표·그래프 페이지 렌더링, 검사 PASS |
| 플러그인 | 최종 지침으로 노트 → Default | 130.8 | 0/0/0 | 원문 보존, 문체·후처리 검사 PASS |
| 플러그인 | 노트 → Default, 직접 후처리 요청 | 94.9 | 0/0/0 | 위임 없이 후처리·검사 완료, 원문 보존 |

검사기는 `.agents/skills` 또는 `plugins/cache/skill-techblog/techblog/0.5.0`의 실제 설치 경로에서 실행됐다. `${CLAUDE_SKILL_DIR}`가 없는 환경에서도 문체·후처리·어투·정리 명령이 동작했다. 후처리 사본이 남은 모든 사례에서 `worse_ai`는 빈 목록이고 `must_fix`는 false였다. WARN이 남은 글은 적용 조건을 설명하는 추정·당위 표현 또는 긴 문장 분포에 관한 이유를 보고했다.

## 원문 대조와 수정 사항

노트의 600요청/60초, bucket 100토큰, 충전 10토큰/초, p99 1,850→420ms, 거절 비율 2.1→2.6%, Redis CPU +8%p를 결과와 대조했다. Codex 두 어투의 글은 원문의 설정과 한계를 유지했다. Casual의 내용 보존은 별도 실행의 Default 글과 비교하지 않고 **같은 실행의 Default 초안과** 비교했다.

URL 결과는 [PEP 659](https://peps.python.org/pep-0659/)의 명령군, 채택·폐기된 캐시 설계, 성능 추정과 메모리 표를 대조했다. PDF 결과는 [PagedAttention 논문](https://arxiv.org/abs/2309.06180)의 처리량 비교 조건과 주요 표·그래프를 확인했다. Codex는 `pdftotext -layout` 결과를 구간별로 끝까지 읽고 `pdftoppm`으로 주요 페이지를 렌더링했다. 숫자가 일치하는 것과 모든 문장이 사실에 충실한 것은 별개이므로 자동 검사만으로 사실 정확성을 보장하지 않는다.

Claude Default의 수동 검토에서는 “50,000 초과 미검증”을 “50,000 이하에서만 확인”으로 요약한 표현이 있었다. 원문은 실제 시험한 클라이언트 수를 밝히지 않는다. 이를 50,000 이하의 모든 규모를 검증했다는 뜻으로 읽히게 만들지 않았는지 별도로 검토해야 한다. 범위 점검 설명을 추가한 재시험에도 비슷한 표현이 남아, 글쓰기 기준은 기존대로 유지하고 이 관찰을 자동 검사와 분리해 기록했다.

첫 Claude 두 실행은 문서·목록을 셸로 읽으려다가 각각 2회·1회 거부된 뒤 Read로 복구했다. 기존 Claude의 Read·Glob 사용 지침을 공통 진입점에 다시 명시했다. 재시험의 Casual 변환은 권한 거부 없이 완료됐고, Default에서는 subagent의 검사 실행이 한 번 거부되어 상위 agent가 직접 검사했다. 이는 6단계에서 상위 agent가 최종 확인하도록 한 경로로 처리됐다.

역방향 retone 점검에서는 기존 지침이 항상 `--tone casual`을 쓰도록 되어 있던 부분을 목표 어투로 고쳤다. Retone 원문을 수정·삭제하지 않고 어투 외 기존 lint 문제는 보고만 하도록 명확히 했다. 양방향 변환은 tone_check와 원문 SHA-256 비교를 통과했다.

## Claude 회귀 재시험

| 동작 | 초 | G/F/W | 확인 |
|---|---:|---|---|
| 노트 파일 → Default | 161.0 | 0/0/0 | 원문 보존, 독립 후처리 후 상위 agent의 검사 완료 |
| Default → Casual retone | 118.4 | 0/0/0 | 161문장 대응, tone_check PASS, 원문 보존 |

두 결과 모두 검사기를 별도로 다시 실행했다. 후처리의 AI 문체 악화는 없었고 어투 변환의 FAIL도 없었다. 범위 표현의 수동 검토 사항은 위 절에 별도로 기록했다. 초기 비교 실행 2건을 포함해 Claude는 총 4회 실행했다.

## 재현과 범위

실행 명령은 [실행기 안내](README.md)에 있다. 이번 산출물과 JSONL 로그는 로컬 `/tmp/techblog-v050/` 아래의 케이스별 폴더에 남겼다. 각 폴더의 `meta.json`, `eval.json`, `run.jsonl`과 `작업 폴더/`를 함께 확인한다. 초기 Claude 비교 실행은 `claude-default`, `claude-retone`, 재시험은 `claude-default-final`, `claude-retone-final`이다. 원본 로그와 생성 글은 저장소에 커밋하지 않는다.

추가 Codex 실행 `plugin-fallback-final`은 `--disable multi_agent`를 적용했어도 독립 후처리 보고가 나와 도구 부재 경로의 검증으로 세지 않았다. 위 표에는 일반 Default 실행으로 기록했다. 실행기의 직접 후처리 옵션은 기능 플래그 대신 사용자 요청으로 그 절차를 선택하게 한다. 이 옵션을 적용한 `plugin-direct-revision`은 직접 후처리를 보고했고 협업 도구 호출 없이 검사까지 통과했다. Codex 실행은 총 9회다.

Windows/Linux 실사용, Codex 앱의 버튼 조작, Python이 없는 환경의 수동 문체 검사는 실행하지 않았다. 검사 스크립트의 Python 3.8 이상·외부 패키지 없음 조건은 유지했다. 이전 버전의 대규모 Claude 품질 평가는 이 Codex 호환성 검사와 다른 실험이다.
