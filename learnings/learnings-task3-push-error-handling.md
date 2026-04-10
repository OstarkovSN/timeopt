## Implementer
- CliRunner captures `result.output` from both stdout and stderr combined when `mix_stderr=True` (the default), so assertions on `result.output` will catch messages sent via `click.echo(..., err=True)`
- `raise SystemExit(1)` inside a CliRunner-invoked command sets `result.exit_code = 1` reliably; no need to use `sys.exit(1)` or `ctx.exit()`
- The `plan` command has no `--push` flag — push is triggered by a `click.confirm` prompt; tests must pass `input="y\n"` to confirm, not a CLI flag
