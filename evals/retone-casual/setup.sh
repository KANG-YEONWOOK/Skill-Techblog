#!/usr/bin/env bash
# 어투 변환 대상인 Default(합니다체) 글을 작업 폴더에 복사한다.
set -e
cp "$(dirname "$0")/article-default.md" ./article-default.md
