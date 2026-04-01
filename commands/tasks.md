**Task:** Show the user's current tasks from timeopt.

Call `list_tasks()`. If $ARGUMENTS contains filters (e.g. `--done`, `--priority high`, `--category work`), pass them as parameters.

Format the output:
```
Pending (N)
  #1-display-id          [category, priority]
  #2-display-id          [category, priority, urgent, due YYYY-MM-DD]
  ...

Being handled by Claude (N)
  #X-display-id          [category, priority — last note preview]
  ...
```

Tasks appear in Eisenhower order: Q1 (urgent+important) → Q2 (important) → Q3 (urgent) → Q4 (neither). Show the last line of `notes` for delegated tasks (truncated to 60 chars).
