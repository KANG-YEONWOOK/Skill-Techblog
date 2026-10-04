---
type: regex
target: { source: file, path: article.md }
pattern: '단순(한|히) [^.\n]{0,40}(을|를) 넘어'
match: not_contains
---
