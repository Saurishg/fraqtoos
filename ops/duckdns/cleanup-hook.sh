#!/usr/bin/env bash
# Clears the DNS-01 TXT record after validation.
set -euo pipefail
CONF="/home/work/fraqtoos/ops/duckdns/duckdns.conf"
# shellcheck source=/dev/null
source "$CONF"
curl -s --max-time 30 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&txt=removed&clear=true" >/dev/null
