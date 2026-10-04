---
type: regex
target: { source: file, path: article.md }
pattern: '(^|[.?!]\s+)(그리고|그러나|그런데|그러므로|하지만|그래서|따라서),'
flags: m
match: not_contains
---
