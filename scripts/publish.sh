#!/usr/bin/env bash
# Publishes this folder as the public repository <you>/qpcp-proofs.
# Run once, after scripts/bootstrap.sh has succeeded.
set -euo pipefail
cd "$(dirname "$0")/.."

REPO_NAME="qpcp-proofs"

if [ ! -f lake-manifest.json ] || [ ! -f lean-toolchain ]; then
  echo "Run scripts/bootstrap.sh first: lean-toolchain or lake-manifest.json is missing." >&2
  exit 1
fi

OWNER="$(gh api user --jq .login)"
echo "This will create the PUBLIC repository $OWNER/$REPO_NAME, push this folder,"
echo "create one issue per step, and turn on GitHub Pages."
read -r -p "Type yes to continue: " answer
[ "$answer" = "yes" ] || { echo "Stopped."; exit 1; }

echo "==> Filling in the owner name"
grep -rl "__OWNER__" --exclude-dir=.git --exclude-dir=.lake --exclude=publish.sh . \
  | while read -r f; do
      perl -pi -e "s/__OWNER__/$OWNER/g" "$f"
    done

echo "==> Committing"
[ -d .git ] || git init -b main
git add -A
git commit -m "Pilot scaffold: definitions, statements, checker, instructions"

echo "==> Creating the repository"
gh repo create "$OWNER/$REPO_NAME" --public --source . --push \
  --description "Open, machine-checked Lean 4 foundations around the quantum PCP conjecture"

echo "==> Creating labels and issues"
gh label create step --repo "$OWNER/$REPO_NAME" --color 1d76db \
  --description "An open lemma to prove" --force
gh label create claimed --repo "$OWNER/$REPO_NAME" --color fbca04 \
  --description "Someone is working on this step" --force
python3 scripts/create_issues.py

echo "==> Turning on GitHub Pages from /docs"
gh api -X POST "repos/$OWNER/$REPO_NAME/pages" \
  -f "source[branch]=main" -f "source[path]=/docs" >/dev/null \
  || echo "Could not enable Pages automatically. Enable it in Settings > Pages (branch main, folder /docs)."

echo "==> Done"
echo "Repository: https://github.com/$OWNER/$REPO_NAME"
echo "Site:       https://$OWNER.github.io/$REPO_NAME/"
echo "Next: protect the main branch as described in MAINTAINERS.md."
