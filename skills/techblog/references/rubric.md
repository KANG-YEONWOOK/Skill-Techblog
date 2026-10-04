# techblog 평가 rubric

techblog 스킬이 쓴 글을 점검하는 기준이다. 스킬의 점검 단계, dogfooding 평가, 사람 검토가 모두 이 문서를 쓴다.

- 버전: v1. 자동 측정 기준치는 토스·카카오·당근 사람 글 측정값으로 정했다(`scripts/thresholds.json`, 측정 과정은 저장소의 `dev/baseline/`).
- 항목 종류
  - **Gate (G)**: 위반 1건이면 불합격.
  - **자동 측정 (A, T)**: `scripts/lint_ko.py`가 세고 PASS / WARN / FAIL로 판정한다.
  - **참고 지표 (INFO)**: 값만 보고하고 판정에 넣지 않는다.
  - **판정 (J)**: 사람이나 judge model이 0~2점으로 매긴다.
- "AI 문체 패턴"은 영어권 연구에서 tell이라고 부르는 표현이다. 이 문서는 영어 목록을 옮기지 않고 한국어 실측 자료(KCI 초록, KatFishNet, im-not-ai, 블로그 측정)를 우선한다.

## 판정 방식

- 합격 조건: Gate 위반 0, 자동 측정 FAIL 0, WARN 3개 이하, 판정 항목 평균 1.6 이상이고 0점 없음.
- 자동 측정 기준치(사람 글 기준)
  - 많을수록 나쁜 지표: PASS ≤ 사람 p95, WARN ≤ max(p99, 사람 최댓값)에 여유(횟수 +1, 비율 ×1.2), 그 위는 FAIL.
  - 적을수록 나쁜 지표(문장 길이 변동계수, 긴 문장 비율): PASS ≥ 사람 p5, WARN ≥ min(p1, 최솟값)×0.8.
  - 드문 패턴(부정 대구): 사람 글 전체의 1,000자당 비율(pooled rate)로 글 길이에 맞춘 Poisson 상한(PASS q0.95, WARN q0.995).
  - fixed 표시 항목은 정책으로 정한 값이다(fact sheet에 없는 수치 0, "~되어지다" 0, 제목의 부정 대구 0 등).
- 기준치 검증: 기준치 계산에 쓰지 않은 사람 글 22편(holdout)에 같은 판정을 적용해 19편(86%)이 통과했다. 목표는 85% 이상이다.
- policy 표시 항목: 이 스킬의 출력에만 적용하는 규칙이다. 자료를 정리하는 글이라 경험담과 이모지를 쓰지 않고, 맞춤법 규정을 지키고, 어투를 섞지 않는다. 사람 글도 이 규칙을 어기는 경우가 있어서 사람 글 검증에서는 뺀다.
- 고칠 때 원칙
  - 기준치를 넘은 항목만 고친다. 기준치 안으로 들어오면 멈춘다. 빈도를 0으로 만드는 것이 목표가 아니다. Boggia(2026)는 사후 rewrite가 모든 장르에서 부정 대구를 0으로 만들어 사람 글과 다른 분포가 된다고 보고했다[12].
  - 걸린 표현을 같은 수사 동작의 다른 표현으로 바꾸지 않는다. "단순히 X가 아니라 Y입니다"를 "X를 넘어 Y입니다"로 바꾸는 것은 고친 것이 아니다. Y를 바로 쓴다.
  - 고친 뒤 다시 검사해서 다른 항목 수치가 늘지 않았는지 확인한다. im-not-ai 실험에서 rewrite 뒤 연결어미 쉼표, "결국", 부정 대구가 새로 늘었다[3].
  - 수치, 고유명사, 인용은 고치는 과정에서 바꾸지 않는다.

## 측정 단위와 범위

- 글자 수: 본문 산문(문단, 목록 항목)의 공백 제외 글자 수. 코드 블록, 표, 헤딩, 인용(blockquote), URL은 뺀다. 비율은 1,000자당으로 쓴다.
- 문장 길이: 공백 포함 글자 수.
- 따옴표 안 텍스트와 인라인 코드는 패턴 검사에서 뺀다. 자료의 표현을 그대로 인용하는 경우를 감점하지 않기 위해서다.
- 본문이 1,500자 미만이면 리듬·밀도 지표는 판정하지 않는다.

## 사람 글 측정에서 확인한 것

측정 대상: 토스·카카오·당근 기술 블로그 757편을 모아 기술 글이고 한쪽 어투가 90% 이상인 글만 골랐다. 기준치는 2022-11-30 이전 합니다체 글 57편과 2024-06-30 이전 해요체 글 31편에서 holdout 22편을 뺀 66편으로 정했다[20].

- 2025~2026년 글은 2022년 이전 글과 분포가 다르다. AI 문체 연구가 지목한 지표가 함께 높았다.
  - 부정 대구(문장 수): 합니다체 그룹 중앙값 4.0 대 1.0, p90 12.8 대 2.1
  - 연결어미 뒤 쉼표 비율: 중앙값 0.41 대 0.18
  - 지시어로 여는 문장(1,000자당): p90 1.61 대 0.74
  - 그래서 기준치는 2022년 이전 글로 잡고, 2025년 이후 글은 비교에만 쓴다.
- 스킬 없이 Claude Opus 5.5에게 "자료를 한국어 기술 블로그 글로 정리해 달라"고 한 결과 3편은 강조 문장, 과사용 어휘, Claude 번역 표현, 번역투가 사람 글 수준이었다. 사람 글 p90을 넘은 지표는 목록 비중(0.27~0.35, 사람 p90 0.25), 셋 묶음, bold, "라벨: 설명" 목록, 연결어미 뒤 쉼표(0.29~0.41, 사람 p90 0.33), 부정 대구였다. 이 지표들이 이 스킬이 가장 먼저 줄여야 할 대상이다.

## Gate

### 사람 글에서도 거의 나오지 않는 Gate

| ID | 내용 | 사람 글 위반 |
|---|---|---|
| G8 | "단순한 X를 넘어", "단순히 X를 넘어", "단순한 X 그 이상" | 0/88 |
| G9 | 내용 없는 상투 도입·마무리: "오늘날 ~는 빠르게 변화하고 있습니다", "~의 시대가 도래했습니다", "앞으로가 더 기대됩니다", "무궁무진한 가능성", 짧은 "물론 과제도 남아 있습니다" | 1/88 |

- G8 근거: Lee(2026)의 KCI 초록 398,296건 분석에서 "단순한 X를 넘어"는 2019년 0.12%에서 2026년 4.93%로 60.8배 늘어 증가 폭 1위였다[1]. im-not-ai 실측에서 사람 글 60편에는 0회, AI 글 12편에는 12회 나왔다[3].
- G9 근거: im-not-ai에서 첫 문장에 시점이 있는 비율은 사람 33%, AI 10%였고, 내용 없는 과제 문장은 사람 0회 대 AI 8회, 글 후반부 "향후/앞으로" 문장은 0회 대 12회였다[3]. digitalmarketer 분석에서 결론 헤더는 참여 지표와 가장 강한 음의 상관(r ≈ −0.118)을 보였다[5].

### 정책 Gate (policy)

| ID | 내용 | 이유 | 사람 글 사용 |
|---|---|---|---|
| G1 | 자료에 없는 수치·고유명사·인용·주장·출처 | 자료를 정리하는 글이다. A15로 수치를 자동 대조하고 나머지는 원문과 대조한다. | - |
| G2 | 겪지 않은 경험: "직접 써 보니", 근거 없는 구체 수치, "~더라고요", "~네요" | 화자는 자료를 읽은 사람이다. 1인칭 경험은 지어낸 내용이 된다. | 8/88 |
| G3 | 챗봇 응답 흔적: "궁금한 점이 있으면", "물론입니다", "요청하신 글", "원하시면", placeholder, AI 자기 언급, 자료 메타 언급("제공된 자료에 따르면", "주어진 글을 바탕으로") | 독자가 아니라 요청자에게 하는 말이다. 자료는 제목과 저자로 부른다. | 1/88 |
| G4 | 어투 혼용, Casual 금지 어미(~더라고요, ~네요, ~잖아요, ~답니다) | Default는 합니다체, Casual은 순수 해요체로 정했다. Default의 "~할까요?"와 인용문은 허용. | 71/88 |
| G5 | Casual이 같은 실행의 Default 초안과 종결부 외에 다름 | 어투만 바꾼다는 요구사항. `scripts/tone_check.py`로 확인. | - |
| G6 | 본문의 이모지, 세미콜론, 문장 안 em dash(양쪽이 한글인 —) | 라벨·소제목·참고문헌 구분자의 em dash는 허용. | 이모지 19/88, em dash 4/88, 세미콜론 1/88 |
| G7 | 문장 첫머리 그리고·그러나·그런데·그러므로·하지만·그래서·따라서 바로 뒤 쉼표 | 한글 맞춤법 문장 부호 규정의 원칙[7]. LLM은 영어 쉼표 관습을 한국어에 옮긴다(KatFishNet)[2]. | 23/88 |

- G2 근거: Jakesch et al.(2023)에서 사람은 1인칭 대명사와 가족 이야기를 사람 글의 증거로 여겼고, 이 단서를 넣은 AI 글은 실제 사람 글보다 더 사람 같다고 판정됐다(65.7% vs 51.7%)[17]. 이 단서를 지어내면 독자를 속이게 된다. Graphite(2026)는 Claude가 "twenty minutes", "a handful" 같은 구체 시간·수량 표현을 늘려 쓴다고 보고했다[8].
- G3 근거: Wikipedia Signs of AI writing의 collaborative communication, placeholder 항목[11]. Sun et al.(2025)에서 Claude 응답을 가르는 특징 표현이 "according to", "the text", "based on", "appears to"였다[14].
- G6 근거: Wikipedia는 emoji formatting을, 오마이뉴스는 쉼표 자리의 줄표 남발을 AI 글의 특징으로 든다[6][11]. Arena 분석에서 Opus 5는 세미콜론을 1,000단어당 6.10개 썼다[21].

## 자동 측정 (판정에 넣는 지표)

기준치는 `scripts/thresholds.json`이 우선한다. 아래 기준은 v1 값이다.

| ID | 지표 | v1 기준 | 사람 글(p50 / p90) | 근거 |
|---|---|---|---|---|
| A1.np | 부정 대구 문장 수: "X가 아니라 Y", "X라기보다", "X에 그치지 않고", "X를 넘어", "더 이상 X가 아닌", 문장을 나눈 "X가 아닙니다. Y입니다." | pooled 0.245회/1,000자의 Poisson 상한(6,000자 글이면 PASS ≤4) | 1 / 2 | [1][3][8][12][19] |
| A1.np_simple | "단순히/단순한 X가 아니라" | 글당 1회 | - | [1][3] |
| A1.np_title | 제목의 부정 대구 | 0 | - | |
| A1.np_same_para | 부정 대구가 2개 이상인 문단 | PASS 0, WARN 2 | 0 / 0 | [12] |
| A2.comma_per_sentence | 문장당 쉼표 | PASS ≤0.88 | 0.45 / 0.78 | [2][3] |
| A2.connective_comma_ratio | 연결어미(~고, ~며, ~지만, ~는데, ~면서, ~어서, ~니까, ~면) 뒤 쉼표 비율 | PASS ≤0.34 | 0.19 / 0.33 | [2][4] |
| A3.salience | 강조·평가 문장: "중요한 것은", "핵심은", "~이 중요합니다", "주목할 점은", "왜 ~가 중요할까요", "~점이 흥미롭습니다", "결과는 ~ 인상적입니다", "진짜 강점은" | PASS ≤2, WARN ≤3 | 0 / 1 | [3][8][9] |
| A4.para_end | 문단 끝 요약·교훈 문장("결국 ~", "이처럼 ~", "~를 보여줍니다") | PASS ≤3 | 0 / 2 | [3][6] |
| A4.obligation_end | 문단 끝 당위문("~해야 합니다") | PASS ≤2 | 0 / 1 | [3] |
| A4.gyeolguk | "결국" | PASS ≤2 | 0 / 1 | [3] |
| A4.summary_opener | "결론적으로", "요약하자면", "종합하면"으로 여는 문장 | PASS ≤1 | 0 / 0 | [5][10] |
| A5.style_words_per_1k | 과사용 어휘: 시사하다, 구조적, 체계적, 통합적, 다층적, 핵심적, 실질적, 전략적, 혁신적, 획기적, 원활, 기능하다, 규명하다, 메커니즘, 기제 | PASS ≤0.36/1,000자 | 0 / 0.25 | [1][3][5] |
| A5.word_max | 과사용 어휘 단어별 최다 횟수 | PASS ≤2, WARN ≤4 | 0 / 1 | |
| A6.calque | Claude 번역 표현과 상투 은유: 떠받치다, 조용히, "두 축으로", "세 갈래로", "봐야 하는 자리", 여정, 지평, 청사진, 발판, 토대, 초석, 퍼즐 조각, 게임 체인저 | PASS ≤1 | 0 / 1 | [3][5][16] |
| A7.hedge_stack | 추정 중첩: "~할 수 있을 것으로 보입니다", "~일 가능성이 있을 수 있습니다" | PASS ≤1 | 0 / 0 | [14][21] |
| A7.hedge_boimnida | "~것으로 보입니다" | PASS 0, WARN ≤2 | 0 / 0 | [14] |
| A8.sent_len_mean | 평균 문장 길이(공백 포함) | PASS 46~84자 | 62 / 82 | [10][15] |
| A8.sent_len_cv | 문장 길이 변동계수 | PASS ≥0.37 | 0.48 / 0.61 | [10][15] |
| A8.long_ratio | 80자 이상 문장 비율 | PASS ≥0.065 | 0.26 / 0.49 | [3][15] |
| A8.ending_run4 | 같은 종결(예: ~했습니다)이 4문장 이상 이어진 횟수 | PASS ≤6, WARN ≤10 | 2 / 5 | dogfooding |
| A8.ending_top_share | 가장 많은 종결(예: ~해요)이 서술 문장에서 차지하는 비율 | Default PASS ≤0.60, Casual PASS ≤0.52 | Default 0.42 / 0.56, Casual 0.37 / 0.51 | dogfooding |
| A9.bold_per_1k | bold 개수(1,000자당, 토스 제외) | PASS ≤4.62 | 0.95 / 3.23 | [9][10][11][14] |
| A9.list_ratio | 목록 비중(본문 글자 중 목록 항목) | PASS ≤0.305 | 0.09 / 0.25 | [10][14] |
| A9.label_list_ratio | "라벨: 설명" 형태 목록 비율 | PASS ≤0.495 | 0 / 0.31 | [9][11] |
| A10.triad_per_1k | 셋 묶음 나열(1,000자당) | PASS ≤2.21 | 0.83 / 1.90 | [5][6][9][16] |
| A12.progressive_per_1k | "~되고 있다", "~지고 있다"(1,000자당) | PASS ≤0.89 | 0 / 0.66 | [3] |
| A13.demonstrative_start_per_1k | "이는", "이를 통해", "이러한", "이처럼"으로 여는 문장(1,000자당) | PASS ≤0.93 | 0.23 / 0.75 | [1][15] |
| A14.translationese_per_1k | 번역투: "그것은", "~에 의해", "가장 ~한 ~ 중 하나", "중요한 역할을 하다", 속성의 "~를 가지고 있다" | PASS ≤0.46 | 0 / 0.31 | [1][3] |
| A14.doeeojida | 이중 피동 "~되어지다" | 0 | - | [3] |
| A15.unknown_numbers | 본문 수치 중 fact sheet(`<이름>.facts.md`)에 없는 값 | 0 | - | G1 |
| A16.source_subject_share | "저자들은", "논문은"으로 여는 문장 비율(policy) | PASS ≤0.10, WARN ≤0.15 | - | dogfooding |
| T.kkayo_ratio | "~할까요?" 질문 비율 | PASS ≤0.037 | 0 / 0.03 | |
| T.jyo_ratio, T.geudeun_ratio, T.neundeyo_ratio | Casual의 ~죠, ~거든요, ~는데요 비율(policy) | ~죠·~거든요 PASS ≤0.05, ~는데요 PASS ≤0.04 | 해요체 글 ~죠 3.4%, ~는데요 3.4%, ~거든요 0.2% | tone.md |
| INFO.closing_wish | 마무리 인사("도움이 되었으면 합니다", policy) | 글당 1회 | - | |

근거 메모
- A1: im-not-ai에서 1,000자당 AI 5.8회, 사람 0.6회(9.2배)로 모델과 과제에 상관없이 유지된 유일한 신호였다[3]. Graphite(2026)에서 Opus 5.5는 "rather than simply"를 사람의 32배, "is more than a _ it"를 98배 썼다[8]. The Conversation은 독자가 부정된 개념을 먼저 처리한다는 인지심리학 연구를 근거로 든다[19].
- A2: KatFishNet에서 쉼표가 있는 문장은 사람 에세이 26.3%, LLM 61.0%였고, 연결어미 뒤 쉼표는 4.1%와 19.8%였다. 쉼표 feature만으로 AUC 94.88을 얻었다[2].
- A3: Graphite(2026)에서 Opus 5.5는 "this matters"를 사람의 116배, "why _ matters"를 92배 썼다[8]. Arize는 salience flag가 Opus 5.5 출력의 가장 큰 지적 묶음이라고 보고했다[9].
- A5: Lee(2026)에서 기대치 대비 시사하다 4.0배, 구조적 6.0배, 기능하다 7.0배, 통합적 5.7배, 다층적 6.1배였다[1].
- A6: digitalmarketer의 GitHub PR 467,387건 분석에서 load-bearing은 19.6배, quietly는 30.1배였고, Claude 한국어 글에서 "떠받치고 있습니다", "조용히 삼켜지고" 같은 직역이 관찰됐다[5].
- A8: Muñoz-Ortiz et al.(2024)에서 41단어 이상 문장은 사람 12.0%, LLM 4.1~5.5%였다[15]. Pangram에서 Opus 5.5의 문장 길이 변동계수는 0.475로 Opus 5보다 11% 줄었다[10]. 같은 종결 반복(A8.ending_run4)은 dogfooding에서 추가했다. 스킬이 Casual로 바꾼 글에서 "~해요/~했어요"가 이어지는 구간이 8~9곳 나왔고, pairwise judge가 이 리듬을 사람 글보다 기계적이라고 지적했다.
- A8.ending_top_share: dogfooding iteration 4에서 style judge가 세 글 모두 "어미와 호흡이 균일하다"고 지적했다. Casual 글은 "~해요" 현재형이 서술 문장의 47~53%로 사람 해요체 글의 p90~p95(0.51~0.52)에 걸려 있었다. 동작을 설명하는 "~합니다/~됩니다"가 많은 초안이 변환되며 한 종결로 모였기 때문이다.
- A16: dogfooding iteration 2에서 "자료를 주어로 쓴다"는 규칙 때문에 "저자들은 ~"으로 여는 문장이 18%(160문장 중 29개)까지 늘었고, pairwise judge가 이 반복을 보고서 같은 리듬이라고 지적했다. 스킬 없는 Claude 출력은 2~7%였다. 사실은 기술·결과를 주어로 쓰고 "저자들은"은 주장·추정을 옮길 때만 쓴다.
- A9, A10: Arize에서 Opus 5.5의 bold lead-in bullet은 2.5배, 세 항목 목록은 35% 늘었고[9], Pangram에서 bullet은 85%, 번호 목록은 111% 늘었다[10]. 사람 글도 bold와 목록을 쓰므로 0이 목표가 아니다.

## 참고 지표 (INFO)

값만 보고하고 판정에 넣지 않는다. 사람 글에서 글쓴이마다 차이가 크고, 스킬 없는 Claude 출력과 사람 글을 가르지 못했다.

- 헤딩 밀도(사람 p50 2.2개/1,000자), 콜론 헤딩 비율, 문단당 문장 수, 한 문장 문단 비율
- 본문 질문 수, 질문형 헤딩 비율
- 첫 문단의 부정 대구, "뿐만 아니라", 추상 정책 동사(강화·확대·개선·구축, 기술 글에서는 문자 그대로 쓰는 경우가 많다), 쉼표가 있는 문장 비율
- 문장 첫 부사 뒤 쉼표("즉,", "특히,": 사람 글에도 흔하다), 1인칭 팀 화자 "저희"(자료가 그 팀의 글이 아니면 G2 확인)

## 판정 (J, 0~2점)

judge는 항목마다 점수와 근거 문장(본문 그대로 인용)을 적는다. 인용이 본문에 없으면 그 근거는 버린다.

| ID | 항목 | 2점 | 1점 | 0점 |
|---|---|---|---|---|
| J1 | coverage | 자료의 문제, 방법, 핵심 결과, 한계가 모두 있다 | 하나가 빠졌다 | 둘 이상 빠졌거나 핵심 결과가 없다 |
| J2 | 구체성 | 주장마다 자료의 수치, 이름, 동작 원리가 붙어 있다 | 평가어만 있는 문장이 1~2개 | 3개 이상 |
| J3 | deletion test | 지워도 정보(사실, 수치, 동작 원리, 할 일)가 줄지 않는 문장이 없다 | 1~2개 | 3개 이상 |
| J4 | 구조 | 제목이 내용을 특정하고, 도입이 독자 상황이나 자료 맥락에서 시작하고, 마무리가 구체 사실이나 자료의 열린 질문으로 끝나고, 참고자료가 있다 | 한 가지가 어긋난다 | 두 가지 이상 |
| J5 | 한국어 자연스러움 | 한국 개발자가 쓴 기술 블로그처럼 읽히고 용어 표기 규칙을 지킨다 | 번역투나 어색한 표현이 1~2곳 | 3곳 이상 |
| J6 | 어투 품질 | Default는 공문체가 아닌 합니다체, Casual은 정중한 해요체이고 허용 변형 비율 안이다 | 어색한 종결이 1~2곳 | 3곳 이상이거나 반말·과한 구어 |
| J7 | AI처럼 읽히는 문장 | 1,000자당 개수가 같은 묶음의 사람 글 대조군 p75 이하 | p75 초과, 최댓값 이하 | 사람 글 최댓값 초과 |
| J8 | 과교정 없음 | 자연스러운 대조, 단서("다만", "정확히는"), 괄호 보충, 긴 문장이 남아 있다 | 문장이 다소 단조롭다 | 패턴을 지우느라 내용이나 흐름이 손상됐다 |

- J3 deletion test는 Arize가 쓴 방식이다. "이 구절을 지웠을 때 글이 정보를 잃는가"를 묻는 기준을 넣자 judge precision이 약 40%에서 30건 중 26건으로 올랐다[9].
- J4 구조의 세부 기준은 `style-guide.md`를 따른다.
- J5 용어 표기: 한글 표기가 굳어진 외래어(서버, 캐시, 쿠버네티스)는 한글, 그 외 기술 용어(race condition, connection pool, latency)는 영어 원문, 번역어(경쟁 상태, 연결 풀)는 쓰지 않고, "한국어(English)" 병기는 첫 등장 1회.
- J7 대조군: 같은 judge 묶음에 사람이 쓴 테크 블로그 글을 섞고, 어떤 글이 사람 글인지 judge에게 알리지 않는다.
- J8 근거: Boggia(2026)에서 한 줄 지시로 Sonnet과 Opus의 부정 대구가 0이 됐고 사후 rewrite는 모든 장르에서 0을 만들었다[12]. im-not-ai에서 괄호는 사람 1,000문장당 10.6개, AI 1.2개였다[3].

## 감점하지 않는 표현

사람 글에서 더 자주 나오거나 블로그 관례인 표현이다. 이 표현을 지우는 것은 과교정이다.

- "~를 통해", "~것이다", "~에 대해", "~을 위해": im-not-ai에서 사람이 AI보다 2~3배 더 썼다[3].
- "다만", "사실", "정확히는", "엄밀히 말하면": Boggia(2026)에서 모델은 사람보다 자기 수정과 단서 표현을 덜 썼다[12].
- 살펴보다, 알아보다, 소개하다, 많다, 보다: Lee(2026)에서 LLM 시기에 줄어든 평이한 동사다(알아보다 0.24배, 살펴보다 0.42배)[1].
- "즉,", "특히,", "예를 들어,"
- 도입부의 "이번 글에서는 ~를 정리합니다" 1회, "마치며" 섹션 1개, "참고자료" 섹션
- 라벨, 소제목, 참고문헌의 em dash
- 사람 수준의 bold, 목록, 셋 묶음, 섹션을 여는 질문

## 근거 자료

1. Lee (2026), An LLM-Associated Register Shift in Korean Journal Abstracts. https://arxiv.org/abs/2609.07447
2. Park et al. (2025), KatFishNet: Detecting LLM-Generated Korean Text through Linguistic Feature Analysis. https://arxiv.org/abs/2503.00032
3. im-not-ai, 한국어 AI 문체 분류와 사람/AI 실측. https://github.com/epoko77-ai/im-not-ai
4. Pebblous (2026), Repairing AI-Written Korean. https://blog.pebblous.ai/report/korean-ai-humanizer-teardown-2026-08/en/
5. 디지털마케터, 클로드와 챗GPT 말투가 티 나는 이유. https://www.digitalmarketer.co.kr/insights/claude-load-bearing-vocabulary-github-pr
6. 오마이뉴스, 챗GPT에게 맡긴 글은 명백하게 티가 난다. https://www.ohmynews.com/NWS_Web/View/at_pg.aspx?CNTN_CD=A0003264627
7. 국립국어원, 한글 맞춤법 부록 문장 부호(쉼표). https://www.korean.go.kr/nkview/nknews/200011/28_3.htm
8. Graphite (2026), AI Tells, AI Tells: Opus 5.5 Update. https://graphite.io/five-percent/research/ai-tells , https://graphite.io/five-percent/research/ai-tells-opus-5-5-update
9. Arize (2026), Anthropic says it fixed Claude's writing. https://arize.com/blog/anthropic-says-it-fixed-claudes-writing/
10. Pangram (2026), Can Pangram detect Opus 5.5. https://www.pangram.com/blog/can-pangram-detect-opus-5-5
11. Wikipedia, Signs of AI writing / WikiProject AI Cleanup. https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing , https://en.wikipedia.org/wiki/Wikipedia:WikiProject_AI_Cleanup/Guide_and_resources
12. Boggia (2026), Artificial Epanorthosis. https://arxiv.org/abs/2607.21498
13. Paech et al. (2025), Antislop. https://arxiv.org/abs/2510.15061
14. Sun et al. (2025), Idiosyncrasies in Large Language Models, ICML. https://proceedings.mlr.press/v267/sun25z.html
15. Muñoz-Ortiz, Gómez-Rodríguez, Vilares (2024), Contrasting Linguistic Patterns in Human and LLM-Generated News Text. https://arxiv.org/abs/2308.09067
16. Kriss (2025), Why Does A.I. Write Like … That?, The New York Times Magazine. https://longreads.com/2025/12/04/why-does-a-i-write-like-that/
17. Jakesch, Hancock, Naaman (2023), Human heuristics for AI-generated language are flawed, PNAS. https://www.pnas.org/doi/10.1073/pnas.2208839120
18. Reinhart et al. (2025), Do LLMs write like humans? Variation in grammatical and rhetorical styles, PNAS. https://www.pnas.org/doi/10.1073/pnas.2422455122
19. The Conversation, Slanguage: why AI's stylistic negation "it's not X, it's Y" is both annoying and doesn't work. https://theconversation.com/slanguage-why-ais-stylistic-negation-its-not-x-its-y-is-both-annoying-and-doesnt-work-278967
20. 토스·카카오·당근 기술 블로그 측정. 측정 도구와 결과는 저장소의 `dev/baseline/`(URL 목록 `urls.json`, 측정값 `stats.json`, 보고서 `README.md`).
21. Aixploria (2026), Arena 분석 요약: Opus 5.5의 em dash, 세미콜론, hedging 변화. 표본 크기와 통계적 유의성은 공개되지 않았다. https://www.aixploria.com/en/ai-radar/95-percent-fewer-em-dashes-claude-opus-5-5-learns-to-hide/
