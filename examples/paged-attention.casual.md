# PagedAttention: KV cache를 블록으로 나눠 LLM 서빙 처리량을 2~4배 높인 방법

LLM 서빙 시스템에 최대 시퀀스 길이가 2048 토큰인 요청 하나가 들어왔다고 해 볼게요. 프롬프트는 "Four score and seven years ago our"라는 7토큰이고 모델은 토큰 세 개를 더 만들고 끝나요. FasterTransformer나 Orca 같은 기존 서빙 시스템은 이 요청을 받을 때 KV cache 자리를 2048 토큰만큼 연속으로 잡아 두므로 2038 자리는 요청이 끝날 때까지 한 번도 쓰이지 않아요.

UC Berkeley 등의 연구진은 SOSP 2023 논문 「Efficient Memory Management for Large Language Model Serving with PagedAttention」에서 이 낭비를 OS의 가상 메모리와 페이징 기법으로 줄였어요. KV cache를 고정 크기 블록으로 나눠 필요할 때 할당하는 attention 알고리즘이 PagedAttention이고, 그 위에 만든 서빙 엔진이 vLLM이에요. 이 글에서는 PagedAttention이 KV cache 메모리를 관리하는 방식과 그 방식이 처리량을 얼마나 바꿨는지 정리해요.

vLLM은 FasterTransformer, Orca와 비슷한 latency를 유지하면서 처리량을 2~4배 높였어요. 개선 폭은 시퀀스가 길고 모델이 크고 디코딩 알고리즘이 복잡할 때 더 컸어요.

## KV cache가 배치 크기를 정하는 이유

LLM은 토큰을 한 번에 하나씩 생성해요. 새 토큰을 만들 때마다 앞선 모든 토큰의 key 벡터와 value 벡터가 필요하므로 서빙 시스템은 이 벡터를 GPU 메모리에 저장해 두고 다시 써요. 이 저장 공간을 KV cache라고 불러요.

토큰을 하나씩 만드는 생성 단계는 GPU 연산 능력을 다 쓰지 못하는 memory-bound 작업이에요. 여러 요청을 배치로 묶으면 요청들이 같은 모델 가중치를 함께 읽어서 가중치를 옮기는 비용이 요청 수만큼 나뉘어요. 그래서 배치에 요청을 많이 넣을 수 있으면 처리량이 오르죠.

13B 파라미터 모델을 NVIDIA A100 40GB 한 장에서 서빙하면 GPU 메모리의 약 65%(26GB)는 모델 가중치가, 30% 가까이는 KV cache가 차지해요. 가중치는 서빙 내내 그대로이고 activation이 쓰는 메모리는 작아요. 그래서 최대 배치 크기는 KV cache를 관리하는 방식에 달려 있어요.

OPT-13B에서 토큰 하나의 KV cache는 800KB예요. key와 value 두 벡터에 hidden state 크기 5120, layer 수 40, FP16 한 값의 크기 2바이트를 곱한 값이에요.

OPT는 최대 2048 토큰까지 생성하므로 요청 하나의 KV cache는 최대 1.6GB까지 커져요.

Orca가 쓰는 iteration-level scheduling은 iteration마다 끝난 요청을 배치에서 빼고 새 요청을 넣어서 요청의 대기 시간과 padding으로 버리는 연산을 줄였어요. 이 방식에서도 한 번에 배치할 수 있는 요청 수는 KV cache에 쓸 수 있는 GPU 메모리가 제한해요.

A100에서 H100으로 넘어가면서 FLOPS는 2배 넘게 늘었지만 GPU 메모리는 최대 80GB로 같았는데요. 저자들은 이 추세 때문에 메모리가 점점 더 큰 병목이 될 것으로 봐요.

## 기존 시스템은 KV cache 메모리를 얼마나 버릴까

FasterTransformer와 Orca는 요청 하나의 KV cache를 연속된 메모리 공간에 저장해요. 대부분의 딥러닝 프레임워크가 tensor를 연속 메모리에 두도록 요구하거든요. 출력 길이는 생성이 끝나야 알 수 있으므로 두 시스템은 요청이 들어올 때 그 요청의 최대 시퀀스 길이만큼 메모리를 한 번에 잡아요.

미리 잡은 공간 가운데 앞으로 생성할 토큰에 쓸 예약(reserved) 공간은 결국 쓰이지만 요청이 끝날 때까지 다른 요청이 쓸 수 없어요. 실제 길이보다 크게 잡아서 끝까지 쓰이지 않는 부분은 내부 단편화(internal fragmentation)예요. 외부 단편화(external fragmentation)는 요청마다 잡는 크기가 달라서 buddy allocator 같은 할당기의 chunk 사이에 남는 공간이에요.

Orca는 코드가 공개되지 않아 연구진이 직접 구현했고, 출력 공간을 얼마나 넉넉히 잡는지에 따라 세 버전을 만들었어요. Orca (Max)는 항상 모델의 최대 길이인 2048 토큰을 잡아요. Orca (Pow2)는 실제 출력 길이의 최대 2배를 잡아서 출력이 25토큰이면 32토큰을 잡아요.

Orca (Oracle)은 실제 출력 길이를 미리 안다고 가정한 버전이고 실제로는 만들 수 없는 상한이에요.

기본 샘플링 실험 동안 세 Orca 버전의 KV cache 메모리가 평균적으로 어디에 쓰였는지 비율로 나누면 다음과 같아요.

| 시스템 | 토큰 상태 | 예약 | 내부 단편화 | 외부 단편화와 기타 |
|---|---|---|---|---|
| Orca (Max) | 20.4% | 13.3% | 57.3% | 8.9% |
| Orca (Pow2) | 26.8% | 17.9% | 13.6% | 41.6% |
| Orca (Oracle) | 38.2% | 25.2% | - | 36.6% |

세 Orca 버전이 실제 토큰 상태를 저장한 비율은 20.4~38.2%였어요. Orca (Oracle)은 출력 길이를 정확히 알고도 38.2%만 토큰 상태에 썼어요. 예약 25.2%와 외부 단편화와 기타 36.6%는 출력 길이를 알아도 남는 낭비이고, 두 낭비 모두 요청마다 연속 공간을 통째로 잡는 방식에서 생겨요.

같은 실험에서 vLLM은 KV cache 메모리의 96.3%에 토큰 상태를 저장했어요.

연속 공간 방식에서는 메모리를 공유할 수도 없어요. parallel sampling과 beam search는 요청 하나에서 출력 시퀀스를 여러 개 만들고 이 시퀀스들은 같은 프롬프트의 KV cache를 가져요. 기존 시스템은 시퀀스마다 KV cache를 별도의 연속 공간에 저장하므로 같은 프롬프트의 KV cache를 시퀀스마다 따로 둬요.

## PagedAttention과 block table

PagedAttention은 시퀀스의 KV cache를 KV block으로 나누고, 블록들이 메모리에 떨어져 있어도 attention을 계산할 수 있게 만든 attention 알고리즘이에요. 블록 하나에는 정해진 수의 토큰에 대한 key와 value 벡터가 들어가고 이 토큰 수를 블록 크기라고 불러요. attention kernel은 블록을 하나씩 찾아와 query 벡터와 그 블록의 key 벡터로 attention score를 구하고 이 score를 그 블록의 value 벡터에 곱해요.

OS의 가상 메모리에 대응시키면 블록은 페이지, 토큰은 바이트, 요청은 프로세스예요.

vLLM의 KV cache manager는 요청의 KV cache를 logical block의 목록으로 보고 왼쪽부터 채워요. GPU worker의 block engine은 GPU DRAM에 연속된 공간을 잡아 physical block으로 나눠 둬요. 요청마다 있는 block table은 logical block이 어느 physical block에 있는지와 블록마다 몇 자리가 찼는지를 기록해요.

블록 크기가 4이고 프롬프트가 7토큰인 요청은 아래 순서로 메모리를 받아요.

1. 프롬프트 단계에서 vLLM은 logical block 0과 1을 physical block 7과 1에 매핑해요. 처음 4토큰의 KV cache는 logical block 0에, 나머지 3토큰은 logical block 1에 들어가고 logical block 1에 한 자리가 남아요.
2. 첫 디코딩 단계에서 새 토큰의 KV cache는 logical block 1의 빈자리에 들어가고, block table에 기록한 찬 자리 수가 3에서 4로 바뀌어요.
3. 두 번째 디코딩 단계에서는 logical block 1이 가득 찼으므로 vLLM이 새 logical block을 만들고 physical block 3을 할당해 block table에 적어요.

vLLM은 앞 블록이 다 찼을 때만 physical block을 새로 할당하므로 요청 하나가 버리는 메모리는 블록 하나 안으로 제한돼요. 블록 크기가 16이면 요청 하나에서 비는 자리는 많아야 15개죠. 요청이 끝나면 그 요청의 블록은 반납되어 다른 요청의 KV cache를 담아요.

모델을 여러 GPU에 나눠 실행할 때도 KV cache manager는 중앙 scheduler 안에 하나만 있어요. Megatron-LM 방식의 tensor parallelism에서는 GPU마다 같은 입력 토큰을 처리하므로 worker들은 같은 block table을 받고 각자 맡은 attention head의 KV cache만 저장해요.

### 블록 크기를 16으로 정한 이유

블록이 작으면 kernel이 KV cache를 읽고 처리할 때 GPU 병렬성을 다 쓰지 못하는데요. 블록이 크면 마지막 블록의 빈자리가 늘어 내부 단편화가 커지고 블록을 공유할 확률은 줄어들어요.

고정된 요청률에서 기본 샘플링으로 잰 end-to-end latency는 데이터셋마다 달랐어요. 평균 입력 161토큰, 평균 출력 338토큰인 ShareGPT 트레이스에서는 블록 크기 16~128의 성능이 가장 좋았어요. 평균 입력 19토큰, 평균 출력 58토큰인 Alpaca 트레이스에서는 16과 32가 좋았고 그보다 큰 블록에서는 시퀀스가 블록보다 짧아져 성능이 크게 떨어졌어요.

저자들은 블록 크기 16이 대부분의 워크로드에서 GPU를 충분히 활용할 만큼 크고 내부 단편화를 피할 만큼 작다고 보고 vLLM의 기본 블록 크기를 16으로 정했어요.

PagedAttention의 attention kernel은 block table을 읽고 분기를 더 실행하고 가변 시퀀스 길이를 처리해야 해서 FasterTransformer의 attention kernel보다 latency가 20~26% 높았어요. 이 오버헤드는 attention 연산자에만 생기고 Linear 같은 다른 연산자에는 생기지 않아요. vLLM은 block table대로 KV cache를 읽는 과정과 attention 계산을 kernel 하나로 합치고, 블록 하나를 GPU warp 하나가 읽게 해서 메모리 접근을 coalesced access로 맞췄어요.

vLLM 엔진은 Python 8.5K줄과 C++/CUDA 2K줄로 되어 있어요. scheduler와 block manager는 Python으로, PagedAttention 같은 핵심 연산은 CUDA kernel로 작성했어요.

## 블록 단위로 KV cache 공유하기

vLLM에서는 physical block 하나를 여러 logical block에 매핑할 수 있어서 같은 KV cache를 여러 시퀀스가 함께 써요. vLLM은 physical block마다 reference count를 두어 그 블록을 가리키는 logical block 수를 세요.

### Parallel sampling과 copy-on-write

parallel sampling은 프롬프트 하나로 출력을 여러 개 만들어 사용자가 고르게 하는 방식이고 프로그래밍 어시스턴트에서 써요. 출력 두 개를 만드는 요청에서 vLLM은 두 시퀀스의 프롬프트용 logical block 0, 1을 같은 physical block 7, 1에 매핑해요. 두 physical block의 reference count는 2예요.

생성 단계에서는 두 샘플 A1과 A2가 서로 다른 토큰을 만들어요. 샘플 A1이 마지막 logical block에 새 KV cache를 쓰려 하면 vLLM은 physical block 1의 reference count가 1보다 큰 것을 보고 새 physical block 3에 block 1의 내용을 복사한 뒤 block 1의 reference count를 1로 줄여요. 다음에 샘플 A2가 쓸 때는 reference count가 이미 1이므로 physical block 1에 바로 써요.

이 방식은 OS가 fork한 프로세스의 페이지를 다루는 copy-on-write를 블록 단위로 옮긴 거예요. 프롬프트의 KV cache는 마지막 logical block을 뺀 나머지를 모든 샘플이 공유해요. copy-on-write가 떨어진 블록 여러 개를 복사할 때 cudaMemcpyAsync를 블록마다 부르면 작은 데이터 이동이 많이 생기므로 vLLM은 여러 블록의 복사를 kernel launch 한 번으로 묶었어요.

### Beam search

beam search는 매 단계에서 확률이 높은 후보 k개를 남기는 디코딩 방식이고 기계 번역 같은 작업에 써요. beam 후보들은 프롬프트 블록과 함께 갈라지기 전까지 생성한 블록도 공유하고, 공유 관계는 디코딩이 진행되면서 바뀌어요.

k가 4인 예에서 다음 단계의 상위 4개 후보가 모두 기존 후보 1과 2에서 나오면 탈락한 후보 0과 3만 쓰던 physical block 4개는 reference count가 0이 되어 반납돼요. 기존 서빙 시스템은 이런 상황에서 beam 후보 사이에 KV cache를 자주 복사해야 했어요. vLLM에서는 후보들이 블록 대부분을 공유하고 새 토큰이 공유 중인 블록에 들어갈 때만 그 블록 하나를 copy-on-write로 복사해요.

### Shared prefix

LLM 서비스는 instruction과 예시 입출력이 든 system prompt를 사용자 입력 앞에 붙여 프롬프트를 만들기도 해요. 이런 서비스에서는 여러 요청이 같은 prefix를 가지므로 서비스 제공자가 prefix의 KV cache를 physical block에 미리 저장해 둘 수 있어요. 요청이 오면 vLLM은 prefix 부분의 logical block을 캐시된 physical block에 매핑하고, 프롬프트 단계 계산은 사용자 입력 부분에만 해요.

디코딩 방식이 다른 요청도 한 배치에 넣을 수 있어요. logical block을 physical block으로 옮기는 매핑 계층이 공유 관계를 감추므로 모델과 kernel은 시퀀스마다 physical block ID 목록만 받아요. vLLM은 이런 디코딩 방식을 시퀀스를 복제하는 fork, 토큰을 붙이는 append, 시퀀스를 지우는 free 세 메서드로 구현해요.

## 메모리가 모자랄 때 선점하고 복구하기

요청이 몰리고 출력이 길어지면 GPU의 physical block이 바닥날 수 있어요. vLLM은 요청을 도착 순서대로 처리하는 FCFS(first-come-first-serve) 정책을 쓰고 선점이 필요하면 가장 늦게 온 요청부터 선점해요.

한 시퀀스의 블록은 함께 접근되므로 vLLM은 시퀀스의 블록을 전부 내보내거나 하나도 내보내지 않아요. beam search 후보처럼 요청 하나에 속한 시퀀스들은 메모리를 공유할 수 있어서 sequence group으로 묶어 함께 선점하고 함께 다시 스케줄해요.

내보낸 블록을 되살리는 방법은 swapping과 recomputation이에요. swapping은 내보낸 블록을 CPU 메모리로 복사해 두었다가 다시 가져와요.

선점이 일어나면 vLLM은 선점한 시퀀스가 모두 끝날 때까지 새 요청을 받지 않아요. 이 설계에서 CPU로 나간 블록 수는 GPU의 전체 physical block 수를 넘지 않으므로 CPU 쪽 swap 공간은 KV cache에 할당한 GPU 메모리 크기로 제한돼요.

recomputation은 선점한 시퀀스를 다시 스케줄할 때 KV cache를 새로 계산해요. 이미 생성한 토큰을 원래 프롬프트 뒤에 붙여 새 프롬프트로 넣으면 프롬프트 단계 한 번에 모든 위치의 KV cache를 만들 수 있어서 처음 생성할 때보다 latency가 훨씬 짧을 수 있어요.

두 방법의 비용은 블록 크기에 따라 갈렸어요. 블록이 작으면 CPU와 GPU 사이에 작은 전송이 많이 생겨 유효 PCIe 대역폭이 줄고 swapping 오버헤드가 커졌어요. recomputation은 KV block을 쓰지 않아서 오버헤드가 블록 크기와 상관없이 일정했어요. OPT-13B와 ShareGPT 트레이스로 잰 end-to-end 성능은 블록 크기 16~64에서 두 방법이 비슷했고, 기본 블록 크기 16도 이 구간에 들어가요.

## Orca, FasterTransformer와 비교한 처리량

### 실험 설정

실험은 Google Cloud의 A2 인스턴스(NVIDIA A100)에서 OPT 13B, 66B, 175B와 LLaMA 13B로 했어요. 모델 크기별 GPU 구성과 KV cache에 쓸 수 있는 메모리는 다음과 같아요.

| 모델 크기 | GPU | 전체 GPU 메모리 | 파라미터 크기 | KV cache 메모리 | 최대 KV cache 슬롯 |
|---|---|---|---|---|---|
| 13B | A100 | 40GB | 26GB | 12GB | 15.7K |
| 66B | 4×A100 | 160GB | 132GB | 21GB | 9.7K |
| 175B | 8×A100-80GB | 640GB | 346GB | 264GB | 60.1K |

워크로드는 ShareGPT와 Alpaca 데이터셋의 입력 길이와 출력 길이로 합성했어요. ShareGPT는 사용자들이 공유한 ChatGPT 대화 모음이고 평균 입력이 161토큰, 평균 출력이 338토큰이에요. Alpaca는 GPT-3.5가 self-instruct로 만든 instruction 데이터셋이고 평균 입력이 19토큰, 평균 출력이 58토큰이에요. ShareGPT의 평균 입력은 Alpaca의 8.4배, 평균 출력은 5.8배예요.

요청 도착 시각은 Poisson 분포로 만들었어요.

FasterTransformer는 latency에 최적화된 분산 추론 엔진이고 자체 scheduler가 없어서 연구진이 Triton과 비슷한 dynamic batching scheduler를 붙였어요. Orca는 출력 공간을 잡는 방식에 따라 Max, Pow2, Oracle 세 버전을 직접 구현해 썼어요.

지표는 normalized latency예요. normalized latency는 요청마다 end-to-end latency를 출력 길이로 나눈 값의 평균(s/token)이고, 처리량이 높은 시스템은 요청률이 높아져도 이 값을 낮게 유지해요. 트레이스는 1시간 길이를 썼고 OPT-175B만 비용 때문에 15분 트레이스를 썼어요.

### 기본 샘플링

요청 하나에 출력 하나를 만드는 기본 샘플링에서 요청률을 올리면 normalized latency는 천천히 오르다가 요청률이 시스템 용량을 넘는 지점에서 갑자기 치솟아요. 용량을 넘으면 큐가 끝없이 길어지거든요.

ShareGPT 워크로드에서 vLLM은 비슷한 latency를 유지하면서 Orca (Oracle)보다 1.7~2.7배, Orca (Max)보다 2.7~8배 높은 요청률을 처리했어요. FasterTransformer와 비교하면 vLLM이 처리한 요청률은 최대 22배였어요. FasterTransformer는 fine-grained scheduling이 없고 메모리도 Orca (Max)처럼 비효율적으로 관리하기 때문이에요.

요청률 차이는 한 번에 배치한 요청 수에서 나와요. OPT-13B를 서빙할 때 평균 배치 요청 수는 다음과 같아요.

| 시스템 | ShareGPT (2 req/s) | Alpaca (30 req/s) |
|---|---|---|
| Orca (Max) | 7.00 | 7.00 |
| Orca (Pow2) | 9.81 | 43.24 |
| Orca (Oracle) | 13.62 | 72.75 |
| vLLM | 30.42 | 132.44 |

ShareGPT에서 vLLM은 Orca (Oracle)보다 2.2배, Orca (Max)보다 4.3배 많은 요청을 동시에 처리했어요. Orca (Max)의 평균 배치 요청 수는 두 데이터셋에서 모두 7.00이었어요. 13B 설정의 KV cache 슬롯 15.7K를 Orca (Max)가 요청마다 잡는 2048 토큰으로 나누면 7.7이에요. 이 계산대로라면 Orca (Max)의 KV cache 메모리에는 데이터셋과 상관없이 요청이 7개까지만 들어가요.

Alpaca 워크로드에서 잰 요청률도 ShareGPT와 같은 경향이었지만 OPT-175B에서는 vLLM이 Orca (Oracle)와 Orca (Pow2)를 앞선 폭이 다른 모델 크기보다 작았어요. OPT-175B 설정은 KV cache에 264GB를 쓸 수 있고 Alpaca는 시퀀스가 짧아서 Orca도 요청을 많이 배치할 수 있었기 때문이에요. 이 설정에서 시스템은 compute-bound 상태였어요.

### 공유가 많은 워크로드

parallel sampling과 beam search 실험은 OPT-13B와 Alpaca 워크로드로 했어요. 요청 하나에서 만드는 샘플 수를 2, 4, 6으로 늘리자 vLLM이 Orca보다 앞선 폭이 커졌고, 공유할 블록이 더 많은 beam search에서는 차이가 더 컸어요. Orca (Oracle) 대비 vLLM의 개선 폭은 기본 샘플링의 1.3배에서 beam width 6인 beam search의 2.3배로 늘었어요.

블록 공유로 아낀 메모리는 공유로 아낀 블록 수를 공유하지 않았을 때의 전체 블록 수로 나눠 쟀어요. Alpaca 워크로드에서 잰 절감률은 다음과 같아요.

| 설정 | 2 | 4 | 6 |
|---|---|---|---|
| parallel sampling (출력 수) | 6.09% | 8.53% | 9.79% |
| beam search (beam width) | 37.56% | 53.13% | 55.16% |

ShareGPT 워크로드에서 잰 절감률은 parallel sampling에서 16.2~30.5%, beam search에서 44.3~66.3%로 Alpaca보다 높았어요. ShareGPT의 평균 입력이 Alpaca의 8.4배라서 샘플들이 공유하는 프롬프트 블록이 더 많기 때문으로 보여요.

shared prefix 실험은 다국어 모델인 LLaMA-13B로 WMT16 영어-독일어 번역을 하면서 instruction과 번역 예시가 든 prefix를 요청들이 공유하게 했어요. 예시 1개가 든 80토큰 prefix에서 vLLM의 처리량은 Orca (Oracle)의 1.67배였고, 예시 5개가 든 341토큰 prefix에서는 3.58배였어요.

챗봇 실험은 OPT-13B에 ShareGPT의 대화 기록과 마지막 질문을 프롬프트로 넣었어요. 프롬프트는 마지막 1024토큰으로 자르고 출력은 최대 1024토큰으로 제한했어요. 이 실험에서 vLLM은 세 Orca 버전보다 2배 높은 요청률을 처리했어요.

ShareGPT에는 긴 대화가 많아 대부분 요청의 입력이 1024토큰이었고, buddy allocation 때문에 세 Orca 버전 모두 출력 길이 예측과 상관없이 출력용으로 1024토큰을 잡았어요.

## 한국어 서비스에 옮긴다면

한국어 텍스트를 영어보다 많은 토큰으로 나누는 토크나이저를 쓰는 서비스라면 같은 내용의 대화도 시퀀스가 길어지고 요청당 KV cache가 커져요. vLLM의 개선 폭은 시퀀스가 긴 워크로드에서 컸으므로 이런 서비스의 결과는 Alpaca보다 ShareGPT 쪽에 가까울 수 있어요.

모든 요청 앞에 같은 system prompt를 붙이는 서비스라면 shared prefix 실험이 가장 가까운 조건이에요. 이 실험에서는 공유 prefix가 80토큰에서 341토큰으로 길어지자 Orca (Oracle) 대비 처리량이 1.67배에서 3.58배로 커졌어요. system prompt가 5-shot 실험의 341토큰처럼 길다면 prefix의 KV cache를 미리 저장해 두는 설정부터 확인해 볼 수 있어요.

짧은 질문에 짧게 답하는 요청이 대부분이고 KV cache에 쓸 GPU 메모리가 넉넉한 서비스라면 OPT-175B와 Alpaca 조합처럼 compute-bound가 되어 vLLM의 이득이 작을 수 있어요. 이런 워크로드에서 블록 크기를 32보다 키우면 Alpaca 실험처럼 시퀀스가 블록보다 짧아져 성능이 떨어질 수 있어요.

## 마치며

PagedAttention의 이득은 KV cache 메모리가 배치 크기를 제한하는 memory-bound 워크로드에서 나와요. 저자들은 LLM이 아닌 DNN 서빙처럼 연산이 병목인 워크로드에 같은 기법을 쓰면 블록을 거치는 간접 참조와 비연속 메모리 때문에 성능이 오히려 떨어질 수 있다고 봐요. 실험은 A100에서 OPT 13B, 66B, 175B와 LLaMA-13B로 했고 요청은 ShareGPT, Alpaca, WMT16의 길이로 합성했어요. 챗봇 실험은 대화 라운드 사이에 KV cache를 남기지 않았으므로 이전 대화의 KV cache를 다음 라운드까지 들고 있는 구성은 이 결과의 범위 밖이에요.

## 참고자료

[1] Woosuk Kwon, Zhuohan Li 외, Efficient Memory Management for Large Language Model Serving with PagedAttention (2023). https://arxiv.org/abs/2309.06180
[2] vLLM 프로젝트, vLLM (2023). https://github.com/vllm-project/vllm
[3] Gyeong-In Yu 외, Orca: A Distributed Serving System for Transformer-Based Generative Models (2022). OSDI 22
[4] NVIDIA, FasterTransformer (2023). https://github.com/NVIDIA/FasterTransformer
