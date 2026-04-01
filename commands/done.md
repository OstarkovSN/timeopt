**Task:** Mark tasks as done in timeopt.

**Input:** $ARGUMENTS (partial task names or IDs, space-separated)

For each word/phrase in the input:

1. Call `fuzzy_match_tasks(query: "<phrase>")`.

2. **Ambiguity rules** (get thresholds with `get_config()`):
   - Score < `fuzzy_match_min_score` (default 80): ask which task was meant
   - Gap between top two scores < `fuzzy_match_ask_gap` (default 10): ask to confirm
   - Otherwise: act silently

3. Call `mark_done(task_ids: ["<uuid>", ...])` with all confirmed IDs.

4. Confirm:
   ```
   Done:
     ✓ #1-fix-login-bug
     ✓ #4-prep-slides
   ```
