The rewrite makes these changes. Nothing else should change.

- Customers move from `GET /customers/{id}` to `GET /clients/{clientId}`.
- The customer field `fullName` is renamed to `name`.
- The deprecated customer field `legacyCode` is dropped.
- Creating an order (`POST /orders`) returns 201 instead of 200.
- Error responses are being tidied up.
