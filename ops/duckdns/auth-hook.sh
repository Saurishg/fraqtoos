#!/usr/bin/env bash
# certbot DNS-01 auth hook for DuckDNS.
#
# DNS-01 is used rather than HTTP-01 deliberately: HTTP-01 needs inbound port
# 80, which residential ISPs commonly block and which would mean opening
# another port. DNS-01 proves control by writing a TXT record instead, so
# nothing extra is exposed.
#
# certbot supplies CERTBOT_DOMAIN and CERTBOT_VALIDATION.
set -euo pipefail

CONF="/home/work/fraqtoos/ops/duckdns/duckdns.conf"   # DUCKDNS_TOKEN=..., DUCKDNS_SUBDOMAIN=...
# shellcheck source=/dev/null
source "$CONF"

resp=$(curl -s --max-time 30 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&txt=${CERTBOT_VALIDATION}")

if [ "$resp" != "OK" ]; then
  echo "duckdns TXT update failed: $resp" >&2
  exit 1
fi
# DuckDNS is fast, but Let's Encrypt may query a resolver that has the old
# record cached. A short wait here is far cheaper than a failed issuance.
sleep 30
