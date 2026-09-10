#!/usr/bin/env bash
# INCIDENT ZERO — OSHA 30 dashboard: Train / Look Up / Inspect / Interview.
# Space-safe launcher (this folder's name contains a space and a trailing period).
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
VENV="$SCRIPT_DIR/venv"
PYTHON_BIN="${OSHA30_PYTHON:-python3}"

usage() {
  cat <<'USAGE'
INCIDENT ZERO — OSHA 30 dashboard

  ./dashboard.sh                 open the dashboard (Train / Look Up / Inspect / Interview)
  ./dashboard.sh lookup WORDS    find a rule, number, standard, or term (+ page) from the terminal
  ./dashboard.sh build           extract PDFs + build the question bank and fact base
  ./dashboard.sh ai [--backend ollama|agy] [--module N] [--force]
                                 add AI scenario questions (build-time only)
  ./dashboard.sh reset NAME      wipe one profile (asks for confirmation)
  ./dashboard.sh status          health check: venv, banks, profiles, Ollama
USAGE
}

die() { printf '%s\n' "$@" >&2; exit 127; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 \
  || die "error: '$PYTHON_BIN' not found." "Set OSHA30_PYTHON to a Python >= 3.11 interpreter."
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "error: $("$PYTHON_BIN" --version 2>&1) is too old." "Need Python >= 3.11 (set OSHA30_PYTHON)."

REQS="$SCRIPT_DIR/requirements.txt"
STAMP="$VENV/.reqs.sha256"
want="$(shasum -a 256 "$REQS" | awk '{print $1}')"
have=""
[ -f "$STAMP" ] && have="$(cat "$STAMP")"
if [ ! -x "$VENV/bin/python" ] || [ "$want" != "$have" ]; then
  echo "[dashboard] preparing venv (first run takes a minute)..."
  "$PYTHON_BIN" -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q -r "$REQS"
  printf '%s' "$want" > "$STAMP"
fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
[ -n "${LANG:-}" ] || export LANG=en_US.UTF-8

cmd="${1:-run}"
[ $# -gt 0 ] && shift || true
case "$cmd" in
  run)            exec "$VENV/bin/python" -m osha_game run "$@" ;;
  build)          exec "$VENV/bin/python" -m osha_game build "$@" ;;
  lookup|find)    exec "$VENV/bin/python" -m osha_game lookup "$@" ;;
  ai)             exec "$VENV/bin/python" -m osha_game ai "$@" ;;
  reset)          exec "$VENV/bin/python" -m osha_game reset "$@" ;;
  status|doctor)  exec "$VENV/bin/python" -m osha_game status "$@" ;;
  help|-h|--help) usage ;;
  *)              usage >&2; exit 2 ;;
esac
