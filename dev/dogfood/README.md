# dogfooding

설치된 techblog 스킬을 headless Claude Code(`claude -p`)로 실행하고 결과를 평가하는 도구다. 스킬 동작에는 필요 없다.

## 조건

- 스킬 설치: `~/.claude/skills/techblog` → 저장소 `skills/techblog` (directory junction)
- 사용자 `~/.claude/CLAUDE.md`와 auto memory를 끄고 실행한다(`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`). 스킬만 설치한 다른 사용자와 같은 조건을 만들기 위해서다.
- 생성: 사용자 기본 설정과 같은 `--model opus --effort xhigh`. 추가 `--allowedTools` 없이 스킬의 `allowed-tools`만으로 실행한다.
- 자료 파일은 실행 폴더에 복사한다. 결과는 `%TEMP%\techblog-work\dogfood\<iter>\<case>\`에 둔다(저장소 밖).
- judge: 새 `claude -p` 프로세스, 기본 sonnet, Read 도구만 허용, `--json-schema`로 구조화 출력.

## 실행

```bash
python dev/dogfood/run.py --iter iter-1 --only A-antislop-casual B-idiosyncrasies-default --jobs 2
python dev/dogfood/evaluate.py --iter iter-1        # transcript 점검, lint·tone_check 재실행
python dev/dogfood/judge.py --iter iter-1 --compare iter-0   # style·fidelity·pairwise judge
```

## 케이스 (`cases.json`)

| 이름 | 자료 | 어투 | 용도 |
|---|---|---|---|
| A-antislop-casual | Paech et al. (2025), Antislop (arXiv 2510.15061) | Casual | 반복 |
| B-idiosyncrasies-default | Sun et al. (2025), Idiosyncrasies in LLMs (ICML) | Default | 반복 |
| S1-pagedattention-casual | Kwon et al. (2023), PagedAttention (arXiv 2309.06180) | Casual | 반복, AI 글쓰기와 무관한 자료 |
| Arep-antislop-casual | A와 같음 | Casual | run 간 편차 |
| A0, B0, S10 | 위와 같음 | | 스킬 없이 "한국어 기술 블로그 글로 정리해 달라"고 요청한 결과(iteration 0) |

A, B의 자료는 AI 글쓰기 연구라서 글에 AI 문체 표현이 인용으로 많이 나온다. lint는 따옴표 안을 검사에서 뺀다. S1은 이런 인용이 없는 자료로 같은 기준을 확인하려고 넣었다.

## 평가

- 결정적 점검(`evaluate.py`): lint 판정, tone_check, 스킬이 lint와 tone_check를 실제로 실행했는지, Default 초안을 Casual보다 먼저 썼는지, 권한 거부, 비용, turn 수
- style judge: 이번 iteration의 글과 사람 블로그 글(대조군 2편)을 섞고 누가 썼는지 알리지 않는다. J2~J6, J8 점수와 "AI가 쓴 것처럼 읽히는 문장" 인용을 받고, 인용이 본문에 그대로 있는지 확인해 1,000자당 개수(J7)를 센다. 2회 실행.
- fidelity judge: 글의 수치·주장을 자료 원문과 대조(supported, unsupported, contradicted)하고 coverage(J1)를 매긴다.
- pairwise judge: 같은 자료로 쓴 두 글을 순서를 바꿔 두 번 비교한다. 두 번 모두 같은 쪽을 고를 때만 승패로 센다.
- judge는 Claude 계열이라 같은 계열 출력에 점수를 후하게 줄 수 있다. 사람 글 대조군과 인용 검증으로 이 영향을 줄이고, 최종 결과는 사람이 직접 읽어 확인한다.

## 종료 기준

연속 2회 iteration에서 모든 케이스가 다음을 만족하면 held-out 케이스로 넘어간다.

- Gate 위반 0, lint FAIL 0, WARN 3 이하, tone_check 통과
- fidelity: unsupported·contradicted 0
- judge 평균 1.6 이상, 0점 없음, J7이 사람 글 대조군 p75 이하
- iteration 0 대비 pairwise 승률 80% 이상

iteration은 최대 6회다. 수렴하지 않거나 run 간 편차 수준에서 개선이 멈추면 남은 문제와 근거를 `REPORT.md`에 정리한다.
