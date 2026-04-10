# Task A: Guard "***" placeholder + fix get_all_config_api + resolve_calendar_reference KeyError

## Implementer

- Issues 1, 2, and 4 were already fixed in ui_server.py and their tests were already passing when the task began
- Issue 3 (KeyError in resolve_calendar_reference) was the only fix needed: line 278 in server.py caught only `ValueError`, not `KeyError` from `core.get_config()`
- Test `test_resolve_calendar_reference_keyerror_for_config_uses_default` already existed but was failing before the fix
- [STALE]: CLAUDE.md src/timeopt/ section states "Config-related tools that can raise `KeyError` (not `ValueError`) must catch and convert separately" but `resolve_calendar_reference` was only catching `ValueError`, leaving the KeyError path unhandled
- The test suite has a pre-existing failure in `test_plan_with_caldav_error` caused by cli.py changes (removal of try/except) that are part of Task B, not Task A — this is unrelated to the fixes here
