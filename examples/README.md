# 예시: PagedAttention 논문 정리

이 폴더의 두 글은 `/techblog`로 PagedAttention 논문을 정리한 결과입니다. `paged-attention.default.md`는 합니다체(Default)로 쓴 글이고, `paged-attention.casual.md`는 해요체(Casual)로 쓴 글입니다.

두 글은 0.4.0 버전 skill을 한 번 실행해서 나왔습니다. skill은 Casual로 요청받아도 합니다체 초안을 먼저 쓰고 점검합니다. 그다음 초안을 쓰지 않은 후처리 subagent가 초안을 다시 읽고 고치고, skill은 후처리를 마친 초안의 문장마다 문장 끝(종결부)만 해요체로 바꿔 Casual 글을 만듭니다. 그래서 두 글은 문장 수, 문장 순서, 수치가 같습니다. 두 글에서 사람이 고친 부분은 없습니다.

| 파일 | 어투 | 본문 글자 수(공백 제외) | 문장 수 | lint 결과 |
|---|---|---|---|---|
| [paged-attention.default.md](paged-attention.default.md) | Default(합니다체) | 9,177 | 161 | Gate 0, FAIL 0, WARN 0 |
| [paged-attention.casual.md](paged-attention.casual.md) | Casual(해요체) | 9,037 | 161 | Gate 0, FAIL 0, WARN 0 |

`tone_check.py paged-attention.default.md paged-attention.casual.md`로 두 글을 비교한 결과, 문장 161쌍 모두 문장 끝만 달라서 FAIL과 WARN이 0개였습니다.

## 생성 조건

- 실행한 명령은 `/techblog casual ./input.pdf -o article.md --keep-work`입니다.
- 모델은 Claude Opus 5.5(`--model opus --effort xhigh`)이고, Claude Code 버전은 2.1.289입니다.
- skill은 commit 9cc0db4 버전입니다. 0.4.0 최종 버전과는 후처리 subagent에게 PDF를 Read 도구로 읽으라고 적은 문장(commit 32d8e88)만 다릅니다.
- `paged-attention.default.md`는 `--keep-work`로 남긴 Default 초안(`article.draft.md`)이고 후처리를 마친 글입니다. `paged-attention.casual.md`는 같은 실행의 출력 파일(`article.md`)입니다.
- 이 글은 dogfooding iteration 12의 S1 케이스에서 나왔습니다. 평가 기록은 [dev/dogfood/REPORT.md](../dev/dogfood/REPORT.md)에 있습니다.

## 평가 결과

- 후처리: 후처리 subagent는 초안 161문장 중 3문장을 고쳤습니다. 같은 실행의 후처리 전 초안과 후처리를 마친 글을 judge에게 순서를 바꿔 두 번 보여 줬고, judge는 두 번 모두 후처리를 마친 글을 골랐습니다. judge가 든 근거는 "두 샘플 A1과 A2가"처럼 예시 대상을 먼저 소개한 수정과 "다른 모델 크기보다 작았습니다"처럼 비교 대상을 밝힌 수정이었습니다.
- 문장 완결성(J9): judge가 문단의 첫 문장, 수치가 든 문장, lint 점검 후보 문장 101개를 판정했습니다. 그중 바로 앞 문장을 읽어야 이해되는 문장은 20개였고, 앞 문장까지 읽어도 이해되지 않는 문장은 3개였습니다.
- 0.3.0 버전으로 같은 논문을 정리한 이전 예시와 이 글을 judge에게 순서를 바꿔 두 번 보여 줬고, 판정은 순서에 따라 갈렸습니다. 두 글은 서로 다른 실행에서 나와서 초안부터 다릅니다.
- fidelity judge가 글의 주장 61개를 논문과 대조했고, 근거가 없거나 논문과 다른 주장은 찾지 못했습니다.
- style judge는 두 번 채점해서 J5(한국어 자연스러움)에 1점과 2점, J8(과교정 없음)에 두 번 모두 1점을 줬습니다.

## 자료와 라이선스

- 자료: Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica, "Efficient Memory Management for Large Language Model Serving with PagedAttention", SOSP 2023. arXiv:2309.06180, https://arxiv.org/abs/2309.06180
- 자료의 라이선스: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 두 글은 이 논문을 한국어로 요약하고 표, 수식, 예시를 옮긴 2차 저작물입니다. 두 글은 원문을 한국어로 옮기며 요약했고, 구성을 바꿨고, 글쓴이의 해석(표의 수치 비교, 한국어 서비스에 적용할 때의 조건)을 더했습니다.
