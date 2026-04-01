**Task:** Sync calendar event bindings for timeopt tasks.

1. Call `sync_calendar()`. This runs both sync phases server-side:
   - Algorithmic: updates `due_at` for tasks bound to moved events
   - Re-binding: attempts to match previously unresolved calendar references

2. Display results:
   ```
   Updated 2 task due dates:
     #5-prep-report    Wed 14:00 → Thu 10:00
     #8-send-invoice   Wed 14:00 → Thu 10:00

   Resolved 1 previously unresolved task:
     #9-board-prep → bound to "Board Meeting" Apr 15
   ```

3. For tasks in `unresolved_remaining`: try to estimate a `due_at` from the task title and world knowledge. If you cannot estimate, ask: "When do you expect '[event name]'?" — they can give a date or say Skip.

If CalDAV is not configured, explain setup: `timeopt config set caldav_username <user>` etc.
