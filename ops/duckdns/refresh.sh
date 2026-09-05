#!/usr/bin/env bash
# Keep the DuckDNS record alive and correct.
#
# Two failure modes this covers, both silent:
#   1. DuckDNS drops hostnames that go un-updated for long enough. Losing
#      fraqtos.duckdns.org would take down all five service URLs and the
#      certificate renewal with them.
#   2. The IP is static today, but a plan change or equipment swap at the ISP
#      would leave the record pointing at an address that is no longer ours,
#      with nothing to notice.
#
# Exit 4 (degraded) if the record and the live public IP disagree after an
# update - the fleet contract turns that into an alert.
set -uo pipefail

CONF="/home/work/fraqtoos/ops/duckdns/duckdns.conf"
# shellcheck source=/dev/null
source "$CONF"

ip=$(curl -s --max-time 20 https://api.ipify.org)
if [ -z "$ip" ]; then
  echo "could not determine the public IP — skipping (not a DuckDNS fault)"
  exit 0
fi

resp=$(curl -s --max-time 30 \
  "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=${ip}")
if [ "$resp" != "OK" ]; then
  echo "duckdns update FAILED: ${resp:-<empty>}"
  exit 1
fi

# Verify against a public resolver rather than the local cache, which would
# happily confirm a stale answer.
sleep 5
resolved=$(dig +short "@1.1.1.1" "${DUCKDNS_SUBDOMAIN}.duckdns.org" | tail -1)
if [ "$resolved" != "$ip" ]; then
  echo "MISMATCH: ${DUCKDNS_SUBDOMAIN}.duckdns.org resolves to ${resolved:-nothing}, public IP is ${ip}"
  exit 4
fi

echo "ok — ${DUCKDNS_SUBDOMAIN}.duckdns.org -> ${ip}"
