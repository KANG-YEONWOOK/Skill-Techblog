# dogfooding

이 폴더의 도구는 설치된 techblog 스킬을 headless Claude Code(`claude -p`)로 실행하고, 스킬이 쓴 글을 평가한다. 스킬이 글을 쓰는 데에는 이 폴더의 도구가 필요 없다.

## 실행 조건

- 스킬은 directory junction으로 설치한다. `~/.claude/skills/techblog`가 저장소의 `skills/techblog`를 가리킨다.
- 실행할 때 사용자의 `~/.claude/CLAUDE.md`와 auto memory를 끈다(`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`). 스킬만 설치한 다른 사용자와 같은 조건에서 결과를 보기 위해서다.
- 글을 쓰는 실행은 사용자 기본 설정과 같은 `--model opus --effort xhigh`로 한다. `--allowedTools`를 따로 주지 않고, 스킬의 `allowed-tools`에 적힌 도구만으로 실행한다.
- `run.py`는 자료 파일을 실행 폴더에 복사한다. 실행 결과는 저장소 밖의 `%TEMP%\techblog-work\dogfood\<iter>\<case>\`에 저장한다.
- judge는 새 `claude -p` 프로세스로 실행한다. judge 모델의 기본값은 sonnet이고, judge에게는 Read 도구만 허용한다. judge의 답은 `--json-schema`로 정한 형식으로 받는다.

## 실행 방법

```bash
python dev/dogfood/run.py --iter iter-1 --only A-antislop-casual B-idiosyncrasies-default --jobs 2
python dev/dogfood/evaluate.py --iter iter-1        # transcript 점검, lint와 tone_check 다시 실행
python dev/dogfood/judge.py --iter iter-1 --compare iter-0   # style, fidelity, pairwise, clarity judge
python dev/dogfood/report.py --iter iter-1          # REPORT.md에 붙일 표
python dev/dogfood/summary.py                       # 사람 글, 스킬 없는 글, 스킬 글의 지표 비교표
python dev/dogfood/judge.py --iter iter-11 --within  # 같은 실행의 초안 사본과 후처리를 마친 글 비교
python dev/dogfood/report.py --iter iter-11 --within # 위 비교의 표
python dev/dogfood/run.py --iter iter-11r --revise-from iter-11 --jobs 1   # 같은 초안을 새 세션에서 후처리만
python dev/dogfood/judge.py --iter iter-11 --cross iter-11r                # 같은 초안의 두 후처리 결과 비교
python dev/baseline/repeats_stats.py --cache <사람 글 캐시>                # 사람 글의 반복 후보 수 분포
python dev/dogfood/judge.py --iter iter-13 --skip style fidelity pairwise clarity   # 문장 단위 J5(korean)만
python dev/baseline/ko_stats.py --cache <사람 글 캐시> --pairs <수정 전후 쌍 폴더>    # 한국어 점검 항목의 오탐과 recall
python dev/dogfood/judge.py --iter iter-090 --skip style fidelity pairwise clarity korean --human-cache <사람 글 캐시>   # 용어 설명 J10(terms)만
```

`run.py`는 프롬프트에 `--defaults`를 붙이고 `claude -p`에 `--disallowedTools AskUserQuestion`을 준다. headless 실행에는 설정 질문에 답할 사람이 없어서, 독자와 분량은 기본값을 쓰고 어투는 케이스에 적은 값을 쓴다. `"settings": "ask"` 케이스만 `--defaults`와 어투 인자를 빼고 실행해, 질문할 수 없을 때 기본값으로 쓰고 보고에 값과 출처를 적는지 본다.

judge가 사람 글 대조군을 읽는 캐시 폴더는 기본값이 `%TEMP%\techblog-work\baseline\cache`다. `measure.py collect --cache`로 다른 곳에 모았으면 `--human-cache`로 그 폴더를 준다.

## 케이스 (`cases.json`)

| 이름 | 자료 | 어투 | 용도 |
|---|---|---|---|
| A-antislop-casual | Paech et al. (2025), Antislop (arXiv 2510.15061) | Casual | iteration마다 실행 |
| B-idiosyncrasies-default | Sun et al. (2025), Idiosyncrasies in LLMs (ICML) | Default | iteration마다 실행 |
| S1-pagedattention-casual | Kwon et al. (2023), PagedAttention (arXiv 2309.06180) | Casual | iteration마다 실행. AI 글쓰기와 관계없는 자료 |
| Arep-antislop-casual | A와 같은 자료 | Casual | 같은 설정을 두 번 실행했을 때의 편차 측정 |
| A0, B0, S10 | A, B, S1과 같은 자료 | | 스킬 없이 "한국어 기술 블로그 글로 정리해 달라"고 요청한 결과(iteration 0) |
| C-epanorthosis-default | Boggia (2026), Artificial Epanorthosis (arXiv 2607.21498) | Default | held-out |
| D-munozortiz-casual | Muñoz-Ortiz et al. (2024), Contrasting Linguistic Patterns in Human and LLM-Generated News Text | Casual | held-out |
| E-discord-url-default | Discord 엔지니어링 블로그 "How Discord Stores Trillions of Messages"(URL로 전달) | Default | held-out. 영문 웹 문서 |
| F-retone-casual | 마지막 iteration에서 A 케이스가 쓴 Default 초안 | Casual | held-out. `--retone` 확인 |
| S2-pep659-pasted-default | PEP 659(public domain) 본문을 프롬프트에 붙여넣음 | Default | held-out. 붙여넣은 텍스트 |
| S3-pagedattention-sonnet-casual | S1과 같은 자료 | Casual | held-out. `--model sonnet` |
| C0, D0, E0, S20 | C, D, E, S2와 같은 자료 | | 스킬 없이 요청한 결과. held-out pairwise의 비교 대상 |
| N1-note-default, N2-note-casual | `evals/note-*`의 엔지니어링 노트를 파일로 전달 | Default, Casual | 0.4.0 후처리 단계의 smoke test |
| W3-connectome-function-casual | Bargmann & Marder (2013), From the connectome to brain function (Nature Methods) | Casual | 0.8.0 용어 설명, 출처 주어와 인용 동사, 한 낱말 한 뜻 확인. 사용자 검토 3주차 3편 노트의 주 자료. 저작권 자료라 저장소에 넣지 않는다 |
| N3-note-nosettings | `evals/note-default`의 엔지니어링 노트(`{work}/sources/note.md`) | 묻지 않음 | 0.9.0 설정 질문의 대체 경로. 어투 인자와 `--defaults` 없이 실행하고 AskUserQuestion을 막는다. 기본값(Default, 사전 지식이 없는 독자, 자료에 맞춘 분량)으로 쓰고 보고에 값과 출처를 적어야 한다 |

E와 E0에는 `source_local`이 있다. judge는 URL을 다시 가져오지 않고, 한 번 받아 둔 본문 파일(`{work}/sources/discord.md`)로 판정한다. 같은 글의 두 버전을 같은 원문으로 판정하기 위해서다.

A와 B의 자료는 AI 글쓰기를 다룬 연구라서, 두 케이스의 글에는 AI 문체 표현이 인용으로 많이 나온다. lint는 따옴표 안의 텍스트를 검사에서 뺀다. S1은 이런 인용이 없는 자료로 같은 기준을 확인하려고 넣은 케이스다.

## 평가 방법

- `evaluate.py`는 결과를 규칙으로 점검한다. 점검 항목은 lint 판정, tone_check 결과, 스킬이 lint와 tone_check를 실제로 실행했는지, Casual 글을 쓰기 전에 Default 초안을 먼저 썼는지, 권한 거부 횟수, 비용, turn 수다.
- style judge는 이번 iteration의 글과 사람이 쓴 블로그 글 2편(대조군)을 섞어서 채점하고, 어느 글을 누가 썼는지 judge에게 알리지 않는다. judge는 J2~J6, J8 점수와 "AI가 쓴 것처럼 읽히는 문장" 인용을 낸다. 0.8.0에는 J10(용어와 중심 대상 설명)도 style judge가 글 전체를 보고 점수 하나로 매겼는데, 같은 글에 0점과 2점을 줘서 0.9.0부터 terms judge로 옮겼다. J5의 자연스러움은 "사람이 쓴 한국어 정보 글(기술 블로그)처럼 읽히는가"로 묻는다. `judge.py`는 인용이 본문에 그대로 있는지 확인한 뒤 1,000자당 인용 수(J7)를 센다. style judge는 글마다 2번 실행한다.
- fidelity judge는 글의 수치와 주장을 자료 원문과 대조해 supported, unsupported, contradicted로 나누고(0.9.0부터 용어 설명에 쓴 일반 지식은 general_knowledge로 따로 나누고 사실인지를 note에 적는다), 자료의 문제, 방법, 결과, 한계가 글에 다 있는지(J1)를 매긴다.
- pairwise judge는 같은 자료로 쓴 두 글을 순서를 바꿔 두 번 비교한다. 두 번 모두 같은 글을 골랐을 때만 승패로 센다. 0.9.0부터는 독자를 "자료 분야의 지식이 충분하지 않거나 없을 수 있는 사람"으로 알려 주고, 이해하기 쉬운지를 볼 때 처음 나오는 말을 설명했는지도 보게 한다.
- korean judge(J5, 0.6.0)는 최종 글(`article.md`)의 헤딩과 모든 문장을 80문장씩 나눠 하나씩 판정한다. judge는 문장마다 natural("사람이 쓴 한국어 정보 글에 그대로 실릴 만한 문장")과 awkward(korean-review.md의 유형 A~R 가운데 문장 하나로 판정할 수 없는 I, M 제외)를 고르고, 1,000자당 awkward 문장 수를 같은 어투의 사람 글 대조군 3편과 비교한다. 사람 글 결과는 `%TEMP%\techblog-work\dogfood\_korean_humans.json`에 저장해 다시 쓴다. 사용자 검토 노트 2편으로 검증했을 때 judge가 고른 문장 중 사용자가 고친 문장은 54~69%, 사용자가 고친 문장 중 judge가 고른 문장은 23~27%였다(rubric.md의 J5). `evaluate.py`는 6단계에서 korean-review.md를 넘긴 subagent 호출 수(`ran.korean_subagent`)를 기록한다.
- terms judge(J10, 0.9.0)는 글만 읽고 독자(자료 분야의 지식이 충분하지 않거나 없을 수 있는 사람)가 모를 수 있는 말을 모두 적는다. 말마다 처음 나온 문장, 글의 설명 인용, 빠진 요소(무엇인지, 하는 일, 이름의 뜻, 설명에 쓴 말, 목록에서만 소개)를 받는다. `judge.py`는 처음 나온 문장이 본문에 없는 말을 빼고, 빠진 요소가 있는 말의 수와 중심 대상 정의로 J10(rubric.md의 0~2점)을 계산한다. 글마다 두 번 실행하고, 두 실행이 빠졌다고 적은 말의 겹침(Jaccard)과 두 실행이 모두 적은 말로 계산한 J10(`j10_both`)을 함께 낸다. 사람 글 대조군 6편도 같은 방식으로 판정해 `%TEMP%\techblog-work\dogfood\_terms_humans.json`에 둔다. 사람 글 대조군은 개발자를 독자로 쓴 글이라 분야 용어를 풀지 않는 경우가 많다. 그래서 이 값은 목표가 아니라 참고값이다.
- clarity judge(J9)는 글 한 편에서 문단의 첫 문장, 수치가 든 문장, lint의 A18에 걸린 문장을 뽑아 하나씩 판정한다. judge에게는 문장마다 그 문장이 속한 절의 헤딩과 바로 앞 문장을 함께 보여 준다. judge는 그 문장만으로 무엇에 대한 말인지 알 수 있는지(self_contained), 바로 앞 문장을 읽어야 알 수 있는지(needs_prev), 앞 문장까지 읽어도 알 수 없는지(unclear)를 고른다. 용어를 모르는 것은 J9의 판정 이유가 아니다(용어는 J10이 본다). 사람 글 대조군 6편(합니다체 3편, 해요체 3편)도 같은 방식으로 판정하고, 그 결과는 `%TEMP%\techblog-work\dogfood\_clarity_humans.json`에 저장해 다음 실행에서 다시 쓴다.
- 후처리 비교(`--within`, 0.4.0): 같은 실행에서 나온 초안 사본(`article.unrevised.md`)과 후처리를 마친 합니다체 글(Default는 `article.md`, Casual은 `article.draft.md`)을 비교한다. 두 글은 같은 초안에서 나와서 차이는 후처리에서만 생긴다.
  - 전체 pairwise: 위 pairwise와 같은 문구로 순서를 바꿔 두 번 비교한다.
  - 절 A/B: 후처리로 내용이 바뀐 H2 절만 모아 절마다 두 버전을 고르게 한다. 순서를 바꿔 두 번 묻고, 무승부를 뺀 표 중 후처리 글 표의 비율을 센다. 거의 같은 두 글을 통째로 비교하면 순서에 따라 판정이 갈리기 쉬워서 넣었다.
  - clarity: 두 글을 따로 판정한 뒤 문장과 바로 앞 문장이 같은 항목끼리 맞춘다. 바뀌지 않은 항목에서 판정이 뒤집힌 비율을 judge 잡음으로 함께 적는다.
  - fidelity: 두 글을 같은 원문으로 판정하고, 후처리 글에서 걸린 주장이 초안에 그대로 있던 문장인지 후처리에서 바뀐 문장인지 나눈다.
  - style: 케이스마다 두 글과 합니다체 사람 글 2편을 한 묶음으로 두 번 채점한다. 채점 묶음 단위로 점수가 함께 오르내리는 영향을 두 글이 같이 받게 하려는 설계다. 점수와 함께 "같은 정보나 같은 문형이 되풀이돼 단조롭게 읽히는 문장" 인용을 받아 본문에 있는 인용만 센다.
  - `evaluate.py`는 두 글의 lint, 반복 후보 수, 바뀐 문장 비율, 사라지거나 새로 생긴 수치, revise_ko.py 실행 순서, start 이후의 토큰 비율, context compaction 횟수를 기록한다.
- judge 모델은 Claude 계열이라 같은 계열 모델이 쓴 글에 점수를 후하게 줄 수 있다. 사람 글 대조군과 인용 검증으로 이 영향을 줄이고, 최종 결과는 사람이 직접 읽어 확인한다.

## 종료 기준

모든 케이스가 다음 조건을 연속 2회 iteration에서 만족하면 held-out 케이스로 넘어간다.

- Gate 위반이 0개, lint FAIL이 0개, WARN이 3개 이하이고 tone_check를 통과한다.
- fidelity judge가 찾은 unsupported와 contradicted 주장이 0개다.
- style judge 평균이 1.6 이상이고 0점이 없으며, J7이 사람 글 대조군의 p75 이하다.
- iteration 0의 글과 비교한 pairwise에서 80% 이상 이긴다.

iteration은 최대 6회로 정했다. 결과가 수렴하지 않거나, 개선 폭이 같은 설정을 두 번 실행했을 때의 편차 수준에서 멈추면 남은 문제와 근거를 `REPORT.md`에 정리한다.

실제로는 iteration 7까지 실행했다. iteration 6에서 문단을 나누라는 지시가 회귀를 만들어서, 그 지시를 고친 iteration 7을 한 번 더 실행했다. 종료 기준을 연속 2회 만족하지는 못했다. A 케이스의 pairwise 결과와 style 평균이 기준에 못 미쳤고, held-out round는 iteration 7 버전으로 실행했다. 판단 근거는 `REPORT.md`의 "종료 판단" 절에 있다.

iteration 8~10은 문장을 따로 읽어도 이해되는 글을 목표로 한 수정이다. 수정 전 버전(iter-8b)과 각 수정 버전을 같은 4개 케이스(B, D, E, S1)로 실행해 clarity, style, fidelity, pairwise judge로 비교했다. 수정은 계획대로 최대 2회(iteration 9, 10) 했고, 결과와 남은 문제는 `REPORT.md`의 iteration 8~10 절과 "수정 종료 판단" 절에 있다.

iteration 11~12는 0.4.0의 후처리 단계를 시험한 기록이다. 초안을 쓴 context에서 후처리한 iteration 11, 같은 초안을 새 세션에서 후처리한 비교(iter-11r, iter-11s, `run.py --revise-from`), subagent에 후처리를 맡긴 iteration 12의 결과와 판단은 `REPORT.md`의 iteration 11~12 절에 있다. `run.py --skill-dir`은 지침을 고치는 동안 revise 모드 실행이 고치기 전 지침을 읽게 고정할 때 쓴다.
