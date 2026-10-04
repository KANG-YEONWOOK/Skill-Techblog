---
description: 짧은 엔지니어링 노트를 해요체(Casual) 기술 블로그 글로 정리한다
max_turns: 60
timeout_seconds: 1500
allowed_tools: [Read, Glob, Grep, Skill]
---

아래 자료의 핵심 내용을 한국어 기술 블로그 아티클로 정리해서 현재 폴더에 article.md 파일로 저장해줘. 어투는 해요체(Casual)로 써줘.

# Migrating the API rate limiter from fixed window to token bucket (internal engineering note, 2026)

## Background
Our public API used a fixed-window rate limiter: each client could send 600 requests per 60-second window. At the start of every window, clients that had been throttled retried at the same moment. We measured bursts of up to 4,800 requests per second in the first second of a window, while the average load was 900 requests per second. These bursts pushed the p99 latency of the gateway to 1,850 ms.

## What we changed
We replaced the fixed window with a token bucket per client. Each bucket holds up to 100 tokens and refills at 10 tokens per second, which keeps the long-run limit at 600 requests per minute. Bucket state lives in Redis; a Lua script performs the check-and-decrement atomically, so two gateway instances cannot spend the same token. When a request is rejected, the response includes a Retry-After header computed from the time until the next token.

## Results (two weeks after rollout, same traffic level)
- Peak load in any one second dropped from 4,800 to 1,400 requests per second.
- Gateway p99 latency dropped from 1,850 ms to 420 ms.
- The share of rejected requests rose from 2.1% to 2.6%, because clients can no longer exceed the limit at window edges.
- Redis CPU usage increased by 8 percentage points.

## Limitations
The token bucket does not help when many different clients start at the same moment; we still see short bursts after deployments. We have not tested the design with more than 50,000 active clients. Clients that ignore Retry-After still retry immediately.
