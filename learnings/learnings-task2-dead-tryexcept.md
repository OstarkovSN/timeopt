## Implementer
- `test_sync_with_caldav_error` tested the dead try/except behavior directly (mocked `get_events` to raise) — removing dead code requires updating tests that validated that code's behavior, not just removing the production code
- The existing test had a `side_effect = Exception(...)` mock asserting `"CalDAV error" in result.output` — this was the only test guarding the now-removed error message, so removing the dead code + updating the test was the complete fix
- CLAUDE.md correctly documents `get_events` never raises, but the test suite contradicted it — test and production behavior were misaligned before this fix
