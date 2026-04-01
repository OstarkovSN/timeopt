**Task:** Process the user's brain dump and save tasks to timeopt.

**Input:** $ARGUMENTS

**Steps:**

1. **Split** — identify task fragments. Separate on commas, semicolons, newlines, "and also", "and then". Keep urgency markers and time references with their fragment.

2. **Get templates** — call `get_dump_templates` with the fragment list.

3. **Fill templates** — for each template returned, infer and fill all `"?"` fields:
   - `priority`: `"high"` for critical/deadline tasks; `"medium"` default; `"low"` for nice-to-haves
   - `urgent`: `true` if text contains "urgent", "ASAP", "before noon", "today", or has an imminent due date
   - `category`: `"work"`, `"personal"`, `"errands"`, or `"other"` from context
   - `effort`: `"small"` (≤30min), `"medium"` (~1hr), `"large"` (>1.5hr) from complexity
   - `due_at`: ISO8601 UTC if a specific time is mentioned (e.g. "before noon" → today `12:00:00Z`)
   - `due_event_offset_min`: negative int = minutes before a calendar event (e.g. `-30`)
   - Omit optional fields already absent from the template

4. **Save** — call `dump_tasks(tasks: [...])` with all filled templates as a batch.

5. **Confirm** — show what was saved:
   ```
   Added N tasks:
     #1-fix-login-bug             [work, high]
     #3-deploy-hotfix-before-noon [work, high, urgent, due today 12:00]
   ```

**Defaults:** effort unclear → call `get_config(key="default_effort")`. Category unclear → best guess, no confirmation needed.
