# 예시: PagedAttention 논문 정리

`/techblog`로 같은 논문을 정리한 Default(합니다체) 글과 Casual(해요체) 글이다. 두 글은 한 번의 실행에서 나왔다. Casual 글은 Default 초안의 문장마다 종결부(마지막 1~2 어절)만 바꾼 결과라서 두 글의 문장 수, 순서, 수치가 같다. 사람이 고친 부분은 없다.

| 파일 | 어투 | 본문 글자 수(공백 제외) | 문장 | lint |
|---|---|---|---|---|
| [paged-attention.default.md](paged-attention.default.md) | Default(합니다체) | 9,984 | 192 | Gate 0, FAIL 0, WARN 0 |
| [paged-attention.casual.md](paged-attention.casual.md) | Casual(해요체) | 9,809 | 192 | Gate 0, FAIL 0, WARN 0 |

`tone_check.py paged-attention.default.md paged-attention.casual.md`: 문장 192쌍, FAIL 0, WARN 0

## 생성 조건

- 명령: `/techblog casual ./input.pdf -o article.md --keep-work`
- 모델: Claude Opus 5.5(`--model opus --effort xhigh`), Claude Code 2.1.289
- 스킬: commit 930779c
- `paged-attention.default.md`는 `--keep-work`로 남긴 Default 초안(`article.draft.md`)이고, `paged-attention.casual.md`는 같은 실행의 출력(`article.md`)이다. Casual로 요청해도 스킬은 Default 초안을 먼저 쓴다.
- dogfooding iteration 7의 S1 케이스다. judge 결과는 [dev/dogfood/REPORT.md](../dev/dogfood/REPORT.md)에 있다.

## 자료와 라이선스

- 자료: Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica, "Efficient Memory Management for Large Language Model Serving with PagedAttention", SOSP 2023. arXiv:2309.06180, https://arxiv.org/abs/2309.06180
- 자료의 라이선스: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- 두 글은 이 논문을 한국어로 요약하고 표, 수식, 예시를 옮긴 2차 저작물이다. 원문과 달라진 점: 한국어로 옮기며 요약했고, 구성을 바꿨고, 글쓴이의 해석(표의 수치 비교, 한국어 서비스에 적용할 때의 조건)을 더했다.
