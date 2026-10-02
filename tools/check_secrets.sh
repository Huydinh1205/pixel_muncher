#!/usr/bin/env bash
# Stop company data from being committed.
#
#   bash tools/check_secrets.sh          check the staged changes (used by the pre-commit hook)
#   bash tools/check_secrets.sh --all    check every tracked file
#
# Checks: words from .secret-patterns.local, private IP addresses, keys and
# passwords, blocked file types (imagery, documents, weights, archives) and
# files larger than 5 MB. Exit code 1 if anything is found.
set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Not inside a git repository."; exit 2; }

MODE="${1:-staged}"
MAX_BYTES=$((5 * 1024 * 1024))
SELF_FILES="tools/check_secrets.sh tools/secret-patterns.example"
BLOCKED_EXT='\.(tif|tiff|jp2|ecw|las|laz|e57|ply|obj|dae|kml|kmz|shp|gpkg|geojson|csv|docx?|pdf|xlsx?|pptx|pt|pth|ckpt|onnx|h5|safetensors|zip|tar|gz|7z|rdp|pem|key|p12|pfx|kdbx|sqlite3|db|log)$'

BUILTIN_PATTERNS=(
  '(^|[^0-9])10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)'
  '(^|[^0-9])192\.168\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)'
  '(^|[^0-9])172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'AccountKey='
  'SharedAccessSignature='
  'DefaultEndpointsProtocol='
  '[?&]sig=[A-Za-z0-9%]{20,}'
  'ghp_[A-Za-z0-9]{30,}'
  'AKIA[0-9A-Z]{16}'
  '(password|passwd|pwd|api[_-]?key|secret[_-]?key|access[_-]?token)[[:space:]]*[:=][[:space:]]*["'"'"']?[^"'"'"'[:space:]<>*]{4,}'
)

PATTERNS=("${BUILTIN_PATTERNS[@]}")
if [ -f .secret-patterns.local ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%$'\r'}"
    case "$line" in ''|'#'*|*'<'*'>'*) continue ;; esac   # skip blanks, comments, unfilled examples
    PATTERNS+=("$line")
  done < .secret-patterns.local
else
  echo "note: .secret-patterns.local not found. Only built-in checks run."
  echo "      cp tools/secret-patterns.example .secret-patterns.local  and add your company words."
fi

if [ "$MODE" = "--all" ]; then
  FILES=$(git ls-files)
  read_file() { cat -- "$1" 2>/dev/null; }
  file_size() { wc -c < "$1" 2>/dev/null | tr -d ' '; }
else
  FILES=$(git diff --cached --name-only --diff-filter=ACMR)
  read_file() { git show ":$1" 2>/dev/null; }
  file_size() { git cat-file -s ":$1" 2>/dev/null; }
fi

problems=0
report() { echo "  BLOCKED  $1"; problems=$((problems + 1)); }

while IFS= read -r f; do
  [ -z "$f" ] && continue
  case " $SELF_FILES " in *" $f "*) continue ;; esac
  if echo "$f" | grep -Eiq "$BLOCKED_EXT"; then report "$f: file type is not allowed in the repository"; continue; fi
  size=$(file_size "$f"); size=${size:-0}
  if [ "$size" -gt "$MAX_BYTES" ]; then report "$f: larger than 5 MB ($size bytes)"; continue; fi
  # skip binary files (icons, screenshots) for the text checks
  n_all=$(read_file "$f" | head -c 8000 | wc -c)
  n_txt=$(read_file "$f" | head -c 8000 | LC_ALL=C tr -d '\000' | wc -c)
  [ "$n_all" != "$n_txt" ] && continue
  for p in "${PATTERNS[@]}"; do
    hits=$(read_file "$f" | grep -Ein -e "$p" 2>/dev/null | head -3)
    if [ -n "$hits" ]; then
      while IFS= read -r h; do report "$f:${h%%:*}: matches '$p'"; done <<< "$hits"
    fi
  done
done <<< "$FILES"

if [ "$problems" -gt 0 ]; then
  echo
  echo "Commit stopped: $problems problem(s). Remove the data, or unstage the file with: git restore --staged <file>"
  echo "If a match is a false alarm, change the text or the pattern. (git commit --no-verify skips this check.)"
  exit 1
fi
echo "check_secrets: no company data found ($( [ "$MODE" = "--all" ] && echo 'all tracked files' || echo 'staged changes'))."
