# PagedAttention: KV cache를 블록으로 나눠 LLM 서빙 처리량을 2~4배 올린 방법

최대 시퀀스 길이가 2048토큰인 모델에 "Four score and seven years ago our"라는 7토큰짜리 프롬프트가 들어왔다고 해 볼게요. 기존 LLM 서빙 시스템은 이 요청이 몇 토큰을 생성할지 모르기 때문에 KV cache를 저장할 연속 공간을 2048토큰만큼 미리 잡아 둬요. 요청이 세 토큰을 더 생성하고 끝나면 미리 잡은 슬롯 중 2038개는 한 번도 쓰이지 않아요.

쓰이지 않는 슬롯도 요청이 끝날 때까지는 다른 요청이 쓸 수 없어요. GPU 메모리에 함께 올릴 수 있는 요청 수가 줄면 배치 크기가 줄고 처리량도 떨어져요.

PagedAttention은 UC Berkeley 등의 연구진이 SOSP 2023 논문 "Efficient Memory Management for Large Language Model Serving with PagedAttention"에서 제안한 attention 알고리즘이에요. PagedAttention은 운영체제의 virtual memory와 paging처럼 KV cache를 고정 크기 블록으로 나눠 비연속 메모리에 저장해요. 같은 논문의 vLLM은 PagedAttention 위에 만든 LLM 서빙 시스템이에요.

이 글에서는 PagedAttention이 KV cache 낭비를 블록 하나 안으로 줄이고 블록을 시퀀스 사이에 공유해 처리량을 올리는 방식을 정리해요. vLLM은 같은 수준의 latency에서 FasterTransformer와 Orca보다 처리량을 2~4배 높였어요.

## KV cache 메모리는 어디서 새는가

LLM은 토큰을 하나씩 생성하고, 새 토큰을 만들 때마다 앞선 모든 토큰의 key 벡터와 value 벡터를 써요. 이 벡터들을 매번 다시 계산하지 않도록 저장해 둔 것이 KV cache예요.

OPT-13B에서 토큰 하나의 KV cache는 800KB예요. 이 값은 key와 value 2개, hidden state 크기 5120, layer 수 40, FP16 한 값의 2바이트를 곱해 나와요. OPT는 최대 2048토큰까지 생성하므로 요청 하나의 KV cache는 최대 1.6GB까지 커질 수 있어요.

40GB A100 한 장에서 13B 모델을 서빙하면 메모리의 약 65%인 26GB를 모델 가중치가 차지해요. KV cache에는 메모리의 30% 가까이가 쓰이고 activation은 나머지 소량을 써요. 가중치는 서빙 중에 바뀌지 않으므로 한 번에 배치할 수 있는 요청 수는 KV cache 관리 방식이 정해요.

GPU 연산 속도는 메모리 용량보다 빠르게 늘고 있어요. A100에서 H100으로 가면서 FLOPS는 2배 넘게 늘었지만 GPU 메모리는 최대 80GB 그대로예요. 저자들은 메모리가 점점 더 큰 병목이 될 것으로 봐요.

### 최대 길이만큼 미리 잡는 연속 할당

FasterTransformer와 Orca 같은 기존 서빙 시스템은 요청 하나의 KV cache를 연속 메모리에 저장해요. 대부분의 딥러닝 프레임워크가 텐서를 연속 메모리에 두도록 요구하거든요. 출력 길이는 미리 알 수 없으므로 요청마다 최대 시퀀스 길이만큼 청크를 할당해요.

앞으로 생성할 토큰을 위해 잡아 둔 예약(reserved) 슬롯은 결국 쓰이지만 요청이 끝날 때까지 다른 요청이 쓰지 못해요. 실제 시퀀스가 최대 길이보다 짧으면 남은 슬롯이 끝까지 쓰이지 않는 내부 단편화(internal fragmentation)가 생겨요. buddy allocator 같은 할당기가 요청마다 크기가 다른 청크를 잡으면 청크 사이에는 외부 단편화(external fragmentation)가 남아요.

vLLM 논문의 프로파일링에서 기존 시스템이 실제 토큰 상태를 저장하는 데 쓴 KV cache 메모리는 20.4~38.2%였어요. 아래 표는 Orca 세 버전의 평균 KV cache 메모리 사용 내역이에요.

| 시스템 | 토큰 상태 | 예약 | 내부 단편화 | 외부 단편화와 기타 |
|---|---|---|---|---|
| Orca (Max) | 20.4% | 13.3% | 57.3% | 8.9% |
| Orca (Pow2) | 26.8% | 17.9% | 13.6% | 41.6% |
| Orca (Oracle) | 38.2% | 25.2% | - | 36.6% |

Orca의 세 버전은 출력 공간을 얼마나 예약하는지만 달라요. Orca (Max)는 항상 최대 길이인 2048토큰을, Orca (Pow2)는 실제 출력 길이의 최대 2배를 예약하고, Orca (Oracle)는 실제 출력 길이를 미리 안다고 가정해요. 출력 길이를 미리 아는 Orca (Oracle)도 KV cache 메모리의 61.8%를 토큰 상태가 아닌 곳에 썼어요.

같은 실험에서 vLLM은 KV cache 메모리의 96.3%를 토큰 상태 저장에 썼어요.

### 시퀀스끼리 공유하지 못하는 KV cache

parallel sampling과 beam search는 요청 하나에서 출력 시퀀스를 여러 개 만들어요. 이 시퀀스들은 같은 프롬프트에서 출발하므로 KV cache 일부를 공유할 수 있어요. 기존 시스템은 시퀀스마다 KV cache를 별도 연속 공간에 저장하기 때문에 이 공유를 하지 못해요.

vLLM 실험에서 parallel sampling의 프롬프트 KV cache는 전체 KV cache 메모리의 12%를 차지했어요. beam search에서는 후보끼리 공유할 수 있는 부분이 더 크고, 공유 패턴이 디코딩 중에 바뀌어요.

## PagedAttention: KV cache를 고정 크기 블록으로 나누기

PagedAttention은 시퀀스의 KV cache를 KV 블록으로 나눠요. 블록 하나에는 블록 크기 B만큼의 토큰에 대한 key 벡터와 value 벡터가 들어가요. 한 시퀀스의 블록들은 물리 메모리에서 서로 떨어져 있어도 돼요.

운영체제의 virtual memory에 대응하면 블록은 페이지, 토큰은 바이트, 요청은 프로세스예요. 블록이 작고 필요할 때마다 할당되므로 내부 단편화가 줄어들어요. 모든 블록의 크기가 같으므로 외부 단편화는 생기지 않아요.

### 블록 단위로 attention 계산하기

j번째 key 블록을 $K_j$, value 블록을 $V_j$라고 하면 토큰 $i$의 attention은 블록 단위 계산으로 바뀌어요.

$$
A_{ij} = \frac{\exp(q_i^\top K_j / \sqrt{d})}{\sum_{t=1}^{\lceil i/B \rceil} \exp(q_i^\top K_t \mathbf{1} / \sqrt{d})}, \quad o_i = \sum_{j=1}^{\lceil i/B \rceil} V_j A_{ij}^\top
$$

$A_{ij}$는 j번째 KV 블록에 대한 attention score 행 벡터예요. PagedAttention 커널은 KV 블록을 하나씩 찾아 가져와 query 벡터 $q_i$와 블록의 key 벡터를 곱해 score를 구하고, 이 score를 같은 블록의 value 벡터와 곱해 출력 $o_i$를 만들어요. 예를 들어 query 토큰이 "forth"이면 커널은 "Four score and seven"이 담긴 블록의 key 벡터와 "forth"의 query 벡터를 곱해 그 블록의 score를 구해요.

Transformer의 key와 value 벡터는 층과 attention head마다 따로 있어요. 이 벡터를 한 블록에 모으는 설계와 층과 헤드마다 블록을 따로 두는 설계는 성능 차이가 없었고, vLLM은 구현이 쉬운 후자를 골랐어요.

### block table로 논리 블록과 물리 블록 잇기

vLLM의 KV cache manager는 요청의 KV cache를 논리 블록의 나열로 표현하고, 새 토큰이 생기면 논리 블록을 왼쪽부터 채워요. GPU worker의 block engine은 GPU DRAM에서 연속 청크를 잡아 물리 블록으로 나눠 둬요. block table은 요청마다 논리 블록이 어느 물리 블록에 있는지와 블록에 채워진 위치 수를 기록해요.

아래 표는 블록 크기가 4일 때 7토큰 프롬프트 "Four score and seven years ago our"를 처리하는 block table의 상태예요.

| 논리 블록 | 물리 블록 | 채워진 수 | 저장된 토큰 |
|---|---|---|---|
| 0 | 7 | 4 | Four score and seven |
| 1 | 1 | 3 → 4 | years ago our, fathers |
| 2 | 3 | 1 | brought |

1. 프롬프트 단계에서 vLLM은 최대 길이만큼 예약하지 않고 프롬프트에 필요한 논리 블록 0, 1만 물리 블록 7, 1에 매핑해요. 논리 블록 1의 남은 한 칸은 생성 단계에서 써요.
2. 첫 디코딩 단계에서 "fathers"의 KV cache가 논리 블록 1의 빈 칸에 들어가고, 채워진 수가 3에서 4로 바뀌어요.
3. 두 번째 디코딩 단계에서는 논리 블록 1이 가득 차 있으므로 vLLM이 논리 블록 2를 만들고 물리 블록 3을 새로 할당해요.

vLLM은 이전 블록이 모두 찬 뒤에만 새 물리 블록을 할당해요. 그래서 요청 하나의 메모리 낭비는 블록 하나 안으로 제한되죠. 요청이 끝나면 그 요청의 블록은 해제되어 다른 요청의 KV cache를 저장해요.

블록 크기를 1보다 크게 잡으면 커널이 더 많은 위치의 KV cache를 병렬로 처리해 하드웨어 활용률이 오르고 latency가 줄어드는데요. 반대로 블록이 클수록 단편화는 늘어나요.

vLLM 스케줄러는 반복마다 배치할 시퀀스를 고르고 새로 필요한 논리 블록에 물리 블록을 할당해요. 그다음 프롬프트 단계 요청의 전체 토큰과 생성 단계 요청의 최신 토큰을 한 시퀀스로 이어 모델에 넣어요.

### vLLM의 커널과 분산 실행

vLLM 엔진은 Python 8.5K줄과 C++/CUDA 2K줄로 되어 있어요. 스케줄러와 블록 매니저는 Python으로, PagedAttention 같은 핵심 연산은 CUDA 커널로 구현했어요. 프론트엔드는 FastAPI로 만들었고 OpenAI API 인터페이스를 확장해 요청마다 최대 시퀀스 길이와 beam width를 지정할 수 있어요.

블록 단위 메모리 접근은 기존 커널이 효율적으로 지원하지 않는 패턴이라 vLLM은 아래 커널을 따로 만들었어요.

- fused reshape and block write 커널은 새 KV cache를 블록으로 나누고 블록 읽기에 맞는 레이아웃으로 바꿔 block table 위치에 저장하는 과정을 커널 하나로 합쳐요.
- fused block read and attention 커널은 FasterTransformer의 attention 커널을 고쳐 block table을 따라 KV cache를 읽으면서 attention을 계산해요. coalesced memory access를 위해 블록마다 GPU warp 하나를 배정해요.
- fused block copy 커널은 copy-on-write가 일으키는 비연속 블록 복사를 cudaMemcpyAsync로 하나씩 호출하지 않고 커널 한 번 실행으로 묶어요.

모델이 GPU 한 장에 들어가지 않으면 vLLM은 Megatron-LM 방식의 tensor model parallelism으로 attention head를 GPU worker에 나눠요. 모든 worker가 같은 입력 토큰을 처리하므로 KV cache manager는 중앙 스케줄러에 하나만 있어요. worker는 같은 물리 블록 ID를 쓰되 자기 attention head의 KV cache만 저장해요.

스케줄러는 반복마다 입력 토큰 ID와 block table을 worker에 broadcast해요. 그래서 worker끼리는 메모리 관리를 위해 따로 동기화하지 않아요.

## 블록을 공유하는 디코딩

### parallel sampling과 copy-on-write

parallel sampling은 프롬프트 하나에서 출력을 여러 개 샘플링하는 방식이고, 코드 어시스턴트처럼 사용자가 후보 중 하나를 고르는 서비스에서 써요. 출력 두 개를 만드는 요청에서 두 시퀀스의 프롬프트 논리 블록은 같은 물리 블록을 가리켜요. vLLM은 물리 블록마다 reference count를 두고, 이 경우 프롬프트 물리 블록의 reference count는 2예요.

생성 단계에서 두 출력은 서로 다른 토큰을 샘플링하므로 KV cache를 따로 저장해야 해요. 첫 번째 샘플이 공유 중인 마지막 블록에 쓰려고 하면 vLLM은 그 물리 블록의 reference count가 1보다 큰 것을 확인하고 새 물리 블록을 할당해 내용을 복사한 뒤 reference count를 1로 줄여요. 두 번째 샘플이 쓸 때는 reference count가 이미 1이므로 원래 물리 블록에 바로 써요.

블록 단위 copy-on-write는 운영체제가 프로세스를 fork할 때 쓰는 copy-on-write와 같은 방식이에요. 이 방식에서 샘플들은 마지막 논리 블록을 뺀 프롬프트 KV cache를 함께 써요.

### beam search에서 바뀌는 공유 패턴

beam search에서는 프롬프트 블록과 함께 후보끼리 겹치는 생성 블록도 공유되고, 공유 패턴은 디코딩이 진행되면서 바뀌어요. 어떤 후보가 상위 k개에서 빠지면 그 후보의 논리 블록이 해제되고, reference count가 0이 된 물리 블록이 반납돼요. 새 후보는 살아남은 후보의 블록을 공유한 채 새 KV cache를 담을 블록만 새로 받아요.

기존 서빙 시스템은 beam 후보 사이에서 KV cache를 자주 복사해야 해요. vLLM에서는 새 토큰이 기존 공유 블록 안에 들어갈 때만 copy-on-write가 일어나고, 그때도 블록 하나만 복사해요.

### 공유 접두사와 섞인 디코딩

여러 요청이 같은 system prompt를 쓰는 서비스라면 서비스 제공자가 그 접두사의 KV cache를 미리 물리 블록에 저장해 둘 수 있어요. 사용자 요청은 자기 논리 블록을 이 물리 블록에 매핑하고 마지막 블록만 copy-on-write로 표시해요. 그러면 프롬프트 단계 계산은 사용자 입력 부분에만 실행돼요.

모델과 커널은 시퀀스마다 물리 블록 ID 목록만 받고 시퀀스 사이의 공유 패턴은 알 필요가 없어요. 그래서 vLLM은 디코딩 방식이 다른 요청을 한 배치에 함께 처리할 수 있어요.

vLLM은 이런 디코딩을 fork, append, free 세 메서드로 구현해요. parallel sampling은 입력 시퀀스를 fork해 출력 시퀀스를 여러 개 만들고, 반복마다 append로 토큰을 붙이고, 종료 조건을 만족한 시퀀스를 free로 지워요.

## GPU 블록이 바닥날 때의 선점과 복구

요청이 많아지고 출력이 길어지면 vLLM도 새 KV cache를 저장할 물리 블록이 모자랄 수 있어요. vLLM은 모든 요청을 FCFS(first-come-first-serve)로 처리하고, 선점이 필요하면 가장 늦게 들어온 요청부터 선점해요.

한 시퀀스의 블록은 함께 접근되므로 vLLM은 그 블록을 전부 내보내거나 하나도 내보내지 않는 all-or-nothing eviction을 써요. beam 후보처럼 요청 하나에 속한 시퀀스들은 메모리를 공유할 수 있어서 sequence group으로 묶이고, 항상 함께 선점되고 함께 다시 스케줄돼요.

내보낸 블록은 swapping이나 재계산(recomputation)으로 되살려요. swapping은 내보낸 블록을 CPU 메모리로 복사하고 CPU block allocator가 이 블록을 관리해요. 선점이 일어나면 vLLM은 선점된 시퀀스가 모두 끝날 때까지 새 요청을 받지 않아요. 이 규칙 덕분에 CPU로 옮기는 블록 수는 GPU의 전체 물리 블록 수를 넘지 않아요.

재계산은 선점된 시퀀스를 다시 스케줄할 때 KV cache를 새로 계산해요. 디코딩에서 생성한 토큰을 원래 프롬프트 뒤에 이어 새 프롬프트로 만들면 모든 위치의 KV cache를 프롬프트 단계 한 번으로 만들 수 있어요. 그래서 재계산 latency는 처음 생성할 때의 latency보다 크게 낮을 수 있어요.

블록 크기를 바꾼 실험에서 swapping은 블록이 작을 때 오버헤드가 컸어요. 작은 블록은 CPU와 GPU 사이에 작은 전송을 많이 만들어 실효 PCIe 대역폭을 떨어뜨려요. 재계산은 KV 블록을 쓰지 않으므로 오버헤드가 블록 크기와 관계없이 일정했어요.

블록이 작으면 재계산이, 크면 swapping이 더 효율적이에요. 원문은 블록이 큰 구간에서도 재계산 오버헤드가 "never higher than 20% of swapping's latency"라고 적었어요.

블록 크기 16~64에서는 두 방식의 end-to-end 성능이 비슷했어요.

## Orca, FasterTransformer와 비교한 실험

### 실험 설정

vLLM 평가 실험은 Google Cloud의 A2 인스턴스에서 NVIDIA A100으로 했어요. 모델은 OPT 13B, 66B, 175B와 LLaMA 13B를 썼고, 모델별 서버 구성은 아래와 같아요.

| 모델 크기 | 13B | 66B | 175B |
|---|---|---|---|
| GPU | A100 | 4×A100 | 8×A100-80GB |
| 전체 GPU 메모리 | 40GB | 160GB | 640GB |
| 파라미터 크기 | 26GB | 132GB | 346GB |
| KV cache용 메모리 | 12GB | 21GB | 264GB |
| 최대 KV cache 슬롯 수 | 15.7K | 9.7K | 60.1K |

13B 설정의 슬롯 수 15.7K는 KV cache용 메모리 12GB를 토큰당 800KB로 나눈 값과 맞아요. 66B 설정은 KV cache에 21GB를 쓰지만 슬롯은 9.7K개로 13B 설정보다 적어요.

워크로드는 ShareGPT와 Alpaca 데이터셋의 입력과 출력 길이로 합성했어요. ShareGPT는 사용자가 공유한 ChatGPT 대화 모음이고 Alpaca는 GPT-3.5로 만든 instruction 데이터셋이에요. ShareGPT의 평균 길이는 입력 161.31토큰, 출력 337.99토큰이고 Alpaca는 입력 19.31토큰, 출력 58.45토큰이에요.

두 데이터셋에 타임스탬프가 없어서 요청 도착 시간은 Poisson 분포로 만들었어요.

FasterTransformer는 자체 스케줄러가 없어서 dynamic batching 스케줄러를 붙이고 최대 배치 크기를 GPU 메모리가 허용하는 만큼 크게 잡았어요. Orca는 공개되지 않아 재구현한 버전을 썼고 buddy allocator를 쓴다고 가정했어요. Orca (Pow2)는 실제 출력 길이가 25이면 32칸을 예약하는 식이에요.

지표는 normalized latency예요. normalized latency는 요청마다 end-to-end latency를 출력 길이로 나눈 값의 평균이고, 요청률을 올려도 이 값이 낮게 유지되는 시스템이 처리량이 높은 시스템이에요. trace 길이는 대부분 1시간이고 OPT-175B만 비용 때문에 15분이에요.

### 기본 샘플링: 요청 하나에 출력 하나

요청률이 시스템 용량을 넘으면 큐가 계속 길어지고 latency가 급격히 올라요.

ShareGPT에서 vLLM은 비슷한 latency를 유지하면서 Orca (Oracle)보다 1.7~2.7배, Orca (Max)보다 2.7~8배 높은 요청률을 처리했어요. FasterTransformer와 비교하면 vLLM이 처리한 요청률은 최대 22배였어요.

OPT-13B에서 동시에 배치한 평균 요청 수는 아래와 같아요.

| 워크로드 | Orca (Max) | Orca (Pow2) | Orca (Oracle) | vLLM |
|---|---|---|---|---|
| ShareGPT, 2 req/s | 7.00 | 9.81 | 13.62 | 30.42 |
| Alpaca, 30 req/s | 7.00 | 43.24 | 72.75 | 132.44 |

ShareGPT 2 req/s에서 vLLM은 Orca (Oracle)보다 2.2배, Orca (Max)보다 4.3배 많은 요청을 동시에 처리했어요. Orca (Max)의 평균 배치 요청 수는 두 워크로드에서 모두 7.00개예요. 13B 설정의 슬롯 15.7K개를 요청당 예약량 2048로 나누면 7.7이므로 요청마다 2048토큰을 잡는 Orca (Max)는 요청을 7개까지만 올릴 수 있어요.

Alpaca에서도 경향은 같았지만 OPT-175B에서는 vLLM과 Orca (Oracle), Orca (Pow2)의 차이가 작았어요. OPT-175B 설정은 KV cache용 메모리가 264GB로 크고 Alpaca 시퀀스는 짧아서 Orca도 요청을 많이 배치할 수 있어요. 이 조건에서 시스템 성능은 compute-bound가 돼요.

### 공유가 있는 디코딩과 접두사 공유

OPT-13B와 Alpaca로 parallel sampling을 돌린 실험에서 샘플 수를 2, 4, 6으로 늘릴수록 vLLM의 Orca 대비 개선 폭이 커졌어요. beam search는 공유가 더 많아서 개선 폭이 더 컸어요. Orca (Oracle) 대비 개선은 기본 샘플링의 1.3배에서 beam width 6인 beam search의 2.3배로 늘었어요.

메모리 절약률은 공유로 아낀 블록 수를 공유하지 않았을 때의 전체 블록 수로 나눈 값이에요.

| 데이터셋 | parallel sampling | beam search |
|---|---|---|
| Alpaca | 6.1~9.8% | 37.6~55.2% |
| ShareGPT | 16.2~30.5% | 44.3~66.3% |

ShareGPT의 메모리 절약률이 Alpaca보다 높은 것은 ShareGPT 프롬프트가 평균 8.4배 길어 공유할 프롬프트 KV cache가 많기 때문일 수 있어요.

접두사 공유 실험은 다국어 모델인 LLaMA-13B로 WMT16 영어→독일어 번역을 했어요. 예시 1개를 담은 80토큰 접두사를 공유하면 vLLM의 처리량은 Orca (Oracle)의 1.67배였고, 예시 5개를 담은 341토큰 접두사를 공유하면 3.58배였어요.

### 챗봇 워크로드

챗봇 실험은 ShareGPT 대화 기록과 마지막 질문을 이어 프롬프트로 만들었어요. OPT-13B의 컨텍스트 길이 제한 때문에 프롬프트를 마지막 1024토큰으로 자르고 최대 1024토큰을 생성하게 했어요.

챗봇 워크로드에서 vLLM은 세 Orca 버전보다 2배 높은 요청률을 처리했어요.

ShareGPT에는 긴 대화가 많아 대부분 요청의 입력이 1024토큰이었어요. Orca는 buddy allocator 때문에 출력 길이 예측과 관계없이 출력용으로 1024토큰을 예약했고, 그래서 Orca 세 버전의 결과가 비슷했어요.

## 블록 크기 16과 커널 오버헤드

PagedAttention 커널은 block table 접근, 추가 분기, 가변 시퀀스 길이 처리 때문에 FasterTransformer 커널보다 attention 커널 latency가 20~26% 높았어요.

저자들은 이 오버헤드가 attention 연산자에만 생기고 Linear 같은 다른 연산자에는 영향이 없어서 작다고 봐요. end-to-end 실험에서 vLLM은 이 오버헤드를 안고도 FasterTransformer보다 최대 22배 높은 요청률을 처리했어요.

블록이 너무 작으면 KV cache를 읽고 처리할 때 GPU 병렬성을 다 쓰지 못해요. 블록이 너무 크면 내부 단편화가 늘고 블록을 공유할 확률이 줄어들어요.

고정 요청률에서 블록 크기를 바꾼 실험에서 ShareGPT trace는 블록 크기 16~128에서 가장 좋았어요. Alpaca trace는 16과 32에서 좋았고, 그보다 큰 블록에서는 시퀀스가 블록보다 짧아져 성능이 크게 떨어졌어요. Alpaca의 평균 입력과 출력을 더하면 77.76토큰이므로 블록 크기가 128이면 평균적인 요청 하나가 블록 하나도 다 채우지 못해요.

vLLM의 기본 블록 크기는 16이에요. 저자들은 블록 크기 16이 대부분의 워크로드에서 GPU를 효율적으로 쓸 만큼 크고 내부 단편화를 피할 만큼 작다고 봤어요.

## 이득이 커지는 워크로드와 줄어드는 워크로드

paging이 LLM 서빙의 KV cache에 맞는 이유는 출력 길이를 몰라 메모리를 동적으로 할당해야 하고 성능이 GPU 메모리 용량에 묶여 있기 때문이에요.

DNN 학습은 텐서 모양이 대개 정해져 있어 메모리 할당을 미리 최적화할 수 있어요. LLM이 아닌 DNN 서빙은 주로 compute-bound라서 메모리 효율이 성능으로 이어지지 않을 수 있어요. 이런 워크로드에서는 메모리 간접 참조와 비연속 블록의 오버헤드 때문에 vLLM의 기법이 오히려 성능을 떨어뜨릴 수 있어요.

LLM 서빙 안에서도 OPT-175B와 Alpaca 조합처럼 KV cache 메모리가 넉넉하고 시퀀스가 짧으면 vLLM과 Orca (Oracle)의 차이가 작았어요. 응답이 짧은 분류나 추출 위주 서비스를 큰 GPU 메모리로 돌린다면 PagedAttention으로 얻는 처리량 이득도 작을 수 있어요.

접두사 공유 실험에서 공유 접두사를 80토큰에서 341토큰으로 늘리자 vLLM의 Orca (Oracle) 대비 처리량은 1.67배에서 3.58배로 늘었어요. 긴 system prompt나 few-shot 예시를 모든 요청에 붙이는 서비스라면 접두사 공유의 효과가 이 실험에 가까울 수 있어요.

한국어 서비스에서 쓰는 토크나이저가 한 단어를 여러 토큰으로 나눈다면 같은 대화도 시퀀스가 길어져요. 그런 서비스의 시퀀스 길이 분포는 Alpaca보다 ShareGPT에 가까울 수 있어요. 그렇다면 블록 크기는 ShareGPT trace에서 성능이 가장 좋았던 16~128 구간을 기준으로 고를 수 있어요.

## 마치며

vLLM의 2~4배 처리량 개선은 KV cache 메모리가 배치 크기를 제한하는 memory-bound 서빙에서 잰 값이에요. 실험은 A100 GPU에서 OPT 13B~175B와 LLaMA-13B로 했고, 워크로드는 ShareGPT와 Alpaca의 길이 분포에 Poisson 도착 시간을 붙여 합성했어요. 비교 대상인 Orca는 공개 구현이 없어 재구현한 버전이에요. 챗봇 실험은 대화 라운드 사이에 KV cache를 저장하지 않았으므로 이전 대화의 KV cache를 재사용하는 멀티턴 서빙은 이 실험 범위 밖이에요.

## 참고자료

- [1] Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica, Efficient Memory Management for Large Language Model Serving with PagedAttention (2023). https://doi.org/10.1145/3600006.3613165
- [2] vLLM project, vLLM (2023). https://github.com/vllm-project/vllm
- [3] NVIDIA, FasterTransformer (2023). https://github.com/NVIDIA/FasterTransformer
- [4] Gyeong-In Yu, Joo Seong Jeong, Geon-Woo Kim, Soojeong Kim, Byung-Gon Chun, Orca: A Distributed Serving System for Transformer-Based Generative Models (2022). OSDI 22
- [5] ShareGPT Team, ShareGPT (2023). https://sharegpt.com/
- [6] Rohan Taori et al., Stanford Alpaca: An Instruction-following LLaMA model (2023). https://github.com/tatsu-lab/stanford_alpaca
