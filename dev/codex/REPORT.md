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
