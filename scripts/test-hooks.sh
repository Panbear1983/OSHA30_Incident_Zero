#!/usr/bin/env bash
# Negative + positive controls for the secret-scan guardrail. The fake secrets are
# assembled at run time so this file itself never contains a matching literal.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
SCAN=scripts/git-hooks/_scan.sh
fails=0
expect() {  # expect <exit-code> <label> <STAGED_FILES> <line>
  local want="$1" label="$2" staged="$3" line="$4"
  STAGED_FILES="$staged" "$SCAN" printf '%s\n' "$line" >/dev/null 2>&1
  local got=$?
  if [ "$got" -eq "$want" ]; then echo "ok    $label"; else echo "FAIL  $label (exit $got, wanted $want)"; fails=1; fi
}
tg="1234567"; tg="${tg}89:AA"; tg="${tg}FakeFakeFakeFakeFakeFakeFakeFakeFake"
expect 1 "telegram token blocked"     ""                 "+TELEGRAM_BOT_TOKEN=\"$tg\""
expect 1 "openai-style key blocked"   ""                 "+key = 'sk-$(printf 'a%.0s' {1..40})'"
hp="/Use"; hp="${hp}rs/somebody/file"
expect 1 "home path blocked"          ""                 "+open('$hp')"
em="somebody@gma"; em="${em}il.com"
expect 1 "personal email blocked"     ""                 "+contact: $em"
expect 1 "progress.db blocked"        "data/progress.db" "x"
expect 1 "pdf blocked"                "guide.pdf"        "x"
expect 1 ".env blocked"               ".env"             "x"
expect 0 "plain code passes"          "osha_game/db.py"  "+print('hello')"
expect 0 "noreply email passes"       ""                 "+Panbear1983@users.noreply.github.com"
armed="$(git config core.hooksPath || true)"
if [ "$armed" = "scripts/git-hooks" ]; then echo "ok    hooks armed (core.hooksPath=$armed)"; else echo "FAIL  hooks NOT armed -- run scripts/install-hooks.sh"; fails=1; fi
exit $fails
