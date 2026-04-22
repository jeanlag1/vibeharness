# vibeharness 🌀

A medium-weight terminal agent harness, in the spirit of Claude Code and
GitHub Copilot CLI. Give it an Anthropic API key and a task; it'll use file
and shell tools to get the job done.

> Status: early alpha. See [Architecture](#architecture) for what's wired up.

## Quick start

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
vibe "add a docstring to every public function in src/"
```

Full docs land in the final commit.
