**Task:** Generate and push a daily task schedule.

1. Call `get_plan_proposal(date?)`. The server computes the full schedule — free slots, Eisenhower sort, effort mapping, breaks, overflow deferral. No scheduling reasoning needed.

2. Display the proposal:
   ```
   Proposed schedule for [date]:
     10:00–11:00  #1-fix-login-bug    [Q2, medium]
     11:15–12:15  #3-deploy-hotfix    [Q1, medium]
     ...
   Deferred: #5-low-priority (not enough time today)
   ```

3. Confirm with the user: "Push this to your calendar?"

4. On confirmation: call `push_calendar_blocks(blocks: [...], date: "YYYY-MM-DD")` with the `blocks` array from the proposal.

5. Report success: "Pushed N blocks to Timeopt calendar."

If CalDAV is not configured, display the schedule but skip the push step and explain.

Input (optional date): $ARGUMENTS
