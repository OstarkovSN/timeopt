## Implementer
- `test_openai_compatible_client_passes_max_tokens` must use `patch("timeopt.llm_client.openai.OpenAI", ...)` (attribute path on the module), not `patch("timeopt.llm_client.openai")` — patching the whole module prevents the class-level mock from being used correctly by `OpenAICompatibleClient.__init__`
- `call_args.kwargs` (attribute access) works in Python 3.8+ unittest.mock; using `call_args[1]` is the older style but both work — the plan's test used `.kwargs` attribute which is cleaner
- The `test_done_command_bad_fuzzy_config_uses_default` weak assertion (`A or B or C`) was logically always True — replacing with `exit_code == 0` actually tests the intended behavior
- `server.get_config` catches `KeyError` (not `ValueError`) — this is called out in CLAUDE.md but easy to miss when writing the fix; the invariant "all error responses include ok:False" is separate from the exception type handling
