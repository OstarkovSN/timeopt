# Task B: Remove Last Dead Try/Except + Narrow Server.push_calendar_blocks

## Implementer
- cli.py plan command had its dead try/except already removed in a previous fix (uses `if caldav:` guard now)
- test_plan_with_caldav_error was testing the OLD behavior (exception handling) that no longer exists
- CalDAVClient.get_events() never raises exceptions — catches all exceptions internally and returns [] on failure
- Removed test was mocking CalDAV to raise Exception, but since get_events never raises, the mock expectation was invalid
- Fixed server.push_calendar_blocks to only catch RuntimeError (not broad Exception) matching CLI pattern
- Changed log level from exception() to error() for CalDAV write failures (exception() logs stack trace, not needed here)
