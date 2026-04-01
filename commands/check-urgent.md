**Task:** Check for urgent tasks that can be delegated to Claude, then delegate them.

1. Call `classify_tasks()` to run Eisenhower classification.

2. Find Q3 tasks: `urgent=true` AND `priority="low"` AND `status="pending"`.

3. For each Q3 task:
   a. Call `mark_delegated(task_id: "<id>", notes: "Starting delegation")`.
   b. Create a TodoWrite entry: "Delegate: [task title]".
   c. Attempt the task using available tools. Budget: check `get_config(key="delegation_max_tool_calls")`.
   d. Progress: call `update_task_notes(task_id: "<id>", notes: "<progress>")` as you work.
   e. On success: call `mark_done(task_ids: ["<id>"])` + final `update_task_notes` with summary.
   f. On failure or budget exceeded: call `return_to_pending(task_id: "<id>", notes: "<reason>")`.

4. Report:
   ```
   Delegated 1 task:
     #6-reply-to-accountant → handled successfully

   Could not delegate:
     #7-book-flight → returned to queue (no booking tool available)
   ```

If no Q3 tasks: "No urgent tasks to delegate. All clear."
