# API version samples

Captured responses from public, no-auth APIs where an old and a new version are both reachable. Use them as offline fixtures for comparing API versions. `manifest.json` is the source of truth for pairings, source URLs and capture times (UTC).

| Pair | Change type |
|---|---|
| `petstore_spec` | Swagger 2.0 -> OpenAPI 3.0.x, different hosts |
| `petstore_findByStatus` | Same endpoint, different data and behaviour |
| `openfoodfacts_product` | v2 -> v3, new response envelope |
| `wikipedia_page` | RESTBase -> MediaWiki REST, different URL tree and payload |

## Caveats
- Petstore v2 is a shared public test instance. Its records are junk (int64-overflow IDs, placeholder strings). Do not treat that as a real v2 -> v3 behaviour change.
- Wikipedia and Open Food Facts content changes over time. These files are snapshots; a later live fetch will differ without any API change.
- Verify the old endpoints still respond before relying on them live. Snapshots exist so the demo does not depend on that.

## Licences and attribution
- Swagger Petstore: Apache 2.0.
- Wikipedia: CC BY-SA 4.0, https://en.wikipedia.org (page "Cat").
- Open Food Facts: data under ODbL, content under CC BY-SA, https://world.openfoodfacts.org.

## Re-capturing
`./capture.sh` re-fetches everything into this folder. Update `captured_at` in `manifest.json` afterwards.
