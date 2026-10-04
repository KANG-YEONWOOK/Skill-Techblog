# techblog

자료(논문·문서 PDF, 마크다운, URL, 붙여넣은 텍스트)를 읽고 그 핵심을 한국어 기술 블로그 아티클로 정리하는 Claude Code skill입니다. 글은 토스·카카오·당근 기술 블로그에 실린 글처럼 읽히는 것을 목표로 하고, AI 글에서 자주 보이는 문체 패턴은 근거 기반 rubric과 검사 스크립트로 걸러 냅니다.

- 어투는 **Default**(합니다체)와 **Casual**(토스식 해요체) 중에서 고릅니다. 어투만 바뀌고 내용은 같습니다.
- 자료에 있는 사실만 씁니다. 본문의 수치는 fact sheet와 자동 대조하고, 겪지 않은 경험이나 근거 없는 수치는 쓰지 않습니다.
- 평가 기준은 연구 자료(한국어 실측 연구 포함)와 토스·카카오·당근 사람 글 측정값으로 정했습니다.

## 설치

### Plugin marketplace로 설치

Claude Code 세션에서:

```
/plugin marketplace add KANG-YEONWOOK/Skill-Techblog
/plugin install techblog@skill-techblog
```

shell에서:

```bash
claude plugin marketplace add KANG-YEONWOOK/Skill-Techblog
claude plugin install techblog@skill-techblog
```

`/techblog`로 호출합니다. 같은 이름의 다른 명령이 있으면 `/techblog:techblog`로 호출합니다. 업데이트는 `/plugin marketplace update skill-techblog`으로 받습니다.

### 직접 복사

`skills/techblog` 폴더를 개인 skill 폴더(`~/.claude/skills/`)에 복사합니다.

macOS, Linux:

```bash
git clone https://github.com/KANG-YEONWOOK/Skill-Techblog.git
mkdir -p ~/.claude/skills
cp -r Skill-Techblog/skills/techblog ~/.claude/skills/
```

Windows PowerShell:

```powershell
git clone https://github.com/KANG-YEONWOOK/Skill-Techblog.git
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse Skill-Techblog\skills\techblog "$HOME\.claude\skills\techblog"
```

### 요구 사항

- Claude Code
- Python 3.8 이상(선택): 검사 스크립트(`lint_ko.py`, `tone_check.py`)를 실행합니다. 없으면 같은 기준으로 수동 점검합니다. 외부 패키지는 쓰지 않습니다.

## 사용법

```
/techblog paper.pdf
/techblog casual https://arxiv.org/pdf/2309.06180 -o paged-attention.md
/techblog default design-doc.md 독자는 백엔드 개발자, 분량은 5,000자 안팎
/techblog casual --retone paged-attention.md
```

| 인자 | 설명 |
|---|---|
| `default`, `casual` | 어투. 생략하면 Default(합니다체). `합니다체`, `해요체`로 써도 됩니다. |
| 자료 | 파일 경로(PDF, 마크다운, 텍스트), URL. 생략하면 대화에 붙여넣은 텍스트를 씁니다. |
| `-o <경로>` | 출력 파일. 생략하면 현재 폴더에 영문 kebab-case 이름으로 저장합니다. |
| `--retone` | 이미 쓴 글의 어투만 바꿉니다. 문장 순서, 수치, 고유명사는 그대로 둡니다. |
| `--keep-work` | 작업 파일(`<이름>.facts.md`, `<이름>.draft.md`)을 지우지 않습니다. |
| 추가 지시 | 독자, 분량, 강조할 부분 등 |

## 동작 방식

1. 자료를 끝까지 읽습니다(PDF는 20쪽 단위, URL은 본문 전체).
2. fact sheet를 만듭니다. 본문의 수치와 주장은 이 파일에서만 가져옵니다.
3. `references/style-guide.md`를 보고 개요를 잡습니다.
4. Default(합니다체) 초안을 씁니다. Casual로 요청해도 먼저 합니다체로 씁니다.
5. `scripts/lint_ko.py`로 rubric의 자동 측정 항목을 검사하고, 기준을 넘은 문장만 고칩니다. 고칠 때는 지워도 정보가 줄지 않는 문장을 지우거나(deletion test) 그 정보를 직접 쓰는 문장으로 바꿉니다.
6. Casual이면 초안의 문장마다 종결부만 바꾸고 `scripts/tone_check.py`로 확인합니다.
7. 작업 파일을 지우고 결과를 짧게 보고합니다.

피할 표현 목록은 초안을 쓴 뒤에만 봅니다. 금지어 목록을 지시문으로 주면 효과가 제한적이고 역효과가 날 수 있다는 연구 결과(Antislop, 2025)를 따른 순서입니다.

## 어투

- Default: 카카오 기술 블로그처럼 합니다체로 씁니다. 섹션을 여는 "~할까요?" 질문은 허용합니다.
- Casual: 토스의 순수 해요체 글과 당근 글처럼 정중한 해요체로 씁니다. 토스 글 22편 중 순수 해요체는 6편이고 나머지는 합니다체이거나 문장 단위로 섞어 쓰는데, 이 스킬은 Casual을 순수 해요체로 정했습니다.
- 내용은 Default 초안에서 정하고 Casual은 종결부만 바꾸므로 한 번의 실행 안에서 두 어투의 내용은 같습니다. `--retone`으로 기존 글을 바꿀 때도 같습니다. 별도로 두 번 실행하면 모델 sampling 때문에 내용이 달라질 수 있습니다.

## 평가 기준

[`skills/techblog/references/rubric.md`](skills/techblog/references/rubric.md)에 있습니다.

- Gate: 자료에 없는 사실, 겪지 않은 경험, 챗봇 응답 흔적, 어투 혼용, 접속부사 뒤 쉼표, "단순한 X를 넘어", 상투 도입·마무리 등
- 자동 측정: 부정 대구(X가 아니라 Y), 쉼표, 강조 문장, 문단 끝 교훈, 과사용 어휘, Claude 번역 표현, 추정 중첩, 문장 리듬, 문단 길이 등. 기준치는 사람 글 분포에서 정했습니다([`dev/baseline`](dev/baseline)). 기준치 계산에 쓰지 않은 사람 글 22편 중 19편(86%)이 이 기준을 통과합니다.
- 판정: coverage, 구체성, deletion test, 구조, 한국어 자연스러움, 어투 품질, 과교정 여부

## 결과

설치한 스킬을 headless Claude Code(`claude -p`, Claude Opus 5.5, `--effort xhigh`, 사용자 CLAUDE.md 끔)로 실행하고, 같은 자료를 스킬 없이 "한국어 기술 블로그 아티클로 정리해 달라"고 요청한 결과와 비교했습니다. 자료는 논문 PDF 5편, 영문 엔지니어링 블로그 URL 1개, 프롬프트에 붙여넣은 PEP 문서 1개입니다. iteration 7회와 held-out round의 기록은 [`dev/dogfood/REPORT.md`](dev/dogfood/REPORT.md)에 있습니다.

### 같은 자료로 쓴 두 글 비교

같은 자료로 쓴 스킬 글과 스킬 없는 글을 Claude Sonnet judge에게 순서를 바꿔 두 번 보여 주고 더 나은 글을 고르게 했습니다. 두 번 모두 같은 글을 고른 경우만 승패로 셉니다. 기준은 자연스러운 한국어(강조 문장, 부정 대구, 요약 표지, 번역투, 기계적 리듬이 적은가), 자료 전달의 정확성, 구조 순입니다.

| 자료 | 스킬 글 기준 결과 |
|---|---|
| iteration 7: Antislop, Idiosyncrasies, PagedAttention 논문 | 2승, 1 split(Antislop) |
| held-out: Epanorthosis, Muñoz-Ortiz 논문, Discord 블로그 URL, PEP 659 붙여넣기 | 4승 |

judge가 스킬 없는 글에서 지적한 것은 "핵심 요약"·"TL;DR" 블록, "짚어 둘 점이 세 가지 있어요" 같은 예고형 열거, 부정 대구("A가 아니라 B"), 문장마다 붙은 bold였습니다. Antislop에서 스킬 없는 글이 이긴 순서의 근거는 PyTorch 스케치, 설정 파일 해설, 저자 주장을 의심하며 읽은 절이 있어 더 깊다는 것이었습니다.

### 지표 비교

사람 글 값은 2025년 이전 토스·카카오·당근 글의 중앙값이고, 생성 글 값은 케이스별 값의 중앙값입니다. `python dev/dogfood/summary.py`로 다시 만들 수 있습니다.

| 지표 | 사람 글 합니다체 (n=57) | 사람 글 해요체 (n=31) | 스킬 없는 Claude (n=7) | 스킬 Default (n=4) | 스킬 Casual (n=3) |
|---|---|---|---|---|---|
| 본문 글자 수(공백 제외) | 4,436 | 3,637 | 8,095 | 7,402 | 7,905 |
| 목록 줄 비율 | 0.093 | 0.086 | 0.349 | 0.048 | 0.103 |
| bold(1,000자당) | 0.68 | 0.84 | 8.00 | 0.00 | 0.00 |
| 셋 묶음 나열(1,000자당) | 0.42 | 0.61 | 1.36 | 0.51 | 0.31 |
| 연결어미 뒤 쉼표 비율 | 0.191 | 0.200 | 0.370 | 0.089 | 0.017 |
| 부정 대구(X가 아니라 Y) 문장 수 | 1.0 | 1.0 | 2.0 | 1.0 | 0.0 |
| 가장 많은 종결의 비율 | 0.41 | 0.38 | 0.41 | 0.41 | 0.39 |
| 평균 문장 길이(공백 포함) | 65.4 | 58.2 | 54.7 | 60.2 | 61.2 |
| 한 문장 문단 비율 | 0.43 | 0.33 | 0.35 | 0.21 | 0.18 |
| lint 통과 | - | - | 3/7 | 4/4 | 3/3 |
| 자료와 다르거나 근거 없는 주장(글당) | - | - | 2.0 | 0.0 | 0.0 |
| style judge 평균(0~2) | - | - | 1.58 | 1.50 | 1.58 |
| AI처럼 읽힌다고 인용된 문장(1,000자당) | - | - | 0.53 | 0.54 | 0.34 |

- 스킬 없는 Claude 글은 목록 비중, bold, 셋 묶음, 연결어미 뒤 쉼표가 사람 글 중앙값의 2~12배였습니다. 스킬 글은 이 지표가 사람 글 중앙값 근처이거나 그보다 낮습니다.
- 연결어미 뒤 쉼표(Casual 0.017)와 한 문장 문단 비율(0.18~0.21)은 사람 글 중앙값보다 낮습니다. 스킬 글은 이 두 지표에서 사람 글 분포의 아래쪽에 있습니다.
- 자료와 다르거나 근거 없는 주장은 fidelity judge가 글의 수치와 주장을 원문과 대조해 센 값입니다. 스킬 글 7편 중 1편에 1건이 있었고, 스킬 없는 글 7편은 글당 중앙값 2건이었습니다.
- style judge 평균과 "AI처럼 읽힌다고 인용된 문장" 수는 스킬 글과 스킬 없는 글의 차이가 작습니다. judge가 사람 글 대조군(토스·카카오·당근 글)에 준 평균도 1.1~1.2점입니다(채용 안내, 인사말, 오탈자에서 감점). 이 점수는 rubric 항목(구체성, deletion test, 구조, 자연스러움, 어투, 과교정)의 충족도이고 사람 글처럼 읽히는 정도를 재지 않습니다. 스킬 글에 남은 주된 지적은 "문장 길이와 종결이 고르다"(J8)입니다.
- Casual의 "~죠", "~는데요"는 사람 해요체 글에서 각각 문장의 3.4%를 차지하는 어미라 허용했습니다. judge는 이 어미를 어투가 흔들린 곳으로 읽은 적이 있습니다.

### claude plugin eval

`evals/`의 세 케이스를 스킬이 있는 arm과 없는 arm으로 2회씩 실행했습니다(Claude Opus 5.5, grader judge는 Sonnet). eval run은 사용자 설정과 개인 skill을 읽지 않는 격리 환경에서 돕니다.

| case | 스킬 있음 (2회) | 스킬 없음 (2회) | 스킬 없음에서 실패한 grader |
|---|---|---|---|
| note-default: 엔지니어링 노트를 합니다체로 정리 | 1.00, 1.00 | 0.88, 0.88 | 지어낸 경험 1회, 문장 안 em dash·세미콜론 1회 |
| note-casual: 같은 노트를 해요체로 정리 | 1.00, 1.00 | 0.88, 0.62 | 지어낸 경험 2회, em dash·세미콜론 1회, 자료에 없는 수치 1회 |
| retone-casual: 합니다체 글의 어투만 해요체로 변환 | 1.00, 1.00 | 1.00, 1.00 | - |

- 요청은 "아래 자료의 핵심 내용을 한국어 기술 블로그 아티클로 정리해서 article.md로 저장해줘"처럼 `/techblog` 없이 썼고, 6회 모두 스킬이 호출됐습니다.
- 첫 측정에서는 grader 두 개가 의도와 다르게 판정했습니다. numbers grader는 표의 값으로 계산한 수치(4,800 ÷ 900 ≈ 5.3배)를 자료에 없는 수치로 판정했고, same-content grader는 tone.md가 허용하는 "~죠" 한 곳을 내용 변경으로 판정했습니다. 두 grader의 문구에 원래 기준(목록의 값으로 계산한 수치 허용, 해요체 어미 변형은 종결부 변경)을 적은 뒤 다시 잰 값이 위 표입니다. 첫 측정의 케이스별 평균은 스킬 있음 0.88, 0.94, 0.75, 스킬 없음 0.88, 0.69, 1.00이었습니다. 다시 잰 실행에서는 스킬의 어투 변환 결과에 "~죠"가 나오지 않아서, same-content grader의 문구 수정은 이 실행으로 확인되지 않았습니다.

## 예시

[`examples/`](examples/)에 PagedAttention 논문(SOSP 2023, CC BY 4.0)을 정리한 Default 글과 Casual 글 한 쌍이 있습니다. 한 번의 실행에서 나온 글이라 문장 192개의 순서와 수치가 같고 종결부만 다릅니다.

## 한계

- 검사 스크립트는 형태소 분석기 없이 정규식으로 셉니다. 오탐이 있어서 기준치를 사람 글에 같은 스크립트를 돌린 값으로 잡았습니다.
- 사람 글 baseline은 토스·카카오·당근 기술 블로그만 썼습니다.
- judge는 Claude Sonnet이라 같은 계열 모델이 판정한 결과입니다. 사람 독자의 평가와 다를 수 있으니 결과 글은 직접 읽어 확인해야 합니다.
- 같은 설정을 두 번 실행해 run 간 편차를 잰 것은 몇 쌍뿐입니다. 위 결과의 작은 차이(style 평균 0.1~0.2점)는 편차 범위일 수 있습니다.
- 자료와 다른 주장이 없다는 것은 한 번의 실행으로 보장되지 않습니다. 같은 URL 자료(Discord 블로그)를 두 번 정리했을 때 fidelity judge가 찾은 문제는 0건과 6건이었고, 6건 중 3건은 글의 문제(자료에 없는 "수십만 명", 추론을 단정한 문장, 두 수치의 기준 혼동)였습니다. 공개 전에 수치와 고유명사를 원문과 대조해야 합니다.
- Windows에서 `claude plugin eval`은 eval run 안에서 Bash를 허용하지 않습니다. 이 환경에서는 검사 스크립트 대신 rubric을 직접 점검하는 경로로 동작합니다.
- 이미지와 인터랙티브 컴포넌트는 다루지 않습니다.

## 개발

```bash
python -m unittest discover tests        # 단위 테스트
claude plugin validate .                  # plugin manifest 검사
claude plugin eval . --allow-tools Write Edit --scaffold   # evals/ 케이스, 스킬 유무 비교
```

- `dev/baseline/`: 사람 글 측정(`measure.py`)과 기준치 생성(`calibrate.py`)
- `dev/dogfood/`: headless Claude Code로 스킬을 실행하고(`run.py`) lint·tone_check(`evaluate.py`)와 judge(`judge.py`)로 평가하는 도구
- `evals/`: `claude plugin eval` 케이스(짧은 엔지니어링 노트의 Default·Casual 정리, 기존 글의 어투 변환)

## License

MIT
