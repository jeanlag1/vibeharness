# 🌀 vibeharness

**An interactive, tool-using LLM agent harness for the terminal** — the
hackable middle ground between a 100-line ReAct toy and a closed-source
product like Claude Code or Copilot CLI. ~2.4k lines of Python you can
actually read end-to-end.

What you get when you launch `vibe`:

- A **stateful REPL** that holds a multi-turn conversation with the model
  and renders it live: streaming token-by-token output, a thinking spinner,
  rich diff/grep/bash panels, and a magenta `◆ vibe` / green `❯ you`
  speaker layout you can scan at a glance.
- A **tool-using agent loop** that the model drives autonomously inside
  each turn: read/write/edit files (with strict-match diffs), grep, glob,
  list, run bash in **persistent PTY sessions** (and background processes),
  spawn isolated **sub-agents** for self-contained subtasks, and update an
  externalized **planning checklist** as it works.
- A **provider abstraction** over Anthropic and OpenAI with token
  streaming, **prompt caching** (cache_control breakpoints on the system
  prompt + tool defs → ~90% discount on repeated turns), and a
  **rate-limit-aware retry layer** that honors `Retry-After`, falls back to
  exponential backoff with full jitter, and surfaces each retry in the UI.
- A **policy + extensibility surface**: three-mode permission policy
  (`auto` / `ask` / `deny`) with per-tool approval memory, plus user-defined
  `before_tool` / `after_tool` **hooks** in `~/.vibe/hooks.py` that can
  mutate args, deny calls, or post-process results (auto-format, gate
  commands, log to disk).
- A **session layer** that JSON-serializes the conversation **after every
  tool call** (mid-turn checkpointing — Ctrl-C never loses progress) and
  **re-renders the full transcript on resume** so you pick up exactly
  where you left off.
- **Context management** that token-counts every turn and triggers an
  auto-summarization compactor when the window crosses 75% so long
  sessions don't blow out the model's context limit.
- **Composable input**: `@path/to/file` mentions inline file contents,
  `/cmdname` runs custom prompts from `~/.vibe/commands/*.md`, and the
  built-in `/help`, `/sessions`, `/cost`, `/tools`, `/compact`, `/save`,
  `/clear` give you full session introspection without leaving the REPL.

```bash
$ vibe
```

```
╭─ 🌀 vibeharness v0.2.1 · model: claude-sonnet-4-5 · cwd: ~/proj · session: a1b2c3d4e5 ─╮
│ Type a task, /help for commands, Ctrl-C to exit.                                       │
╰────────────────────────────────────────────────────────────────────────────────────────╯

❯ you: refactor src/utils.py — add docstrings to every public function

◆ vibe
Looking at src/utils.py and adding docstrings…
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
                              tokens: in=2103 out=412 cache_r=1850  cost≈$0.0073
```

(There's also a `vibe run "<task>"` one-shot mode for scripting / CI, but
the REPL is the primary interface.)

---

## Why another agent harness?

The big ones — Claude Code, Copilot CLI, Aider — are excellent, but they're
either closed-source, large, or both. **vibeharness** exists to be:

- **Hackable.** Every file fits on a screen. The agent loop is ~100 lines.
- **Educational.** A worked example of what a "medium" agent harness needs:
  tool registry, schema generation, permission policy, persistent shells,
  context compaction, session persistence, streaming UI, sub-agents, hooks.
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
- type a task to send it to the agent (text **streams** in real-time)
- `@path/to/file` anywhere in your message attaches that file as context
- `/cmdname` runs a custom slash command from `~/.vibe/commands/cmdname.md`
- `/help` — pretty table of every builtin + custom command
- `/save` — write the session to `~/.vibe/sessions/`
- `/sessions` — list saved sessions, marks the current one
- `/cost` — show cumulative tokens + USD estimate for this session
- `/tools` — list every tool available to the agent
- `/compact` — summarize older turns to free context
- `/clear` — wipe history
- `/exit` — quit

### One-shot

```bash
vibe run "find every TODO in src/ and group them by file"
vibe run "write a pytest fixture for our database client" --auto
```

### Resume a session

Sessions are checkpointed **after every tool call**, not just at end of turn,
so a Ctrl-C or crash never loses progress. When you resume, the full
transcript (user turns, assistant replies, tool calls) is **re-rendered** so
you immediately see where you left off.

```bash
vibe sessions                 # list (also available as /sessions inside REPL)
vibe --resume a1b2c3d4e5      # full transcript replays, then prompt
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

### Custom slash commands

Drop a markdown file at `~/.vibe/commands/<name>.md`. Its content becomes the
prompt when the user types `/<name>`. Trailing free-form arguments are
appended after a separator. Example `~/.vibe/commands/review.md`:

```markdown
You are reviewing the changes in this repo. Run `git diff main`,
identify any bugs or regressions, and write a concise review.
```

Then in the REPL: `/review` (or `/review focus on auth/*` for an extra hint).

### User hooks (extensibility API)

Drop a Python file at `~/.vibe/hooks.py` and define optional functions:

```python
# ~/.vibe/hooks.py
def before_tool(name, args):
    # Block edits to .env files
    if name == "edit_file" and args["path"].endswith(".env"):
        raise PermissionError("no .env edits allowed")
    return args  # may return modified args, or None for no-op

def after_tool(name, args, result):
    # Auto-format Python after every edit
    if name in ("write_file", "edit_file") and args["path"].endswith(".py"):
        import subprocess
        subprocess.run(["ruff", "format", args["path"]])
    return result
```

Hooks run for every tool call (including those inside sub-agents).

---

## Architecture

```
vibeharness/
├── agent.py          ← main loop: LLM ↔ tools ↔ permissions ↔ hooks
├── llm.py            ← provider abstraction (Anthropic, OpenAI) + streaming + caching
├── retry.py          ← rate-limit-aware retry: 429/529/5xx + Retry-After + jitter
├── prompts.py        ← system prompt (encourages externalized planning)
├── permissions.py    ← auto / ask / deny policy
├── context.py        ← token counting + auto-compaction
├── pricing.py        ← per-model USD/M-token table for cost meter
├── session.py        ← JSON save/resume; checkpointed mid-turn
├── ui.py             ← Rich panels: streaming text, diffs, bash output, plan
├── repl_input.py     ← @file mention + slash-command expansion
├── planning.py       ← TodoWrite-style internal plan with set/update/get tools
├── subagent.py       ← `task` tool spawns isolated sub-agents
├── hooks.py          ← user-defined pre/post-tool hooks
├── config.py         ← TOML config + env overrides
├── cli.py            ← Typer entrypoint
└── tools/
    ├── __init__.py   ← Tool registry + JSON schema generation
    ├── files.py      ← read / write / edit / grep / glob / list_dir
    └── bash.py       ← persistent PTY shells + background processes; ANSI strip + smart trim
```

### The loop

```
user_input
   │ (slash-command and @mention expansion)
   ▼
┌──────────────────────────────────────────────────────┐
│  while True:                                         │
│    turn = llm.complete(messages, tools, on_delta=…)  │  ← streams tokens live
│    record turn → messages                            │
│    if not turn.tool_calls:                           │
│        if stop_reason == "max_tokens": continue      │  ← auto-resume
│        else break ────────────────────────────────────┼── final assistant response
│    for call in turn.tool_calls:                      │
│        if mutating: permissions.check()              │
│        args = hooks.before(call.name, args)          │
│        result = dispatch(call)                       │
│        result = hooks.after(name, args, result)      │
│    record results → messages                         │
│    save_session() ← checkpoint after every round     │
└──────────────────────────────────────────────────────┘
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
| `bash` | ✎ | shell command in a **persistent** session (ANSI-stripped, smart-truncated output) |
| `bash_background` | ✎ | start a long-running process, returns `bg_id` |
| `bash_read` | – | read accumulated output from a background process |
| `bash_stop` | ✎ | stop a background process |
| `set_plan` | – | replace the agent's internal checklist |
| `update_plan_item` | – | mark a plan item in_progress / done / blocked |
| `get_plan` | – | read back the current plan + summary |
| `task` | – | spawn an isolated sub-agent for a self-contained subtask |

`edit_file` uses Claude-Code-style strict matching: it requires a unique
substring match by default and fails loudly if `old` appears more or fewer
times than `count`. This is what makes "make a small targeted change" reliable.

The bash tool uses `pexpect` for a real PTY, so `cd`, `export`, shell
functions, and prompts all work and persist across calls with the same
`session_id`. Output is ANSI-stripped, run-length-collapsed, and head/tail
truncated before being returned to the model.

The `task` tool spawns a fresh `Agent` with the same provider but its own
message history. Sub-agents return only a short final report — the heavy
investigation never bloats the parent conversation. Sub-agents cannot
recursively spawn more sub-agents (no `task` tool inside them).

The planning tools encourage the model to externalize and update a checklist
on any non-trivial task. Empirically this reduces drift on long sessions.

### Streaming + caching

- **Streaming**: text appears token-by-token via Anthropic's `messages.stream()`
  / OpenAI's `stream=True`. Tool calls still execute as discrete blocks.
- **Prompt caching** (Anthropic): the system prompt and tool definitions get
  `cache_control: {type: "ephemeral"}` breakpoints. Repeated turns within the
  5-minute cache window read those tokens at ~90% discount; the cost meter
  shows `cache_r=` / `cache_w=` separately.
- **Thinking spinner**: while waiting on the LLM you see a `thinking…` dots
  spinner that auto-dismisses on the first streamed token or tool call.

### Rate-limit awareness

LLM APIs throw `429 RateLimitError`, `529 Overloaded`, intermittent 5xx, and
network blips all the time. vibeharness wraps every provider call in a
retry layer (`vibeharness/retry.py`):

- Retries on `429`, `529`, `5xx`, and connection / timeout errors.
- **Honors `Retry-After`** headers when the API tells you exactly how long to
  wait; falls back to **exponential backoff with full jitter** otherwise
  (1s → 2s → 4s → … capped at 60s, up to 6 attempts).
- Surfaces every retry through the UI as a friendly
  `⏳ RateLimitError: retrying in 4.2s (attempt 2)…` line so you know the
  agent isn't dead — it's just being polite to the API.
- Non-retryable errors (4xx other than 408/409/425/429) are raised
  immediately so bad requests don't waste backoff.

Tunables (env vars, sensible defaults):

| var | default | meaning |
|---|---|---|
| `VIBE_MAX_RETRIES` | `6` | max attempts per provider call |
| `VIBE_RETRY_BASE_DELAY` | `1.0` | base seconds for exponential backoff |
| `VIBE_RETRY_MAX_DELAY` | `60.0` | per-attempt cap |

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

Saved as plain JSON to `~/.vibe/sessions/{id}.json` **after every tool call**
(mid-turn checkpointing — Ctrl-C never loses progress). `vibe --resume ID`
rehydrates `messages` and token counters.

### Stop-reason handling

If the model returns `stop_reason="max_tokens"` without tool calls, the agent
silently sends a "please continue from where you left off" follow-up so a
truncated response is finished automatically.

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

There are 80 tests, none of which need an API key. They use a `FakeProvider`
to exercise the agent loop deterministically.

```
$ pytest -q
................................................................................ [100%]
80 passed
```

---

## What's intentionally NOT here

To stay "medium," vibeharness deliberately omits things you'd want in a
production-grade harness:

- **Sandboxing.** `bash` runs with your full user permissions. Use `--permissions=ask`
  if you don't fully trust the model, or write a `before_tool` hook to enforce
  command/path allowlists.
- **MCP / extension protocol.** Tools are Python functions; add new ones in
  `vibeharness/tools/`. (User hooks cover most extension needs.)
- **LSP integration.** Searches are grep-based.
- **Full eval harness.** No SWE-bench runner.
- **Multi-modal.** No image input.
- **Local model support.** Add a third provider in `llm.py` if you want one.

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
