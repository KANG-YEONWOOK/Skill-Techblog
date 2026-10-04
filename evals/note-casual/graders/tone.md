---
type: regex
target: { source: file, path: article.md }
pattern: '[가-힣](습니다|ㅂ니다|입니다|됩니다|합니다)[.!](\s|$)'
flags: m
match: not_contains
---
