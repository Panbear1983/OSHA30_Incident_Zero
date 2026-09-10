#!/usr/bin/env bash
# Arm the secret-scan hooks for THIS clone. core.hooksPath is per-clone local config:
# it is not committed and does not survive a re-clone, so run this after every clone.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
chmod +x scripts/git-hooks/*
git config core.hooksPath scripts/git-hooks
echo "hooks armed: $(git config core.hooksPath)"
