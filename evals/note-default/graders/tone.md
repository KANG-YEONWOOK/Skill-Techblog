---
type: regex
target: { source: file, path: article.md }
pattern: '((?<!필)(?<!중)(?<!주)(?<!개)(?<!수)(?<!강)(?<!소)요|죠)[.!](\s|$)'
flags: m
match: not_contains
---
