# Claude Code Plugin — Repository Structure Reference

A Claude Code plugin is a Git repository (or a subdirectory inside one) that bundles
slash commands, agents, skills, hooks, and MCP configuration into a single installable
unit. The canonical structure comes from Anthropic's own plugin examples and the
`/plugin` command that installs them.

---

## Minimal / Required Layout

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json          # ← REQUIRED: plugin identity & metadata
└── README.md                # strongly recommended
```

`plugin.json` is the only file Claude Code actually requires. Everything else is opt-in.

### `plugin.json` skeleton

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "What this plugin does in one sentence.",
  "author": "your-github-handle",
  "license": "MIT"
}
```

---

## Full Layout (all features)

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json          # plugin identity
│
├── CLAUDE.md                # context injected into every session that loads this plugin
│                            # (coding standards, domain vocabulary, invariants)
│
├── commands/                # slash commands  (legacy path, still supported)
│   ├── my-command.md        # → /my-command
│   ├── ns/
│   │   └── sub.md           # → /ns:sub
│   └── ...
│
├── skills/                  # preferred modern path for commands + auto-invoked skills
│   ├── my-skill/
│   │   ├── SKILL.md         # frontmatter (name, description) + instructions
│   │   └── supporting/      # optional: scripts, templates, data files used by the skill
│   └── ...
│
├── agents/                  # specialized subagents
│   ├── my-agent.md          # agent definition (system prompt, tools, model hint)
│   └── ...
│
├── hooks/                   # event-driven automation scripts
│   ├── pre-tool-use.sh      # runs before every tool call
│   ├── post-tool-use.sh
│   ├── session-start.sh
│   └── stop.sh
│
├── .mcp.json                # MCP server declarations for this plugin's scope
│
└── README.md
```

---

## Component Details

### `commands/` vs `skills/`

| | `commands/` | `skills/` |
|---|---|---|
| Status | Legacy, still works | Preferred (modern) |
| User-invokable | Yes (`/command-name`) | Yes (`/skill-name`) |
| Auto-invoked by Claude | No | Yes (via `description` frontmatter) |
| Supporting files | No | Yes (sibling files in the skill dir) |
| Disable model invocation | No | Yes (`disable-model-invocation: true`) |

Both paths produce identical `/slash-commands` from the user's perspective.

### `SKILL.md` frontmatter

```markdown
---
name: my-skill
description: >
  Use this when the user wants to do X. Front-load the key use case — descriptions
  are capped at 250 characters in Claude's context budget.
allowed-tools: Read, Bash(git status:*)
model: claude-sonnet-4-6          # optional model hint
disable-model-invocation: false   # set true to hide from Claude's auto-selection
user-invocable: true              # controls menu visibility only
---

# Instructions

Everything below the frontmatter is what Claude reads and follows when the skill fires.
```

### `agents/`

Each `.md` file defines a subagent Claude can spawn. Typical frontmatter:

```markdown
---
name: my-agent
description: Specialized agent for doing Y.
model: claude-sonnet-4-6
allowed-tools: Read, Write, Bash
---

You are an expert in Y. When invoked, you...
```

### `hooks/`

Hooks are executable scripts triggered at lifecycle events. They receive JSON on stdin.

| File name | Event |
|---|---|
| `pre-tool-use.sh` | Before any tool call |
| `post-tool-use.sh` | After any tool call |
| `session-start.sh` | Session initialization |
| `stop.sh` | Claude is about to stop / exit |

Scripts should be `chmod +x`. They can exit non-zero to block the triggering action
(for `PreToolUse`).

### `.mcp.json`

Declares MCP servers scoped to this plugin. Format mirrors the global `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "my-mcp-package"],
      "env": { "MY_API_KEY": "${MY_API_KEY}" }
    }
  }
}
```

---

## Project-scoped vs Plugin-scoped

| Location | Scope | Version-controlled? |
|---|---|---|
| `.claude/skills/` | Project only | Yes (committed to the project repo) |
| `.claude/commands/` | Project only (legacy) | Yes |
| `~/.claude/skills/` | All projects on this machine | No (personal) |
| Plugin repo `skills/` | Wherever plugin is installed | Yes (in the plugin repo) |

If you're building a **personal task management plugin** (not tied to one codebase),
keep it in its own repo and install it globally — changes propagate to every project.

---

## Marketplace Support

A repository becomes a **marketplace** by adding `.claude-plugin/marketplace.json`:

```json
{
  "plugins": [
    { "name": "my-plugin", "path": ".", "description": "One-liner." }
  ]
}
```

Users can then add it with:

```
/plugin marketplace add your-github-org/your-repo
```

---

## `.gitignore` Recommendations

```gitignore
# secrets — never commit these
.env
*.key
*.pem

# Claude's local session state (not plugin files)
.claude/session*
.claude/cache/

# OS noise
.DS_Store
Thumbs.db
```

---

## Minimal Task Manager Plugin — Concrete Example

```
task-manager-plugin/
├── .claude-plugin/
│   └── plugin.json
│
├── CLAUDE.md                    # domain context: Eisenhower matrix rules, CalDAV notes
│
├── skills/
│   ├── brain-dump/
│   │   ├── SKILL.md             # /brain-dump — free-form intake, classifies tasks
│   │   └── classify-prompt.txt  # supporting prompt template
│   ├── prioritize/
│   │   └── SKILL.md             # /prioritize — shows Eisenhower matrix view
│   └── sync-calendar/
│       ├── SKILL.md             # /sync-calendar — push tasks to CalDAV
│       └── caldav_push.py       # Python helper called by the skill via Bash tool
│
├── hooks/
│   └── session-start.sh         # loads pending task count into context on startup
│
├── .mcp.json                    # optional: MCP server for CalDAV if you go that route
│
└── README.md
```

---

## Key Rules to Remember

1. **`plugin.json` is the only required file.** Everything else is additive.
2. **Prefer `skills/` over `commands/`** — skills get auto-invocation and supporting files.
3. **`CLAUDE.md` is context, not commands** — use it for invariants Claude should always know.
4. **Hooks are scripts, not markdown** — they run as subprocesses and must be executable.
5. **Secrets go in env vars, never in committed files.** Reference them as `${VAR_NAME}` in `.mcp.json`.
6. **Skill descriptions are capped at 250 chars** — front-load the trigger phrase.
