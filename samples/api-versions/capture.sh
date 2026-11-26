#!/usr/bin/env bash
# Re-captures the sample responses in this folder. Run from anywhere; writes next to the script.
set -euo pipefail
cd "$(dirname "$0")"
f(){ curl -sSL -m 20 -A 'nParity/0.1 (https://github.com/oliviergerdi/aiskillsday)' \
  -H 'Accept: application/json' -o "$1" -w "$1 %{http_code}\n" "$2"; }
f petstore_v2_spec.json          https://petstore.swagger.io/v2/swagger.json
f petstore_v3_spec.json          https://petstore3.swagger.io/api/v3/openapi.json
f petstore_v2_findByStatus.json  "https://petstore.swagger.io/v2/pet/findByStatus?status=available"
f petstore_v3_findByStatus.json  "https://petstore3.swagger.io/api/v3/pet/findByStatus?status=available"
f wiki_restbase_summary.json     https://en.wikipedia.org/api/rest_v1/page/summary/Cat
f wiki_mwrest_bare.json          https://en.wikipedia.org/w/rest.php/v1/page/Cat/bare
f off_v2.json                    "https://world.openfoodfacts.org/api/v2/product/3017620422003?fields=product_name,brands"
f off_v3.json                    "https://world.openfoodfacts.org/api/v3/product/3017620422003?fields=product_name,brands"
echo "Done. Update captured_at in manifest.json if you re-ran this."
