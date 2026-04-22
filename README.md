# 🌀 vibeharness

A medium-weight terminal coding agent in the spirit of **Claude Code** and
**GitHub Copilot CLI** — built in ~1.5k lines of Python so you can actually
read it end-to-end.

Give it an Anthropic API key and a task. It reads your files, edits them with
surgical-replace semantics, runs shell commands in persistent sessions, and
keeps going until the job is done (or it asks for help).

```bash
$ vibe run "add a docstring to every public function in src/utils.py"
```

```
╭─ vibeharness · model: claude-sonnet-4-5 · cwd: ~/proj ─╮
│ Type your task. Ctrl-C to exit.                        │
╰────────────────────────────────────────────────────────╯
▸ read_file src/utils.py
╭─ 📄 src/utils.py ─╮
│ def slugify(s):   │
│     return ...    │
╰───────────────────╯
▸ edit_file src/utils.py
╭─ ✎ edit src/utils.py (1) ─╮
│ -def slugify(s):           │
│ +def slugify(s):           │
│ +    """Lowercase + …"""   │
╰────────────────────────────╯
Added docstrings to all 4 public functions.
                                            tokens: in=2103 out=412
```

---

## Why another agent harness?

The big ones — Claude Code, Copilot CLI, Aider — are excellent, but they're
either closed-source, large, or both. **vibeharness** exists to be:

- **Hackable.** Every file fits on a screen. The agent loop is ~80 lines.
- **Educational.** A worked example of what a "medium" agent harness needs:
  tool registry, schema generation, permission policy, persistent shells,
  context compaction, session persistence, streaming UI.
- **Useful.** It's a real tool. Use it for real coding tasks.

If you want to know what's between "100-line toy" and "Claude Code" — read
this repo top-to-bottom.

---

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/jeanlag1/vibeharness
cd vibeharness
pip install -e .                   # core
pip install -e ".[openai]"         # optional OpenAI provider
pip install -e ".[dev]"            # tests
```

Set an API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...
```

---

## Usage

### Interactive REPL

```bash
vibe
```

Inside the REPL:
- type a task to send it to the agent
- `/save` — write the session to `~/.vibe/sessions/`
- `/compact` — summarize older turns to free context
- `/clear` — wipe history
- `/exit` — quit

### One-shot

```bash
vibe run "find every TODO in src/ and group them by file"
vibe run "write a pytest fixture for our database client" --auto
```

### Resume a session

```bash
vibe sessions                 # list
vibe --resume a1b2c3d4e5      # pick up where you left off
```

### Inspect tools

```bash
vibe tools
```

### Flags

| flag | meaning |
|---|---|
| `--provider {anthropic\|openai}` | LLM provider (default: anthropic) |
| `--model MODEL` | override model id |
| `--permissions {auto\|ask\|deny}` | permission policy for mutating tools |
| `--auto` / `-y` | shortcut for `--permissions=auto` |
| `--resume ID` | restore a saved session |
| `--max-iters N` | cap loop iterations per turn (default 50) |

### Config file

`~/.vibe/config.toml` (TOML, all keys optional):

```toml
provider = "anthropic"
model = "claude-sonnet-4-5"
permission_mode = "ask"
max_iters = 50
max_context_tokens = 120000
```

Env-var overrides: `VIBE_PROVIDER`, `VIBE_MODEL`, `VIBE_PERMISSION_MODE`.

---

## Architecture

```
vibeharness/
├── agent.py          ← main loop: LLM ↔ tools ↔ permissions
├── llm.py            ← provider abstraction (Anthropic, OpenAI)
├── prompts.py        ← system prompt
├── permissions.py    ← auto / ask / deny policy
├── context.py        ← token counting + auto-compaction
├── session.py        ← JSON save/resume
├── ui.py             ← Rich panels: text, diffs, bash output
├── config.py         ← TOML config + env overrides
├── cli.py            ← Typer entrypoint
└── tools/
    ├── __init__.py   ← Tool registry + JSON schema generation
    ├── files.py      ← read / write / edit / grep / glob / list_dir
    └── bash.py       ← persistent PTY shells + background processes
```

### The loop

```
user_input
   │
   ▼
┌──────────────────────────────────────────┐
│  while True:                             │
│    turn = llm.complete(messages, tools)  │
│    record turn → messages                │
│    if not turn.tool_calls: break ←──────┼── final assistant response
│    for call in turn.tool_calls:          │
│        if mutating: permissions.check()  │
│        result = dispatch(call)           │
│    record results → messages             │
└──────────────────────────────────────────┘
```

### Tools

| tool | mutating | description |
|---|---|---|
| `read_file` | – | read text file with offset/limit |
| `write_file` | ✎ | create/overwrite with content |
| `edit_file` | ✎ | exact-string replace, fails on ambiguous match |
| `grep` | – | recursive regex search (skips `.git`, `node_modules`, …) |
| `glob_files` | – | glob with `**` support |
| `list_dir` | – | directory listing |
| `bash` | ✎ | shell command in a **persistent** session |
| `bash_background` | ✎ | start a long-running process, returns `bg_id` |
| `bash_read` | – | read accumulated output from a background process |
| `bash_stop` | ✎ | stop a background process |

`edit_file` uses Claude-Code-style strict matching: it requires a unique
substring match by default and fails loudly if `old` appears more or fewer
times than `count`. This is what makes "make a small targeted change" reliable.

The bash tool uses `pexpect` for a real PTY, so `cd`, `export`, shell
functions, and prompts all work and persist across calls with the same
`session_id`.

### Permissions

Three modes:
- `auto` — approve everything (great for `--auto` runs and CI)
- `ask`  — prompt before each mutating tool; `a` allows that tool for the
  rest of the session
- `deny` — refuse all mutating tools (read-only inspection mode)

### Context compaction

When `count_tokens(messages) > max_context_tokens * 0.75`, the harness asks
the model to summarize everything before the last 6 turns into a ~300-word
brief, and replaces the older messages with that single summary. This keeps
long sessions from blowing out the context window.

### Sessions

Saved as plain JSON to `~/.vibe/sessions/{id}.json` after every turn.
`vibe --resume ID` rehydrates `messages` and token counters.

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

There are 36 tests, none of which need an API key. They use a `FakeProvider`
to exercise the agent loop deterministically.

```
$ pytest -q
....................................                                     [100%]
36 passed
```

---

## What's intentionally NOT here

To stay "medium," vibeharness deliberately omits things you'd want in a
production-grade harness:

- **Sandboxing.** `bash` runs with your full user permissions. Use `--permissions=ask`
  if you don't fully trust the model.
- **MCP / extension protocol.** Tools are Python functions; add new ones in
  `vibeharness/tools/`.
- **Sub-agents.** No parallel sub-agent spawning; one main loop only.
- **LSP integration.** Searches are grep-based.
- **Streaming token output.** Responses stream by panel, not by token.
- **Eval harness.** No SWE-bench runner.

Each of these is a project in itself. PRs welcome.

---

## License

MIT. See [LICENSE](./LICENSE).

---

## Credits

Built as a worked example of what's actually inside an agent harness like
Claude Code or Copilot CLI. Heavy inspiration from both, plus
[`aider`](https://github.com/Aider-AI/aider) and
[`smol-developer`](https://github.com/smol-ai/developer).
