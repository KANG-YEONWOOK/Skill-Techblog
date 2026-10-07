# techblog

techblog는 Claude Code와 Codex에서 쓰는 skill입니다. 논문 PDF, 기술 문서, 웹 페이지, 대화에 붙여넣은 텍스트 같은 자료를 주면 핵심 내용을 정리한 한국어 기술 블로그 글을 씁니다. 두 환경은 같은 글쓰기 지침과 검사 스크립트를 사용합니다. 글의 문체는 토스, 카카오, 당근 같은 한국 테크 기업의 기술 블로그에 실린 글을 기준으로 맞춥니다.

AI가 쓴 글에는 사람이 쓴 글보다 훨씬 자주 나오는 표현 습관이 있습니다. "A가 아니라 B입니다" 같은 대구, 문단마다 붙는 굵은 글씨, 근거 없이 항목 셋으로 맞춘 나열, 앞 내용을 다시 요약하는 마무리 문장이 대표적입니다. 이 skill은 글을 쓴 뒤 검사 스크립트로 이런 표현이 얼마나 자주 나오는지 재고, 사람이 쓴 기술 블로그 글에서 잰 기준을 넘는 문장만 고칩니다.

## 이 skill이 하는 일

- 이 skill을 사용해 글을 작성할 때, 작성할 글의 어투를 **Default**(합니다체)와 **Casual**(토스식 해요체) 중에서 고를 수 있습니다. 두 어투로 쓴 글의 내용에는 차이가 없습니다.
- 글에는 자료에 있는 사실만 씁니다. skill은 글을 쓰기 전에 자료의 수치와 주장을 fact sheet라는 작업 파일에 옮겨 적고, 글에 나온 수치가 이 파일에 있는지 검사 스크립트로 대조합니다. 글쓴이가 직접 겪은 것처럼 꾸민 경험이나 자료에 없는 수치는 쓰지 않습니다.
- 문장마다 무엇에 대한 말인지가 드러나게 씁니다. 수치를 쓰는 문장에는 그 수치가 무엇을 잰 값이고 무엇과 비교한 값인지를 함께 씁니다.
- 초안을 다 쓰고 점검한 뒤에는 후처리 단계를 거칩니다. 초안의 규칙은 모든 글에 같게 적용되기 때문에, 수치가 많은 글에서는 같은 비교 기준이 문장마다 되풀이되고, 표를 쓴 글에서는 비교 기준이 표에만 있는 문장이 생깁니다. 후처리에서는 초안을 쓰지 않은 subagent가 글 전체를 처음부터 다시 읽고, 이런 곳을 이 글의 독자에게 필요한 만큼만 남기거나 채웁니다.
- 글을 평가하는 기준(rubric)은 AI 문체에 관한 연구 자료와, 토스, 카카오, 당근 기술 블로그 글 224편을 측정한 값으로 정했습니다.

## 설치

### Claude Code: plugin marketplace

Claude Code 세션에서 아래 두 명령을 차례로 실행합니다.

```
/plugin marketplace add KANG-YEONWOOK/Skill-Techblog
/plugin install techblog@skill-techblog
```

터미널에서 설치할 때는 아래 명령을 씁니다.

```bash
claude plugin marketplace add KANG-YEONWOOK/Skill-Techblog
claude plugin install techblog@skill-techblog
```

설치한 뒤에는 `/techblog` 명령으로 skill을 실행합니다. 다른 plugin이나 skill에 같은 이름의 명령이 있으면 `/techblog:techblog`로 실행합니다. 새 버전은 `/plugin marketplace update skill-techblog` 명령으로 받습니다.

### Claude Code: 직접 설치

이 저장소의 `skills/techblog` 폴더를 Claude Code의 개인 skill 폴더(`~/.claude/skills/`)에 복사해도 같은 skill을 쓸 수 있습니다.

macOS와 Linux에서는 아래 명령을 실행합니다.

```bash
git clone https://github.com/KANG-YEONWOOK/Skill-Techblog.git
mkdir -p ~/.claude/skills
cp -r Skill-Techblog/skills/techblog ~/.claude/skills/
```

Windows PowerShell에서는 아래 명령을 실행합니다.

```powershell
git clone https://github.com/KANG-YEONWOOK/Skill-Techblog.git
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse Skill-Techblog\skills\techblog "$HOME\.claude\skills\techblog"
```

### Codex: plugin marketplace

Codex CLI에서 다음 명령을 실행합니다. `codex plugin add`가 있는 CLI가 필요하며, 검증에 사용한 버전은 0.155.1입니다.

```bash
codex plugin marketplace add KANG-YEONWOOK/Skill-Techblog
codex plugin add techblog@skill-techblog
```

설치 후 새 세션에서 `$techblog`로 호출하거나 스킬 선택기에서 techblog를 선택합니다. 플러그인 화면에서도 `skill-techblog` 마켓플레이스의 techblog를 확인할 수 있습니다. 업데이트할 때는 다음 명령을 실행하고 새 세션을 엽니다.

```bash
codex plugin marketplace upgrade skill-techblog
codex plugin add techblog@skill-techblog
```

저장소의 수정본을 시험할 때는 GitHub 주소 대신 로컬 저장소 경로를 등록합니다.

```bash
codex plugin marketplace add /absolute/path/to/Skill-Techblog
codex plugin add techblog@skill-techblog
```

### Codex: 직접 설치

Codex 대화에서 기본 제공 설치 스킬에 아래처럼 요청할 수 있습니다.

```text
$skill-installer KANG-YEONWOOK/Skill-Techblog 저장소의 skills/techblog 스킬을 설치해줘.
```

직접 복사하려면 macOS/Linux에서 다음 명령을 실행합니다. 목적지에 techblog가 없는 첫 설치 기준입니다.

```bash
git clone https://github.com/KANG-YEONWOOK/Skill-Techblog.git
mkdir -p "$HOME/.agents/skills"
cp -R Skill-Techblog/skills/techblog "$HOME/.agents/skills/techblog"
```

Windows PowerShell:

```powershell
git clone https://github.com/KANG-YEONWOOK/Skill-Techblog.git
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse Skill-Techblog\skills\techblog "$HOME\.agents\skills\techblog"
```

특정 프로젝트에서만 쓸 때는 그 프로젝트의 `.agents/skills/techblog`에 복사합니다. `$skill-installer`가 사용하는 `~/.codex/skills`도 지원되는 설치 위치입니다. 직접 설치와 플러그인 설치 중 하나를 선택하면 스킬이 중복으로 표시되는 것을 피할 수 있습니다. 직접 복사한 스킬은 저장소를 업데이트한 뒤 기존 폴더를 백업하고 새 폴더로 교체합니다. 설치나 업데이트가 표시되지 않으면 새 Codex 세션을 엽니다.

### 필요한 환경

- Claude Code 또는 Codex가 필요합니다.
- Python 3.8 이상이 설치돼 있으면 skill이 검사 스크립트(`lint_ko.py`, `revise_ko.py`, `tone_check.py`)를 실행합니다. Python이나 셸이 없으면 같은 기준을 문서로 읽고 직접 점검하며 자동 검사를 하지 못했다고 보고합니다. 검사 스크립트는 외부 패키지를 쓰지 않습니다.
- Claude Code는 PDF를 Read로 읽습니다. Codex에 PDF 읽기 기능이 없으면 Poppler의 `pdftotext`와 `pdftoppm`을 사용합니다. 읽기에 필요한 도구가 없으면 읽을 수 있는 원문을 요청합니다. 스킬이 도구를 자동 설치하지는 않습니다.
- 후처리는 독립 subagent가 제공되면 해당 기능을 사용합니다. 사용할 수 없으면 같은 후처리 지침을 직접 수행하고 그 사실을 보고합니다.

## 사용법

Claude Code:

```
/techblog paper.pdf
/techblog casual https://arxiv.org/pdf/2309.06180 -o paged-attention.md
/techblog default design-doc.md 독자는 백엔드 개발자, 분량은 5,000자 안팎
/techblog casual --retone paged-attention.md
```

Codex:

```text
$techblog paper.pdf
$techblog casual https://arxiv.org/pdf/2309.06180 -o paged-attention.md
$techblog default design-doc.md 독자는 백엔드 개발자, 분량은 5,000자 안팎
$techblog casual --retone paged-attention.md
```

위 호출은 각 제품의 대화 입력입니다. 셸에서 비대화형으로 호출할 때는 `$`가 확장되지 않도록 인용합니다.

```bash
codex exec '$techblog default design-doc.md -o article.md'
```

| 인자 | 설명 |
|---|---|
| `default`, `casual` | 글의 어투를 정합니다. 생략하면 Default(합니다체)로 씁니다. `합니다체`, `해요체`라고 써도 됩니다. |
| 자료 | 정리할 자료의 파일 경로(PDF, 마크다운, 텍스트)나 URL입니다. 생략하면 대화에 붙여넣은 텍스트를 자료로 씁니다. |
| `-o <경로>` | 글을 저장할 파일 경로입니다. 생략하면 현재 폴더에 글 주제를 나타내는 영문 이름(예: `cache-invalidation-latency.md`)으로 저장합니다. |
| `--retone` | 이미 쓴 글의 어투만 바꿉니다. 문장의 순서, 수치, 고유명사는 바꾸지 않습니다. |
| `--keep-work` | 작업 중에 만든 파일인 fact sheet(`<이름>.facts.md`), Default 초안(`<이름>.draft.md`, Casual일 때), 후처리 전 초안 사본(`<이름>.unrevised.md`), 반복 후보 목록(`<이름>.repeats.md`)을 지우지 않고 남깁니다. 후처리 전 초안 사본과 최종 글을 비교하면 후처리에서 바뀐 문장을 볼 수 있습니다. |
| 추가 지시 | 독자, 분량, 강조할 부분 같은 요청을 문장으로 덧붙일 수 있습니다. |

## 글을 쓰는 순서

skill은 아래 순서로 글을 씁니다.

1. 자료를 끝까지 읽습니다. Claude Code의 PDF Read는 20쪽 이하로 나누고, Codex는 PDF 도구 또는 텍스트 추출과 페이지 확인을 사용합니다. 웹 페이지는 본문 전체를 가져옵니다.
2. 글의 핵심 주제를 한 문장으로 정하고, 자료의 수치, 주장, 한계를 fact sheet에 적습니다. 글에 쓰는 수치와 주장은 이 파일에서만 가져옵니다.
3. `references/style-guide.md`를 읽고 글의 제목과 절 구성을 정합니다.
4. Default(합니다체)로 초안을 씁니다. Casual로 요청해도 초안은 먼저 합니다체로 씁니다.
5. `scripts/lint_ko.py`로 초안을 검사하고 기준을 넘은 문장만 고칩니다. 이어서 문장을 하나씩 따로 읽어 무엇에 대한 말인지 알 수 있는지 확인하고, 글의 수치와 주장을 fact sheet와 대조합니다.
6. 후처리 단계에서는 초안 사본과 반복 후보 목록을 만든 뒤, 초안을 쓰지 않은 subagent에게 후처리를 맡깁니다. subagent는 초안을 처음부터 끝까지 읽고 독자가 읽다가 멈출 곳을 먼저 적습니다. 그다음 `scripts/revise_ko.py`가 찾은 반복 후보(같은 비교 기준의 반복, 비교 기준 없이 쓴 변화량, 같은 문형의 연속)를 `references/revision.md`의 판단 질문으로 판단해 필요한 곳만 고칩니다. 글쓴이가 계산한 차이와 비율은 자료 원문의 표로 다시 확인합니다. subagent가 끝나면 상위 agent가 초안 사본과 고친 글을 비교해 검사 기준에 걸린 곳을 고칩니다. 독립 subagent가 없으면 이 절차를 직접 수행합니다.
7. Casual이면 후처리를 마친 초안의 문장마다 문장 끝(종결어미)만 해요체로 바꾸고, `scripts/tone_check.py`로 두 글의 문장 수와 수치가 같은지 확인합니다.
8. 작업 파일을 지우고, 글을 저장한 경로, 초안과 최종 글의 검사 결과, 후처리에서 고친 문장 수를 짧게 보고합니다.

초안 규칙과 lint 기준치는 모든 글에 같은 값을 씁니다. 같은 비교 기준을 문장마다 되풀이하는 것이 어떤 글에서는 필요하고 어떤 글에서는 읽기를 방해하듯이, 어떤 형태가 읽기 쉬운지는 글마다 다릅니다. 그래서 후처리는 규칙 목록 대신 판단 질문("이 구절을 지우면 독자가 잃는 정보가 있는가", "이 형태가 이 글의 독자에게 더 읽기 쉬운 이유를 한 문장으로 쓸 수 있는가")으로 고칠지 정합니다. lint 기준치와 다른 형태라도 이 질문에 답할 수 있으면 남기고, 남긴 이유를 보고합니다.

AI 문체 표현의 목록(`references/ai-patterns.md`)은 초안을 쓴 뒤에만 읽습니다. 피할 표현의 목록을 글을 쓰기 전에 보여 주면 효과가 크지 않고 오히려 그 표현이 늘 수 있다는 연구 결과(Antislop, 2025)가 있어서 이 순서로 정했습니다.

## 어투

- Default 글은 카카오 기술 블로그처럼 합니다체로 씁니다. 절을 시작할 때 "~할까요?" 같은 질문을 쓰는 것은 허용합니다.
- Casual 글은 토스의 해요체 글과 당근 글처럼 정중한 해요체로 씁니다. 토스 기술 블로그 글 22편을 조사해 보니 해요체로만 쓴 글은 6편이었고, 나머지 글은 합니다체로 썼거나 두 어투를 섞어 썼습니다. 이 skill은 Casual 글을 해요체로만 씁니다.
- Casual 글은 Default 초안의 문장 끝만 바꿔서 만들기 때문에, 한 번 실행해서 나온 두 글의 내용은 같습니다. `--retone`으로 이미 쓴 글의 어투를 바꿀 때도 내용은 그대로입니다. 다만 같은 자료로 skill을 두 번 따로 실행하면 모델이 매번 다르게 글을 쓰기 때문에 두 글의 내용이 다를 수 있습니다.

## 평가 기준

평가 기준 전체는 [`skills/techblog/references/rubric.md`](skills/techblog/references/rubric.md)에 있습니다. 기준은 세 종류입니다.

- Gate는 한 번이라도 어기면 불합격인 항목입니다. 자료에 없는 사실, 겪지 않은 경험, 챗봇 응답 흔적("도움이 되셨길 바랍니다"), 어투 혼용, 접속부사 뒤 쉼표, "단순한 X를 넘어" 같은 표현이 여기에 속합니다.
- 자동 측정 항목은 검사 스크립트가 셉니다. 부정 대구("X가 아니라 Y"), 쉼표, 강조 문장, 문단 끝 교훈, 과사용 어휘, Claude가 영어 표현을 그대로 옮긴 번역투, 추정 표현 중첩, 문장 길이와 종결어미의 분포, 문단 길이를 셉니다. 기준치는 사람 글의 분포에서 정했습니다. 기준치 계산에 쓰지 않은 사람 글 22편 중 19편(86%)이 이 기준을 통과합니다.
- 판정 항목은 사람이나 judge 모델이 0~2점으로 매깁니다. 자료의 핵심을 빠짐없이 다뤘는지, 주장마다 수치와 근거가 있는지, 문장을 따로 읽어도 무엇에 대한 말인지 알 수 있는지, 한국어가 자연스러운지를 봅니다.
- 초안은 세 기준을 모두 통과해야 합니다. 후처리를 마친 최종 글은 Gate 위반과 FAIL이 없어야 하고, 후처리 때문에 AI 문체 항목이 나빠지면 안 됩니다. 문장·문단 분포 항목(문장 길이, 종결 분포, 문단 길이, 목록, 자료를 주어로 쓴 문장 비율)의 WARN은 후처리에서 이 글에 맞는 형태로 고른 결과면 남기고, 그 이유를 보고합니다.

## 평가 결과 요약

- 0.2.0 버전으로 쓴 글을 같은 자료 7건에 대해 skill 없이 쓴 글과 비교했습니다. judge는 두 글을 순서를 바꿔 두 번 읽었고, 7쌍 중 6쌍에서 두 번 모두 skill 글을 골랐습니다. 나머지 1쌍은 보여 주는 순서에 따라 판정이 갈렸습니다.
- 0.3.0 버전은 문장마다 무엇에 대한 말인지 드러나게 쓰도록 글쓰기 규칙을 바꿨습니다. 같은 자료 4건으로 잰 결과, 앞 문장을 읽어야 이해되거나 앞 문장을 읽어도 이해되지 않는 문장의 비율이 0.2.0 버전의 21.3%에서 13.5%로 낮아졌습니다. 사람이 쓴 기술 블로그 글 6편에서 같은 비율은 17.4%였습니다.
- 0.3.0 버전으로 쓴 글은 같은 자료로 0.2.0 버전이 쓴 글과의 비교에서 4쌍 중 3쌍을 이겼고 1쌍을 졌습니다.
- 0.4.0 버전은 초안을 쓴 뒤 후처리 단계를 거칩니다. 자료 5건에서 같은 실행의 후처리 전 초안과 후처리를 마친 글을 judge에게 순서를 바꿔 두 번 보여 줬고, 5건 모두 두 번 모두 후처리를 마친 글을 골랐습니다. 후처리로 바뀐 절만 따로 비교했을 때도 judge가 후처리 쪽을 고른 표가 95%(39표 중 37표)였습니다. 후처리가 만든 사실 오류는 없었습니다.
- 후처리를 초안을 쓴 context에서 바로 하면 효과가 작았습니다. 같은 자료 4건에서 바뀐 절만 비교한 표의 68%만 후처리 쪽이었고, judge는 설명 문장과 단서를 지우거나 문형을 바꾸면서 주어와 서술어가 어긋난 문장을 지적했습니다. 그래서 0.4.0은 초안을 쓰지 않은 subagent에게 후처리를 맡깁니다.
- 측정 방법과 자세한 결과는 [`EVALUATION.md`](EVALUATION.md)에 있습니다.

## 예시

[`examples/`](examples/) 폴더에는 PagedAttention 논문(SOSP 2023, CC BY 4.0)을 이 skill로 정리한 Default 글과 Casual 글이 한 편씩 있습니다. 두 글은 한 번의 실행에서 나왔기 때문에 문장의 순서와 수치가 같고 문장 끝만 다릅니다.

## 한계

- 검사 스크립트는 형태소 분석기 없이 정규식으로 표현을 셉니다. 정규식은 사람 글의 일부 표현도 잘못 잡기 때문에, 기준치를 사람 글에 같은 스크립트를 돌려서 얻은 값으로 정했습니다.
- 사람 글 기준은 토스, 카카오, 당근 세 회사의 기술 블로그 글로만 만들었습니다.
- 평가에 쓴 judge 모델은 Claude Sonnet입니다. Claude가 쓴 글을 같은 계열의 모델이 판정했으므로 사람 독자의 평가와 다를 수 있습니다. 결과 글은 직접 읽어 확인해야 합니다.
- 자료와 다른 내용이 글에 들어가지 않는다는 것은 한 번의 실행으로 보장되지 않습니다. 같은 Discord 블로그 글을 두 번 정리하게 했을 때 fidelity judge가 찾은 문제는 0건과 6건이었고, 6건 중 3건이 글의 실제 오류였습니다. 실제 오류는 자료에 없는 "수십만 명"이라는 수치, 글쓴이의 추론을 사실처럼 단정한 문장, 두 수치의 기준을 혼동한 문장이었습니다. 글을 공개하기 전에 수치와 고유명사를 원문과 대조해야 합니다.
- 초안 규칙은 수치를 쓰는 문장마다 무엇과 비교한 값인지를 쓰게 합니다. 0.3.0 버전에서는 수치가 많은 글이 "무작위 추측 정확도 20%보다" 같은 비교 기준을 문단마다 되풀이했습니다. 0.4.0의 후처리는 이런 반복을 찾아 줄이도록 만들었지만, 0.4.0 평가에 쓴 초안 9건에서는 이 반복이 다시 나오지 않아서 효과를 확인하지 못했습니다.
- 후처리는 고친 문장과 글쓴이가 계산한 값만 원문으로 다시 확인합니다. 초안 단계에서 생긴 사실 오류는 후처리 뒤에도 남을 수 있습니다.
- Claude Code로 수행한 0.4.0 평가에서는 후처리로 실행 시간이 4~6분 늘었고 한 번 실행하는 데 12~17분이 걸렸습니다. Codex의 0.5.0 호환성 검증 시간은 [`dev/codex/REPORT.md`](dev/codex/REPORT.md)에 별도로 기록했습니다.
- Windows에서 `claude plugin eval`을 실행하면 eval 안에서 Bash를 쓸 수 없습니다. 그래서 eval을 실행할 때 skill은 검사 스크립트 대신 rubric 문서를 읽고 직접 점검합니다.
- 이 skill은 글에 넣을 이미지나 상호작용하는 컴포넌트를 만들지 않습니다.

## 개발

```bash
python -m unittest discover tests        # 단위 테스트
claude plugin validate .                  # plugin manifest 검사
claude plugin eval . --allow-tools Write Edit --scaffold   # evals/ 케이스로 skill이 있을 때와 없을 때를 비교
```

- `dev/baseline/` 폴더에는 사람 글을 측정하는 스크립트(`measure.py`), 측정값으로 기준치를 만드는 스크립트(`calibrate.py`), 후처리 반복 후보가 사람 글에서 몇 개 나오는지 재는 스크립트(`repeats_stats.py`)가 있습니다.
- `dev/dogfood/` 폴더에는 headless Claude Code로 skill을 실행하는 스크립트(`run.py`), 결과 글을 다시 검사하는 스크립트(`evaluate.py`), judge 모델로 결과 글을 평가하는 스크립트(`judge.py`)가 있습니다. `judge.py --within`은 같은 실행의 후처리 전 초안과 후처리를 마친 글을 비교합니다. 실행 기록은 `REPORT.md`에 있습니다.
- `evals/` 폴더에는 `claude plugin eval`로 실행하는 평가 케이스가 있습니다.
- [`dev/codex/`](dev/codex/README.md)에는 Codex 직접 설치·플러그인 설치와 실제 글 작성을 검증하는 실행기가 있습니다. 임시 환경에서 실행하므로 개인 스킬이나 플러그인 설정을 바꾸지 않습니다. 검사 기준과 결과는 해당 문서에 기록합니다.

Codex 구성은 [공식 스킬 문서](https://learn.chatgpt.com/docs/build-skills)와 [공식 플러그인 문서](https://developers.openai.com/plugins/build/plugins)를 참고했습니다.

## License

MIT
