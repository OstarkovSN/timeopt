## Implementer
- `click.exceptions.Abort` is a subclass of `BaseException`, not `Exception` — broad `except Exception` silently swallows it, which is why it must be re-raised before the broad handler
- `click.exceptions.Exit` is also a `BaseException` subclass and must be explicitly re-raised for the same reason
- `_parse_time` in planner.py raises `ValueError` (via `datetime.fromisoformat`) on invalid time strings — it is not guarded and was not previously documented as a failure point for bad config
- `core.get_config` raises `KeyError` for unknown keys (not `ValueError`) — the existing CLAUDE.md documents this, but the `except ValueError` guard in `try_resolve_unresolved` was written inconsistently with that contract
- When patching `timeopt.core.get_config` with `side_effect=KeyError(...)`, the mock is called from inside `try_resolve_unresolved` which calls `get_config` directly — patching at module level (`timeopt.core.get_config`) works correctly
