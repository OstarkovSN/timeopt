## Implementer
- `get_all_config_api` (GET /api/config) already masked sensitive keys before this task — the fix only needed to extend masking to the HTML-rendering paths (config_page, config_partial) and the POST success path
- `str(KeyError("some message"))` produces `"'some message'"` (double-quoted) in Python — `e.args[0]` is the correct way to get the raw message without extra quotes
- The `_mask_sensitive` helper was introduced as a named private function rather than inline for reuse across both GET handlers — keeps masking logic DRY
- `test_post_config_unknown_key_error_message_not_double_quoted` passed before the fix because `core.set_config` raises `KeyError("Unknown config key: ...")` and the existing error text in the template did not literally contain the double-quoted pattern being tested; the assertion needed careful crafting to catch the `str(KeyError)` double-quoting bug specifically
