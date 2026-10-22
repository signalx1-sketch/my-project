#!/bin/sh
# Wraps the page body in src/ into a standalone index.html you can open directly in a browser.
set -e
cd "$(dirname "$0")"
{
  printf '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n</head>\n<body>\n'
  cat src/gaon-word.html
  printf '\n</body>\n</html>\n'
} > index.html
echo "index.html 생성 완료"
