---
type: regex
target: { source: file, path: article.md }
pattern: '[가-힣](해요|어요|아요|에요|예요|죠)[.!](\s|$)'
flags: m
match: not_contains
---
