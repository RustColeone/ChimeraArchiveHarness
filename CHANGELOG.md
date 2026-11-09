# Changelog

What each release of ChimeraArchiveHarness changed. `venv/bin/python -m core --version` says which one you run.

## 0.9.0 (2026-11-08)

The first numbered release: a small plug-in core, and around it the students, MomoChat, Chimera and the interfaces, as
the [README](README.md) describes them. It needs Python 3.12 or newer and mneme-llm 0.7.3.

**What it holds**

- **The core** runs conversations, approvals, routines and history, and knows no platform. Modules declare the modules
  and packages they need; one that cannot load is left out with the reason, and the rest start. Every model call goes
  through one provider layer (DeepSeek, OpenAI, Gemini, Claude, OpenRouter and any OpenAI-compatible API), with
  fallbacks between candidates that are never silent, prompt caching, and prices from Artificial Analysis.
- **The students** (GPT, Gemini, Claude, DeepSeek and Grok) are agents with their memory: what was said, kept word for
  word with the newest part in front of her, notes, mood, closeness and her gut (mneme-llm), wherever she speaks. Her
  settings page has four tabs, Her, People, Memory and Gut.
- **MomoChat** converses: direct and group chats, hand-offs between classmates, tools and commands. **Chimera**, the
  Classroom, works on your code: each task routed, worked in its own git worktree, tested, and landed as one commit only
  after your second check and final approval.
- **Stamina**: every answer is priced, each student has a daily allowance and everyone together a daily total, and a
  run that reaches one stops and asks.
- **Interfaces**: Discord (with 鲸酱's own bot and voice), the web UI on your local network (the Cafe, MomoChat, the
  Students page and your page), the Classroom page, WeChat (optional) and the terminal. The pages speak English and
  Chinese.
- **Setup** in one step (`python -m core setup`), a supervisor that restarts the bot when it needs to, and the
  architecture page read from the code.

**New since the build before it**

- **Every billed call counts, whichever provider made it.** An answer that could not be used (not the requested JSON,
  calls that do not fit the tools, cut off at the token limit) is kept in the audit log with what it said, its tokens
  and its cost; it counts in the run's usage and on the student's day, and shows on the Classroom's step as its own row,
  dimmed, with why. Contracts 2.2: `RejectedCall`, on `ModelResult.rejected` and `ModelError.rejected`.
- **Words before the JSON no longer lose the answer**: every object in the text is a candidate, and the last that
  matches the schema is it.
- **Claude calls tools natively** (tool_use and tool_result blocks), with her answer sent back as she wrote it, and
  **answers from Anthropic's prompt cache**, so the conversation so far costs a tenth on the next call.
- **A module left out says so**: a start names each module not loaded and why, and the Classroom refuses a task it has
  nobody for instead of leaving it waiting.
- **The students need mneme-llm 0.7.3**: links between exchanges that come to mind together grow in each student's
  memory file (mneme-llm's tuner draws them as her memory sky); a look is as before.
- **The translation tool reads every page**, and a test keeps every word the pages show translated.
- **The tests run on GitHub at every push.**

**Known limits**

- The web UI and the Classroom page are for your own network: a passphrase is their only lock.
- Claude's native tool calls are new in this release and have had little use with the live API.
- Gemini works through JSON steps: its adapter makes no native tool calls.
- WeChat runs through the Linux desktop client. When the client is not ready for `give_up_s` (300 seconds), the
  interface stops checking until `$wechat_login` or `$wechat_resume`.

**Upgrading**

Stop the bot, `git pull`, `venv/bin/pip install -r requirements.txt`, and start it. Memory files gain the links table
when they are first opened; nothing else to do. From a build before the 2026-11 clean-up, run `tools/migrate.py` first
(see the README).
