#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="${REPO_NAME:-aptv-sports-source}"

cd "$ROOT"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required. Install GitHub CLI first." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not logged in. Run: gh auth login" >&2
  exit 1
fi

python3 update_sports.py

if [ ! -d .git ]; then
  git init
  git branch -M main
fi

git add .gitignore README.md sports.m3u sports_sources.json sports_update_report.txt update_sports.py serve_sources.py com.q.aptv-sports-source.plist
git commit -m "Update APTV sports source" || true

OWNER="$(gh api user --jq .login)"

if ! git remote get-url origin >/dev/null 2>&1; then
  if gh repo view "$OWNER/$REPO_NAME" >/dev/null 2>&1; then
    git remote add origin "https://github.com/$OWNER/$REPO_NAME.git"
  else
    gh repo create "$OWNER/$REPO_NAME" --public --source=. --remote=origin --push
  fi
fi

git push -u origin main

if gh api "repos/$OWNER/$REPO_NAME/pages" >/dev/null 2>&1; then
  gh api -X PUT "repos/$OWNER/$REPO_NAME/pages" \
    -f 'source[branch]=main' \
    -f 'source[path]=/'
else
  gh api -X POST "repos/$OWNER/$REPO_NAME/pages" \
    -f 'source[branch]=main' \
    -f 'source[path]=/'
fi

echo
echo "APTV URL:"
echo "https://$OWNER.github.io/$REPO_NAME/sports.m3u"
