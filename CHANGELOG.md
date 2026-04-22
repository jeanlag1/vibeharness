# Changelog

## 0.2.0

Major v1 → v2 upgrade. Eleven new features across seven commits.

### Added
- **Token streaming** — assistant text now appears live (Anthropic
  `messages.stream()` and OpenAI `stream=True`).
- **Anthropic prompt caching** — system prompt + tool definitions get
  ephemeral cache breakpoints; repeated turns within the cache window
  read those tokens at ~90% discount.
- **Cost meter** — per-model USD pricing table; usage line shows
  estimated cost alongside token counts (input / output / cache_r / cache_w).
- **Stop-reason handling** — `max_tokens` truncations are auto-resumed
  with a "please continue" follow-up, transparent to the caller.
- **Bash output cleanup** — ANSI-stripped, repeated lines collapsed,
  smart head/tail truncation; same for background-process logs.
- **`@file` mentions** — any `@path/to/file` token in REPL input is
  expanded with the file's contents appended as context.
- **Custom slash commands** — drop a markdown file at
  `~/.vibe/commands/<name>.md` and use `/<name>` in the REPL.
- **TodoWrite-style planning tool** — `set_plan`, `update_plan_item`,
  `get_plan` give the model a stateful checklist; system prompt nudges
  it to externalize multi-step work.
- **Sub-agent / `task` tool** — spawn an isolated sub-agent with its own
  conversation; only a short final report comes back to the parent.
- **User hooks** — `~/.vibe/hooks.py` may define `before_tool` /
  `after_tool` to mutate args, deny calls, or post-process results
  (e.g. auto-format edited files, gate commands).
- **Mid-turn checkpoints** — `save_session()` is invoked after every
  tool call, not just at end of turn; Ctrl-C / crash never loses
  progress captured so far.

### Internal
- `LLMProvider.complete` accepts an `on_text_delta` callback.
- `Agent` gains `total_cache_read_tokens`, `total_cache_write_tokens`,
  `last_stop_reason`, `hook_manager`, `on_checkpoint`.
- 33 new tests; suite is 69 total, all without API keys.

## 0.1.0
Initial release. See README architecture section.
