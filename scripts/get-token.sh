#!/usr/bin/env bash
# Emit `export` lines for a Sigma bearer token + base URL.
# Usage:  eval "$(SIGMA_CLIENT_ID=... SIGMA_CLIENT_SECRET=... ./get-token.sh)"
#
# Reads creds from the environment (preferred) or, if absent, from a
# credentials file passed as $1 (one `KEY=VALUE` per line:
# SIGMA_CLIENT_ID, SIGMA_CLIENT_SECRET, optional SIGMA_BASE_URL).
#
# Read-only assessment posture: this token is only ever used for GETs.
set -euo pipefail

if [[ -n "${1:-}" && -f "${1:-}" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$1"; set +a
fi

BASE="${SIGMA_BASE_URL:-https://api.us-a.aws.sigmacomputing.com}"
CID="${SIGMA_CLIENT_ID:?set SIGMA_CLIENT_ID (env or creds file)}"
CSEC="${SIGMA_CLIENT_SECRET:?set SIGMA_CLIENT_SECRET (env or creds file)}"

# Sigma's token endpoint intermittently 400s ("Invalid access/refresh token")
# under bursty requests — retry with backoff.
TOKEN=""
for attempt in 1 2 3 4 5; do
  RESP=$(curl -s -X POST "$BASE/v2/auth/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${CID}&client_secret=${CSEC}")
  TOKEN=$(printf '%s' "$RESP" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null || true)
  [[ -n "$TOKEN" ]] && break
  sleep $((attempt * 2))
done

if [[ -z "$TOKEN" ]]; then
  echo "# get-token.sh: auth failed after retries — raw response below" >&2
  printf '%s\n' "$RESP" | head -c 500 >&2
  exit 1
fi

echo "export SIGMA_API_TOKEN=${TOKEN}"
echo "export SIGMA_BASE_URL=${BASE}"
