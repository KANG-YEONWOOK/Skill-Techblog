# 예시: PagedAttention 논문 정리

이 폴더의 두 글은 `/techblog`로 PagedAttention 논문을 정리한 결과입니다. `paged-attention.default.md`는 합니다체(Default)로 쓴 글이고, `paged-attention.casual.md`는 해요체(Casual)로 쓴 글입니다.

두 글은 한 번의 실행에서 나왔습니다. skill은 Casual로 요청받아도 합니다체 초안을 먼저 쓰고, 초안의 문장마다 문장 끝(종결부)만 해요체로 바꿔 Casual 글을 만듭니다. 그래서 두 글은 문장 수, 문장 순서, 수치가 같습니다. 두 글에서 사람이 고친 부분은 없습니다.

| 파일 | 어투 | 본문 글자 수(공백 제외) | 문장 수 | lint 결과 |
|---|---|---|---|---|
| [paged-attention.default.md](paged-attention.default.md) | Default(합니다체) | 9,700 | 177 | Gate 0, FAIL 0, WARN 0 |
| [paged-attention.casual.md](paged-attention.casual.md) | Casual(해요체) | 9,547 | 177 | Gate 0, FAIL 0, WARN 0 |

`tone_check.py paged-attention.default.md paged-attention.casual.md`로 두 글을 비교한 결과, 문장 177쌍 모두 문장 끝만 달라서 FAIL과 WARN이 0개였습니다.

## 생성 조건

- 실행한 명령은 `/techblog casual ./input.pdf -o article.md --keep-work`입니다.
- 모델은 Claude Opus 5.5(`--model opus --effort xhigh`)이고, Claude Code 버전은 2.1.289입니다.
- skill은 commit 034891a 버전입니다. 이 버전은 0.3.0(commit d218dd6)과 SKILL.md 본문이 같고, frontmatter의 description과 버전 번호만 다릅니다.
- `paged-attention.default.md`는 `--keep-work`로 남긴 Default 초안(`article.draft.md`)이고, `paged-attention.casual.md`는 같은 실행의 출력 파일(`article.md`)입니다.
- 이 글은 dogfooding iteration 10의 S1 케이스에서 나왔습니다. 평가 기록은 [dev/dogfood/REPORT.md](../dev/dogfood/REPORT.md)에 있습니다.

## 평가 결과

- 문장 완결성(J9): judge가 문단의 첫 문장, 수치가 든 문장, lint 점검 후보 문장 110개를 판정했습니다. 그중 바로 앞 문장을 읽어야 이해되는 문장은 15개(13.6%)였고, 앞 문장까지 읽어도 이해되지 않는 문장은 없었습니다. 0.2.0 버전으로 같은 논문을 정리한 이전 예시(commit 930779c)는 이 비율이 30.2%(126문장 중 38문장)였습니다.
- 0.2.0 버전으로 같은 논문을 정리한 글과 이 글을 judge에게 순서를 바꿔 두 번 보여 줬고, judge는 두 번 모두 이 글을 골랐습니다. judge가 든 근거는 7토큰 프롬프트로 문제를 보여 주는 도입과, 수치가 무엇을 잰 값인지 문장 안에서 밝힌 점이었습니다.
- fidelity judge가 글의 주장 64개를 논문과 대조했고, 근거가 없거나 논문과 다른 주장은 찾지 못했습니다.
- style judge는 이 글에 J5(한국어 자연스러움) 1.5점, J8(과교정 없음) 1점을 줬습니다. judge는 "~해요"로 끝나는 짧은 문장이 길게 이어지고 "저자들은 ~봐요" 구조가 반복되는 점을 단조롭다고 지적했습니다.

## 자료와 라이선스

- 자료: Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica, "Efficient Memory Management for Large Language Model Serving with PagedAttention", SOSP 2023. arXiv:2309.06180, https://arxiv.org/abs/2309.06180
- 자료의 라이선스: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 두 글은 이 논문을 한국어로 요약하고 표, 수식, 예시를 옮긴 2차 저작물입니다. 두 글은 원문을 한국어로 옮기며 요약했고, 구성을 바꿨고, 글쓴이의 해석(표의 수치 비교, 한국어 서비스에 적용할 때의 조건)을 더했습니다.
