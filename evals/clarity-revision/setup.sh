#!/usr/bin/env bash
set -euo pipefail
case_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$case_dir/article.md" ./article.md
cp "$case_dir/source.md" ./source.md
