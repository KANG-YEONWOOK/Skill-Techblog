# Codex 실사용 검증

`smoke.py`는 실제 `codex exec`를 실행한다. 로그인된 계정의 사용량이 소비되므로 단위 테스트와 별도로 실행한다. Python 표준 라이브러리만 사용하며 Codex CLI와 로그인이 필요하다.

각 실행은 새로운 `--work` 폴더에 Codex 설정·플러그인 캐시·작업 폴더를 만든다. 직접 설치는 프로젝트의 `.agents/skills/techblog`에 복사하고, 플러그인 설치는 배포 파일을 별도 폴더에 복사한 뒤 CLI로 마켓플레이스 등록과 설치를 수행한다. 기존 사용자의 설정을 불러오지 않는다. 기존 로그인 파일이 있으면 내용 복사 없이 심볼릭 링크로 참조하고 종료 시 링크를 제거한다. 원본 입력은 실행 전후 SHA-256으로 대조한다.

```bash
python3 dev/codex/smoke.py --installation direct --case default --work /tmp/techblog-direct-default
python3 dev/codex/smoke.py --installation plugin --case casual --work /tmp/techblog-plugin-casual
python3 dev/codex/smoke.py --installation direct --case retone-casual --work /tmp/techblog-retone-casual
python3 dev/codex/smoke.py --installation plugin --case retone-default --work /tmp/techblog-retone-default
python3 dev/codex/smoke.py --installation direct --case cleanup --work /tmp/techblog-cleanup
python3 dev/codex/smoke.py --installation plugin --case url --work /tmp/techblog-url
python3 dev/codex/smoke.py --installation direct --case pdf --source /absolute/path/paper.pdf --work /tmp/techblog-pdf
python3 dev/codex/smoke.py --installation plugin --case default --direct-revision --work /tmp/techblog-direct-revision
```

`--work`는 존재하지 않는 경로여야 한다. 재시험할 때는 새 경로를 사용한다. 기본 timeout은 1,800초이며 `--timeout`으로 바꿀 수 있다. 모델은 지정하지 않고 Codex 기본 모델을 사용한다. `--source`로 URL이나 어투 변환 원문을 바꿀 수도 있다. `--direct-revision`은 입력 요청에 subagent를 사용하지 말고 직접 후처리하라는 지시를 추가한다. 도구가 없는 환경을 에뮬레이션하는 옵션은 아니다.

Default와 Casual은 기존 `evals/note-default`의 engineering note를 각각 파일·붙여넣기로 제공한다. 두 어투 변환은 저장소의 PagedAttention 예시를 사용한다. URL 기본 자료는 PEP 659다. PDF는 사용자가 지정한 로컬 자료를 복사한다.

## 결과 읽기

- `marketplace.jsonl`, `install.jsonl`: 플러그인 등록·설치 결과.
- `prompt.txt`, `run.jsonl`, `run.err`, `meta.json`: 입력, Codex 도구 실행 로그, stderr, 버전과 종료 코드.
- `작업 폴더/`: 결과 글과 `--keep-work` 작업 파일. 경로에 공백·한글을 포함한다.
- `eval.json`: 별도 프로세스의 lint 결과, 어투 검사, 후처리 전후 비교, 검사기 호출과 원문 보존 여부.

프로세스 종료 코드 0만으로 합격으로 보지 않는다. 새 글은 Gate/FAIL 0, 원문 보존, 작업 파일 보존·정리 규칙을 만족해야 하고 어투 변환은 tone_check의 FAIL이 없어야 실행기가 성공한다. 어투 변환 입력에 이미 있던 어투 외 문체 문제는 별도로 기록한다. 후처리의 AI 문체 악화 여부, 실제 스킬 로드 경로, subagent 실행 또는 직접 후처리 보고, 사실 충실성은 로그와 원문을 함께 검토한다. Python 부재 등 수동 점검 경로는 자동 검사 통과로 기록하지 않는다.

## 정적 검사와 회귀 검사

```bash
python3 -m unittest discover tests
claude plugin validate .
claude plugin validate .claude-plugin/plugin.json
```

Codex의 skill-creator `quick_validate.py`와 plugin-creator `validate_plugin.py`로도 검증한다. 이 개발용 검증기는 PyYAML이 필요하지만 배포되는 검사 스크립트의 의존성은 아니다.

실행 결과는 [검증 기록](REPORT.md)에 남긴다. 원본 로그와 생성된 글은 임시 폴더에 유지하고 저장소에 추가하지 않는다.
