# PagedAttention: KV cache를 블록으로 나눠 LLM 서빙 처리량을 올리는 방법

LLM 서빙 시스템에 최대 길이 2048토큰, 프롬프트 7토큰인 요청이 들어왔다고 해 볼게요. 기존 서빙 시스템은 이 요청의 KV cache를 담을 2048칸짜리 연속 메모리를 처음부터 잡아 둬요.

논문의 예에서 이 요청이 끝날 때까지 한 번도 쓰이지 않는 칸은 2038개예요. 요청이 살아 있는 동안에는 다른 요청도 이 공간을 쓰지 못해요.

UC Berkeley 등의 연구진이 SOSP 2023에서 발표한 「Efficient Memory Management for Large Language Model Serving with PagedAttention」은 이 낭비를 운영체제의 paging 기법으로 줄여요. KV cache를 고정 크기 블록으로 나눠 비연속 메모리에 두는 attention 알고리즘 PagedAttention과 그 위에 만든 서빙 엔진 vLLM이 이 논문의 결과물이에요. 이 글에서는 PagedAttention이 KV cache를 나누고 공유하는 방식과 그 효과를 정리해요.

vLLM에서 KV cache 메모리 중 실제 토큰 상태가 차지한 비율은 96.3%로 기존 시스템의 20.4~38.2%보다 높았어요. 처리량은 같은 수준의 latency를 유지하면서 FasterTransformer, Orca의 2~4배였어요.

## KV cache 메모리는 어디서 낭비될까

### 토큰 하나에 800KB

LLM은 토큰을 하나씩 생성하고 새 토큰을 만들 때마다 앞선 모든 토큰의 key, value 벡터를 써요. 이 벡터를 매번 다시 계산하지 않도록 저장해 둔 것이 KV cache예요.

생성 단계는 iteration마다 토큰 하나만 입력으로 받아 matrix-vector 곱을 하므로 GPU 연산 능력을 다 쓰지 못하는 memory-bound 작업이에요. 처리량을 올리려면 여러 요청을 batch로 묶어야 해요. 이때 한 batch에 넣을 수 있는 요청 수는 KV cache에 쓸 GPU 메모리가 정해요.

OPT-13B에서 토큰 하나의 KV cache는 2(key와 value) × 5120(hidden state 크기) × 40(layer 수) × 2(FP16의 바이트 수)로 800KB예요. OPT는 최대 2048토큰까지 생성하므로 요청 하나의 KV cache는 최대 1.6GB까지 커질 수 있어요.

13B 모델을 40GB A100 한 장에 올리면 가중치가 메모리의 약 65%(26GB)를 차지하고 KV cache가 30% 가까이를 써요. 가중치는 서빙 내내 그대로이고 activation은 적은 양만 쓰므로 KV cache 관리 방식이 최대 batch 크기를 정해요.

### 최대 길이만큼 미리 잡는 할당

FasterTransformer, Orca 같은 기존 시스템은 요청 하나의 KV cache를 연속된 텐서 하나로 저장해요. 대부분의 딥러닝 프레임워크 연산자가 텐서를 연속 메모리에 두도록 요구하거든요.

출력 길이는 미리 알 수 없으므로 이 시스템들은 실제 입력·출력 길이와 관계없이 요청이 가질 수 있는 최대 길이만큼 chunk를 정적으로 할당해요.

아직 생성하지 않은 토큰을 위해 잡아 둔 예약(reserved) 슬롯은 결국 쓰이지만 요청이 끝날 때까지 다른 요청에 내줄 수 없어요. 최대 길이에 맞춰 넉넉히 잡았지만 끝내 쓰이지 않는 부분은 내부 단편화(internal fragmentation)예요. 그 크기는 요청이 끝나야 알 수 있어요.

buddy allocator 같은 메모리 할당기가 요청마다 크기가 다른 chunk를 잡으면서 그 사이에 남는 틈은 외부 단편화(external fragmentation)예요. compaction으로 틈을 메우는 방법도 있지만 KV cache가 워낙 커서 성능에 민감한 서빙 시스템에서는 현실적이지 않아요.

메모리 공유도 막혀요. parallel sampling이나 beam search처럼 요청 하나가 출력 여러 개를 만들 때는 시퀀스들이 같은 프롬프트의 KV cache를 함께 쓸 수 있어요. 시퀀스마다 별도의 연속 공간에 KV cache를 두는 기존 방식에서는 이 공유가 불가능해요.

### 실제 토큰 상태가 차지하는 메모리

논문은 Orca를 출력 공간을 얼마나 넉넉히 잡느냐에 따라 세 가지로 구현해 비교했어요.

- Orca (Max)는 항상 모델의 최대 길이인 2048토큰까지 잡아요.
- Orca (Pow2)는 최대 2배까지 넉넉히 잡아요. 실제 출력이 25토큰이면 32칸을 잡는 식이에요.
- Orca (Oracle)은 실제 출력 길이를 미리 안다고 가정해요. 실제로는 만들 수 없는 상한 성능이에요.

아래 표(논문 그림 2)는 §6.2 실험 동안 KV cache 메모리가 어디에 쓰였는지 평균한 값이에요.

| 시스템 | 토큰 상태 | 예약 | 내부 단편화 | 외부 단편화·기타 |
|---|---|---|---|---|
| Orca (Max) | 20.4% | 13.3% | 57.3% | 8.9% |
| Orca (Pow2) | 26.8% | 17.9% | 13.6% | 41.6% |
| Orca (Oracle) | 38.2% | 25.2% | - | 36.6% |
| vLLM | 96.3% | - | - | - |

Orca (Max)는 메모리의 57.3%를 내부 단편화로 잃어요. 논문의 두 워크로드 중 긴 쪽인 ShareGPT도 평균 입력과 출력을 더하면 500토큰 정도라 2048토큰보다 훨씬 짧아요.

Orca (Oracle)은 출력 길이를 정확히 아는데도 토큰 상태 비율이 38.2%에 그쳤어요. 내부 단편화는 없어졌지만 예약 25.2%와 외부 단편화·기타 36.6%를 더한 61.8%가 토큰 상태 밖에 쓰였어요.

## 블록과 block table로 KV cache 관리하기

PagedAttention은 시퀀스마다 KV cache를 KV 블록으로 나눠요. 블록 하나에는 정해진 개수(블록 크기 B)의 토큰에 대한 key, value 벡터가 들어가고 블록끼리는 물리 메모리에서 붙어 있지 않아도 돼요.

논문은 이 구조를 OS의 virtual memory에 빗대 "블록은 페이지, 토큰은 바이트, 요청은 프로세스로 볼 수 있다"고 설명해요. 블록을 작게 잡고 필요할 때만 할당하므로 내부 단편화가 줄어들어요. 모든 블록의 크기가 같으므로 외부 단편화는 생기지 않아요.

### 블록 단위로 계산하는 attention

j번째 key 블록을 $K_j = (k_{(j-1)B+1}, \ldots, k_{jB})$, value 블록을 $V_j$로 두면 attention 계산을 블록 단위로 다시 쓸 수 있어요.

$$
A_{ij} = \frac{\exp(q_i^\top K_j / \sqrt{d})}{\sum_{t=1}^{\lceil i/B \rceil} \exp(q_i^\top K_t \mathbf{1} / \sqrt{d})}, \quad o_i = \sum_{j=1}^{\lceil i/B \rceil} V_j A_{ij}^\top
$$

$A_{ij}$는 j번째 KV 블록에 대한 attention score 행 벡터예요. 커널은 KV 블록을 하나씩 따로 찾아 가져와 계산해요.

논문의 예에서 query 토큰 "forth"가 참조할 key, value 벡터는 떨어져 있는 블록 세 개에 있어요. 커널은 블록마다 key 벡터와 query를 곱해 score를 구하고 그 score를 같은 블록의 value 벡터와 곱해요.

### 논리 블록과 물리 블록

vLLM의 KV cache manager는 OS의 virtual memory를 본뜬 구조예요. 요청의 KV cache는 논리 KV 블록(logical KV block)의 나열로 표현되고 새 토큰이 생길 때마다 왼쪽부터 채워져요.

GPU worker에서는 block engine이 GPU DRAM의 연속 chunk를 잡아 물리 KV 블록(physical KV block)으로 나눠 둬요. swapping에 쓸 CPU RAM도 같은 방식으로 나눠요.

둘을 잇는 것이 block table이에요. block table의 항목에는 논리 블록에 대응하는 물리 블록 번호와 채워진 위치 수(#filled)가 들어가요. 논리 블록과 물리 블록이 분리되어 있어 모든 위치를 미리 예약하지 않고도 KV cache를 필요한 만큼 늘릴 수 있어요.

### 프롬프트 7토큰 요청의 디코딩 과정

블록 크기가 4이고 프롬프트가 "Four score and seven years ago our" 7토큰인 요청은 다음 순서로 처리돼요.

1. prefill 단계에서 vLLM은 프롬프트의 KV cache에 필요한 논리 블록 0, 1만 물리 블록 7, 1에 매핑해요. 기존 self-attention 커널로 프롬프트의 KV cache와 첫 출력 토큰을 만든 뒤 앞 4토큰을 논리 블록 0에, 나머지 3토큰을 논리 블록 1에 저장해요. 논리 블록 1의 남은 한 칸은 다음 생성 단계 몫이에요.
2. 첫 디코딩 단계에서는 물리 블록 7, 1 위에서 PagedAttention으로 새 토큰을 만들어요. 논리 블록 1에 한 칸이 남아 있으므로 새 KV cache를 그 칸에 넣고 block table의 #filled를 3에서 4로 바꿔요.
3. 두 번째 디코딩 단계에서는 논리 블록 1이 가득 찼으므로 새 논리 블록을 쓰고 물리 블록 3을 새로 할당해 그 매핑을 block table에 기록해요.

새 물리 블록은 앞선 블록이 모두 찼을 때만 할당돼요. 그래서 요청 하나가 낭비하는 메모리는 마지막 블록의 빈칸, 즉 블록 하나 이내죠. 요청이 끝나면 그 블록들은 풀려 다른 요청의 KV cache를 담아요.

블록 크기를 1보다 크게 잡으면 커널이 여러 위치의 KV cache를 병렬로 처리해 하드웨어 활용도가 오르고 latency가 줄어들어요. 반면 블록이 커지면 단편화도 늘어나요.

## 블록 단위로 KV cache 공유하기

### parallel sampling과 copy-on-write

프로그램 어시스턴트는 프롬프트 하나로 출력을 여러 개 뽑아 사용자가 고르게 해요. 이런 parallel sampling에서는 모든 샘플이 같은 프롬프트를 쓰므로 vLLM은 prompt 단계에서 프롬프트 상태를 한 벌만 저장해요.

샘플 두 개의 논리 블록 0, 1은 모두 물리 블록 7, 1을 가리켜요. 물리 블록 하나를 여러 논리 블록이 가리킬 수 있으므로 물리 블록마다 reference count를 둬요. 이 예에서 물리 블록 7과 1의 reference count는 2예요.

생성 단계에서 두 샘플은 서로 다른 토큰을 뽑으므로 KV cache를 따로 저장해야 해요. 샘플 A1이 마지막 논리 블록에 쓰려 할 때 vLLM은 대응하는 물리 블록 1의 reference count가 1보다 크다는 것을 확인하고 새 물리 블록 3을 할당해요. block engine이 물리 블록 1의 내용을 블록 3으로 복사하고 reference count는 1로 내려가요.

뒤이어 샘플 A2가 물리 블록 1에 쓸 때는 reference count가 이미 1이라 복사 없이 바로 쓸 수 있어요. OS가 프로세스를 fork할 때 쓰는 copy-on-write를 블록 단위로 옮긴 방식이에요.

프롬프트 KV cache 중 마지막 논리 블록을 뺀 나머지는 모든 샘플이 공유해요. 논문은 입력 프롬프트가 길 때 이 공유로 아끼는 메모리가 특히 크다고 설명해요.

### beam search

beam search는 매 단계 k·|V|개 후보(k는 beam width, |V|는 어휘 크기) 가운데 확률이 높은 k개를 남겨요. 프롬프트 블록만 공유하는 parallel sampling과 달리 생성 중에 만든 블록도 후보끼리 공유해요. 공유 관계는 디코딩이 진행되면서 바뀌어요.

beam width가 4인 논문의 예에서 모든 후보는 프롬프트가 든 블록 0을 공유해요. 후보 3은 두 번째 블록부터 다른 후보와 갈라지고 후보 0~2는 처음 세 블록을 공유하다 네 번째 블록에서 갈라져요.

다음 iteration의 상위 4개 후보는 모두 후보 1과 2에서 나왔어요. 후보 0과 3의 논리 블록이 해제되면서 reference count가 0이 된 물리 블록 2, 4, 5, 8이 풀리고 새 후보의 KV cache는 새로 할당한 물리 블록 9~12에 저장돼요.

기존 시스템에서는 이 시점에 후보 3이 생성을 이어 가려고 후보 2의 KV cache 대부분을 복사해야 해요. vLLM에서는 블록을 공유하므로 copy-on-write는 새 토큰이 기존 공유 블록 안에 들어갈 때만 일어나고 복사량도 블록 하나예요.

### 시스템 프롬프트를 공유하는 shared prefix

LLM 사용자는 흔히 지시와 예시 입출력을 담은 긴 설명(system prompt)을 실제 task input 앞에 붙여요.

vLLM에서는 서비스 제공자가 미리 정한 공유 prefix의 KV cache를 물리 블록에 올려 둬요. 같은 prefix로 시작하는 요청은 자기 논리 블록을 이 물리 블록에 매핑하고 마지막 블록만 copy-on-write로 표시해요.

OS가 여러 프로세스 사이에서 shared library를 다루는 방식과 같아요. prompt 단계 연산은 사용자의 task input 부분에만 실행해요.

### 디코딩 방식이 섞인 batch

모델과 커널은 시퀀스마다 물리 블록 ID 목록만 받고 시퀀스 사이의 공유 관계는 보지 않아요. 공유는 논리 블록을 물리 블록으로 바꾸는 매핑 계층이 맡으므로 디코딩 방식이 서로 다른 요청을 한 batch에 함께 넣을 수 있어요.

구현은 시퀀스를 복제하는 fork, 토큰을 붙이는 append, 시퀀스를 지우는 free 세 메서드로 되어 있어요.

### 블록 접근을 위한 커널

vLLM 엔진은 Python 8.5K줄과 C++/CUDA 2K줄로 되어 있어요. 블록 단위 메모리 접근은 기존 시스템이 효율적으로 지원하지 않는 패턴이라 커널 세 개를 새로 만들었어요.

1. 새 KV cache를 블록 레이아웃으로 바꿔 block table 위치에 쓰는 과정을 커널 하나(fused reshape and block write)로 합쳤어요.
2. FasterTransformer의 attention 커널을 고쳐 block table대로 KV cache를 읽으며 계산해요.
3. copy-on-write의 블록 복사를 cudaMemcpyAsync로 하면 작은 복사가 많이 호출되므로 여러 블록 복사를 커널 launch 한 번으로 묶었어요.

## 메모리가 모자랄 때의 선점과 복구

### all-or-nothing 선점

요청과 출력이 늘어나면 새 KV cache를 담을 물리 블록이 바닥날 수 있어요. vLLM은 모든 요청을 FCFS(first-come-first-serve)로 스케줄링하고 선점이 필요하면 가장 늦게 도착한 요청부터 내보내요.

시퀀스의 블록은 모두 함께 접근되므로 vLLM은 시퀀스의 블록을 전부 내보내거나 하나도 내보내지 않는 all-or-nothing 정책을 써요. beam search 후보처럼 한 요청에 속한 시퀀스들은 메모리를 공유할 수 있어서 sequence group으로 묶어 함께 선점하고 함께 다시 스케줄링해요.

### swapping과 recomputation

swapping은 내보낸 블록을 CPU 메모리로 복사해 두는 방식이고 이 블록은 CPU block allocator가 관리해요. 선점이 일어나면 선점한 시퀀스가 모두 끝날 때까지 새 요청을 받지 않으므로 CPU의 swap 공간은 KV cache에 할당한 GPU 메모리 크기로 묶여요.

recomputation은 선점한 시퀀스를 다시 스케줄링할 때 KV cache를 새로 계산해요. 디코딩에서 생성한 토큰을 원래 프롬프트에 이어 붙여 새 프롬프트로 만들면 prompt 단계 iteration 한 번에 모든 위치의 KV cache가 만들어지므로 처음 생성할 때보다 latency가 크게 낮을 수 있어요. OS의 paging에서는 쓸 수 없는 방법이에요.

### 여러 GPU에 나눠 실행할 때

vLLM은 Megatron-LM 방식의 tensor model parallelism을 지원하고 attention 연산을 head 차원으로 나눠요. 모델을 나눠도 shard마다 같은 입력 토큰을 처리하므로 필요한 KV cache 위치도 같아요.

그래서 KV cache manager는 중앙 scheduler 안에 하나만 있고 worker마다 자기 attention head 몫의 KV cache만 저장해요. scheduler가 매 step 입력 토큰 ID와 block table을 broadcast하므로 worker끼리 메모리 관리를 위해 동기화할 필요가 없어요.

## OPT와 LLaMA로 잰 처리량

### 모델, 워크로드, 비교 대상

모델은 OPT 13B, 66B, 175B와 LLaMA 13B를 썼고 Google Cloud의 A2 인스턴스(NVIDIA A100)에서 실험했어요.

| 모델 크기 | 13B | 66B | 175B |
|---|---|---|---|
| GPU | A100 | 4×A100 | 8×A100-80GB |
| 전체 GPU 메모리 | 40GB | 160GB | 640GB |
| 파라미터 크기 | 26GB | 132GB | 346GB |
| KV cache용 메모리 | 12GB | 21GB | 264GB |
| 최대 KV cache 슬롯 수 | 15.7K | 9.7K | 60.1K |

13B의 슬롯 수 15.7K는 KV cache용 12GB를 토큰당 800KB로 나눈 값과 맞아요. 66B는 KV cache용 메모리가 21GB로 13B보다 많은데도 슬롯 수는 9.7K로 더 적어요. 모델이 커진 만큼 토큰당 KV cache도 커졌기 때문으로 보여요.

워크로드는 ShareGPT(사용자가 공유한 ChatGPT 대화)와 Alpaca(GPT-3.5가 self-instruct로 만든 instruction 데이터)의 입출력 길이로 합성했어요. 데이터셋에 타임스탬프가 없어 요청 도착 시간은 Poisson 분포로 만들었어요.

ShareGPT의 평균 길이는 입력 161.31토큰, 출력 337.99토큰으로 Alpaca(입력 19.31, 출력 58.45)보다 입력이 8.4배, 출력이 5.8배 길고 분산도 커요.

비교 대상은 FasterTransformer와 앞에서 본 Orca 세 버전이에요. 자체 스케줄러가 없는 FasterTransformer에는 dynamic batching 스케줄러를 붙였고 공개되지 않은 Orca는 buddy allocator를 쓴다고 가정해 직접 구현했어요.

지표는 normalized latency예요. 요청마다 end-to-end latency를 출력 길이로 나눈 뒤 평균한 값이고, 요청률을 올려도 이 값이 낮게 유지되는 시스템이 처리량이 높은 시스템이에요. trace는 대부분 1시간짜리를 썼고 OPT-175B만 비용 때문에 15분짜리를 썼어요.

### 요청 하나에 샘플 하나인 basic sampling

ShareGPT에서 vLLM은 비슷한 latency를 유지하면서 Orca (Oracle)보다 1.7~2.7배, Orca (Max)보다 2.7~8배 높은 요청률을 처리했어요. FasterTransformer와 비교하면 최대 22배예요. FasterTransformer는 fine-grained 스케줄링을 쓰지 않고 메모리도 Orca (Max)처럼 관리해요.

차이는 batch 크기에서 나와요. OPT-13B에서 동시에 batch에 들어간 요청 수의 평균(논문 그림 13)은 다음과 같아요.

| 워크로드 | Orca (Max) | Orca (Pow2) | Orca (Oracle) | vLLM |
|---|---|---|---|---|
| ShareGPT, 2 req/s | 7.00 | 9.81 | 13.62 | 30.42 |
| Alpaca, 30 req/s | 7.00 | 43.24 | 72.75 | 132.44 |

ShareGPT에서 vLLM은 Orca (Oracle)의 2.2배, Orca (Max)의 4.3배 요청을 동시에 처리했어요. Alpaca에서는 Orca (Oracle) 대비 1.8배로 차이가 줄었어요.

Orca (Max)는 두 워크로드 모두 7.00인데요. 슬롯 15.7K를 요청당 2048칸씩 나누면 7.67이므로 요청 길이와 관계없이 7개만 들어가는 구조로 보여요.

Alpaca에서도 경향은 같았지만 OPT-175B에서는 Orca (Oracle), Orca (Pow2)와의 차이가 작았어요. 이 설정은 KV cache용 메모리가 264GB로 크고 Alpaca 시퀀스는 짧아서 Orca도 요청을 많이 묶을 수 있어요. 성능을 제한하는 요인이 메모리에서 연산으로 바뀐 경우예요.

### parallel sampling과 beam search

OPT-13B와 Alpaca로 잰 결과예요. parallel sampling에서는 샘플 수를 2, 4, 6으로 늘리면서 Orca 대비 개선 폭이 커졌어요. beam search는 공유할 블록이 더 많아 차이가 더 컸고 Orca (Oracle) 대비 개선은 basic sampling의 1.3배에서 beam width 6의 2.3배로 늘었어요.

메모리 절약률은 공유로 아낀 블록 수를 공유하지 않았을 때의 전체 블록 수로 나눈 값이에요.

| 출력 수 또는 beam width | 2 | 4 | 6 |
|---|---|---|---|
| parallel sampling | 6.09% | 8.53% | 9.79% |
| beam search | 37.56% | 53.13% | 55.16% |

beam width를 4에서 6으로 늘렸을 때 절약률은 53.13%에서 55.16%로 2%p 정도 늘었어요. 같은 실험을 ShareGPT로 하면 parallel sampling은 16.2~30.5%, beam search는 44.3~66.3%였어요.

parallel sampling이 공유하는 것은 프롬프트의 KV cache예요. 프롬프트가 평균 8.4배 긴 ShareGPT에서 절약률이 Alpaca의 2.7~3.1배로 나온 것도 이 구조와 맞는 결과로 보여요.

### shared prefix와 chatbot

shared prefix 실험은 다국어 모델인 LLaMA-13B로 WMT16 영어-독일어 번역을 했어요. 지시와 번역 예시를 담은 prefix를 두 가지로 만들었어요. 예시 1개(80토큰)를 공유할 때 vLLM의 처리량은 Orca (Oracle)의 1.67배, 예시 5개(341토큰)를 공유할 때는 3.58배였어요.

chatbot 실험은 ShareGPT로 대화 기록과 질의를 합성했어요. OPT-13B의 컨텍스트 제한 때문에 프롬프트는 마지막 1024토큰으로 자르고 출력은 최대 1024토큰으로 했어요. 대화 라운드 사이의 KV cache는 저장하지 않았어요.

vLLM은 세 Orca보다 2배 높은 요청률을 처리했고 세 Orca의 결과는 거의 같았어요. 대부분 요청의 프롬프트가 1024토큰이라 buddy allocator가 출력 길이 예측과 관계없이 출력용으로 1024토큰 공간을 잡거든요.

## 블록 크기와 커널 오버헤드

### attention 커널은 20~26% 느리다

vLLM의 attention 커널은 block table을 읽고 분기를 더 실행하고 가변 시퀀스 길이를 처리해요. 그래서 context 길이 64~256, batch 크기 8과 32에서 FasterTransformer 커널보다 latency가 20~26% 높았어요.

저자들은 이 오버헤드가 attention 연산자에만 생기고 Linear 같은 다른 연산자에는 영향이 없어 작다고 판단해요. end-to-end 성능에서는 vLLM이 FasterTransformer를 크게 앞섰어요.

### 기본 블록 크기가 16인 이유

블록이 너무 작으면 KV cache를 읽고 처리할 때 GPU 병렬성을 다 쓰지 못해요. 너무 크면 내부 단편화가 늘고 블록을 공유할 확률이 줄어들어요.

요청률을 고정하고 블록 크기를 1부터 256까지 바꿔 보면 ShareGPT에서는 16~128이 가장 좋았어요. Alpaca에서는 16과 32가 좋았고 그보다 크면 시퀀스가 블록보다 짧아져 성능이 크게 떨어졌어요.

Alpaca의 평균 입력과 출력을 더하면 77.76토큰이에요. 블록 크기가 128이면 평균적인 요청은 블록 하나도 다 채우지 못하죠.

저자들은 블록 크기 16이 GPU를 효율적으로 쓸 만큼 크고 대부분의 workload에서 내부 단편화를 피할 만큼 작다고 보고 기본값을 16으로 정했어요.

### 블록 크기에 따라 갈리는 swapping과 recomputation

블록이 작으면 swapping 오버헤드가 커지는데요. CPU와 GPU 사이에 작은 전송이 많이 생겨 실제로 쓸 수 있는 PCIe 대역폭이 줄거든요.

recomputation은 KV 블록을 쓰지 않으므로 블록 크기와 관계없이 오버헤드가 일정해요. 그래서 블록이 작을 때는 recomputation이, 클 때는 swapping이 유리했어요. 블록 크기 16~64에서는 두 방법의 end-to-end 성능이 비슷했어요.

## 한국어 LLM 서비스에 옮긴다면

논문의 이득은 서빙이 GPU 메모리에 묶여 있다는 조건에서 나와요. OPT-175B와 Alpaca 조합처럼 KV cache 공간이 넉넉하고 시퀀스가 짧으면 Orca (Oracle)와의 차이가 작았어요. 짧은 질의응답처럼 출력이 짧은 요청이 대부분이고 GPU 메모리에 여유가 있는 서비스라면 이득이 논문의 2~4배보다 작을 수 있어요.

토큰당 KV cache 크기(OPT-13B 기준 800KB)는 모델 구조로 정해져요. 쓰는 토크나이저가 한국어 문장을 같은 분량의 영어보다 많은 토큰으로 나눈다면 요청당 KV cache도 토큰 수만큼 커져요. 이 경우 서비스의 길이 분포가 Alpaca보다 ShareGPT 쪽에 가까워질 수 있고, 논문은 시퀀스가 길수록 개선이 두드러진다고 정리했어요.

공통 시스템 프롬프트를 붙이는 서비스라면 shared prefix 결과를 참고할 수 있어요. 공유 prefix가 80토큰일 때 1.67배, 341토큰일 때 3.58배였어요. 다만 두 설정만 잰 값이라 prefix 길이와 이득의 관계를 일반화하기는 어렵고 자기 서비스의 prefix 길이로 다시 재 봐야 해요.

멀티턴 챗봇이라면 chatbot 실험의 2배가 대화 라운드 사이의 KV cache를 저장하지 않은 조건이라는 점을 함께 봐야 해요. 라운드마다 최근 1024토큰의 대화 기록을 프롬프트로 다시 계산한 결과예요.

블록 크기 16은 ShareGPT와 Alpaca 분포에서 고른 기본값이에요. Alpaca처럼 입출력을 합쳐 평균 78토큰 정도인 요청이 대부분이라면 32보다 큰 블록은 피하는 편이 맞아요. 선점 복구 방식도 하드웨어에 따라 달라질 수 있어요. 두 방법의 성능이 CPU-GPU 대역폭과 GPU 연산 능력에 좌우되므로 A100이 아닌 GPU에서는 swapping과 recomputation이 갈리는 블록 크기가 달라질 수 있어요.

## 마치며

PagedAttention의 2~4배는 출력 길이를 미리 알 수 없고 성능이 GPU 메모리 용량에 묶인 LLM 서빙에서 잰 값이에요. 실험은 A100에서 OPT 13B·66B·175B와 LLaMA-13B로 했고 요청은 ShareGPT, Alpaca 길이 분포로 합성했으며 비교한 Orca는 저자들이 직접 구현한 버전이에요. 저자들은 텐서 shape가 정적인 DNN 학습이나 연산이 병목인 비LLM 모델 서빙에서는 메모리 간접 참조와 비연속 블록 접근의 오버헤드로 성능이 오히려 떨어질 수 있다고 밝혔어요. 자기 서비스에 적용할지는 KV cache가 batch 크기를 막고 있는지부터 확인하고 정하면 돼요.

## 참고자료

- [1] Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica, Efficient Memory Management for Large Language Model Serving with PagedAttention (2023). SOSP '23. https://arxiv.org/abs/2309.06180
- [2] vLLM 소스 코드. https://github.com/vllm-project/vllm
- [3] Gyeong-In Yu, Joo Seong Jeong, Geon-Woo Kim, Soojeong Kim, Byung-Gon Chun, Orca: A Distributed Serving System for Transformer-Based Generative Models (2022). OSDI 22.
- [4] NVIDIA, FasterTransformer (2023). https://github.com/NVIDIA/FasterTransformer
