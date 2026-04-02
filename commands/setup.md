# /timeopt:setup

Interactive setup wizard for timeopt. Walks through configuring LLM, CalDAV, and scheduling defaults.

## Steps

1. Call `get_config` (no key argument) to see what's currently configured.

2. Tell the user what's already configured and what's missing:
   - LLM: check if `llm_api_key` is set
   - CalDAV: check if `caldav_username` and `caldav_password` are set
   - Show current values for any configured items (mask passwords)

3. **LLM provider** — ask the user which provider they want to use:
   - **Anthropic**: ask for `llm_api_key` and `llm_model` (suggest `claude-sonnet-4-6`). Call `set_config` for each.
   - **OpenAI**: set `llm_base_url` to `https://api.openai.com/v1`, ask for `llm_api_key` and `llm_model` (suggest `gpt-4o`). Call `set_config` for each.
   - **Custom (OpenAI-compatible)**: ask for `llm_base_url`, `llm_api_key`, and `llm_model`. Call `set_config` for each.
   - **Skip**: move on.

4. **CalDAV** — ask "Would you like to configure CalDAV integration? (Yandex Calendar or any CalDAV server)"
   - If yes: ask for `caldav_url` (default: `https://caldav.yandex.ru`), `caldav_username`, `caldav_password`. Call `set_config` for each.
   - If no: skip.

5. **Scheduling defaults** — ask "Would you like to customize scheduling defaults?"
   - If yes: ask for `day_start` (default: `09:00`), `day_end` (default: `18:00`), `break_duration_min` (default: `15`), `default_effort` (default: `medium`). Call `set_config` for each.
   - If no: skip.

6. **Web UI** — ask "Would you like to open the timeopt web UI?"
   - If yes: tell the user to run `timeopt ui` in their terminal, or use the terminal tool to run it.
   - If no: skip.

7. Summarize what was configured.

## Notes

- Always mask passwords when showing current values (show `***` instead)
- If a value is already set, show the current value as the suggested default
- `set_config` accepts string values only — all config values are stored as strings
- Valid effort values: `small`, `medium`, `large`
