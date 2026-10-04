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
- 자동 측정: 부정 대구(X가 아니라 Y), 쉼표, 강조 문장, 문단 끝 교훈, 과사용 어휘, Claude 번역 표현, 추정 중첩, 문장 리듬 등. 기준치는 사람 글 분포에서 정했습니다([`dev/baseline`](dev/baseline)).
- 판정: coverage, 구체성, deletion test, 구조, 한국어 자연스러움, 어투 품질, 과교정 여부

## 한계

- 검사 스크립트는 형태소 분석기 없이 정규식으로 셉니다. 오탐이 있어서 기준치를 사람 글에 같은 스크립트를 돌린 값으로 잡았습니다.
- 사람 글 baseline은 토스·카카오·당근 기술 블로그만 썼습니다.
- 이미지와 인터랙티브 컴포넌트는 다루지 않습니다.

## 개발

```bash
python -m unittest discover tests        # 단위 테스트
claude plugin validate .                  # plugin manifest 검사
```

- `dev/baseline/`: 사람 글 측정(`measure.py`)과 기준치 생성(`calibrate.py`)
- `dev/dogfood/`: headless Claude Code로 스킬을 실행하고 평가하는 도구

## License

MIT
