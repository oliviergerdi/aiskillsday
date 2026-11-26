The Swagger 2.0 Petstore (v2) is being replaced by the OpenAPI 3.0 Petstore (v3).

- Keep the same resources and paths.
- The two servers run on separate databases, so the actual records (names, statuses, counts) can differ.
- `GET /user/login` and `GET /user/logout` may return strings instead of JSON objects.
- New fields may be added. All other existing response shapes should stay the same.
