---
type: regex
target: { source: file, path: article.md }
pattern: '[가-힣][^\n—]{0,15}—[^\n—]{0,15}[가-힣]|[가-힣];'
match: not_contains
---
