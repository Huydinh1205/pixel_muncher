#!/usr/bin/env bash
# Run tools/check_secrets.sh automatically before every commit in this clone.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Run this inside the git repository (git init first)."; exit 1; }
HOOK="$ROOT/.git/hooks/pre-commit"
mkdir -p "$(dirname "$HOOK")"
cat > "$HOOK" <<'HOOK'
#!/usr/bin/env bash
exec bash "$(git rev-parse --show-toplevel)/tools/check_secrets.sh"
HOOK
chmod +x "$HOOK"
echo "Installed pre-commit hook: $HOOK"
[ -f "$ROOT/.secret-patterns.local" ] || echo "Next: cp tools/secret-patterns.example .secret-patterns.local  and add your company words."
