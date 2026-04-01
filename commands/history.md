**Task:** Show completed tasks from timeopt.

Call `list_tasks(status: "done", include_old_done: true)`.

If $ARGUMENTS contains:
- `--today`: filter to tasks with `done_at` matching today's date
- `--week`: filter to tasks completed in the last 7 days
- `--all` or empty: show all completed tasks

Display:
```
Completed (N)
  #1-fix-login-bug    2026-03-27  fix login bug
  #4-prep-slides      2026-03-26  prep slides for Thursday
```

Most recently completed first.
