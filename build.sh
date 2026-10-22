#!/bin/sh
# Builds two standalone pages from src/gaon-word.html:
#   index.html                - loads JSZip and web fonts from the internet
#   gaon-word-offline.html    - JSZip built in, no internet needed (uses fonts installed on the PC)
set -e
cd "$(dirname "$0")"

HEAD='<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n</head>\n<body>\n'
TAIL='\n</body>\n</html>\n'

{ printf "$HEAD"; cat src/gaon-word.html; printf "$TAIL"; } > index.html

python3 - <<'EOF'
src = open('src/gaon-word.html', encoding='utf-8').read()
jszip = open('vendor/jszip.min.js', encoding='utf-8').read()
tag = '<script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>'
assert tag in src, 'JSZip script tag not found'
src = src.replace(tag, '<script>\n' + jszip + '\n</script>')
# Drop web font links; the font lists already fall back to fonts on the PC.
src = '\n'.join(l for l in src.split('\n') if 'fonts.googleapis.com' not in l and 'fonts.gstatic.com' not in l)
import re
assert not re.search(r'(src|href)="https?://', src), 'external resource left'
head = '<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n</head>\n<body>\n'
open('gaon-word-offline.html', 'w', encoding='utf-8').write(head + src + '\n</body>\n</html>\n')
EOF

echo "index.html, gaon-word-offline.html 생성 완료"
