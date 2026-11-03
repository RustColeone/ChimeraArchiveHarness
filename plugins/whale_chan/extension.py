"""Whale-chan (鲸酱): an example drop-in extension. Her own Discord bot, chatting
inside the app: a frontend of MomoChat. She is the DeepSeek student: the bot is one more way to reach her, as
MomoChat's other pages are, and what she is (her prompt, name, models) and remembers (her memory) is the same
everywhere.

Drop this folder into `plugins/` (it already is), put the bot token in `.env` as
DISCORD_BOT_TOKEN_WHALE_CHAN (or in this folder's config.yml) and restart: the core loads it without
changes to core.yml. Without a token only her voice loads.

It contributes: the `whale_chan` interface (the Discord bot, which also speaks her short replies as voice messages
where `/voice on` asks it to, and her own first messages), her voice (`whale_chan.speak`, for her model to call) and
defaults for its own conversations (`whale_chan:*` is MomoChat with the DeepSeek student, one thread until `/new`; in
servers it answers mentions and replies; every write and critical action asks
the owner first, with no exceptions, in case she misread a request or a page tried to trick her). core.yml settings
win over all of these.
"""

from __future__ import annotations

import os

from contracts import Contributions, Extension, Setting

from . import voice
from .bot import WhaleChanBot


async def check_token(token: str) -> str:
    """Log in with the token over HTTP and name the bot."""
    import aiohttp
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get("https://discord.com/api/v10/users/@me",
                                   headers={"Authorization": f"Bot {token.strip()}"}) as response:
                if response.status != 200:
                    raise ValueError("Discord rejected this token" if response.status == 401
                                     else f"Discord answered HTTP {response.status}")
                return f"logs in as {(await response.json()).get('username')}"
    except aiohttp.ClientError as error:
        raise ValueError(f"Could not reach Discord: {type(error).__name__}")

# How MomoChat runs her chats: a chat app's, short and casual, at the effort in her student.yml (none: she answers at
# once); `style: full` and `effort: high` in her settings make this a chat client, thorough and slow. Her settings of
# these names (style, max_steps, ...) win, and the assignment's own `options` over them.
OPTIONS = {"style": "chat", "max_steps": 10, "max_tokens": 8000, "history_limit": 60,
           "history_chars": 40000, "timeout_s": 240, "compact": False, "new_chat_text": "🐳 好的主人，新的对话开始啦～"}


def chat_options(config) -> dict:
    """MomoChat's options for her chats: OPTIONS, with her settings of the same names (and `tool_calls`)."""
    return {**OPTIONS, **{key: config[key] for key in (*OPTIONS, "effort", "tool_calls") if key in config}}


def setup(context) -> Contributions:
    config = context.config
    name = str(config.get("interface", "whale_chan"))
    persona = str(config.get("persona", "deepseek"))  # the student her bot speaks as
    speech = {"folder": str(context.data_dir), **dict(config.get("voice") or {})}  # (`folder`: where her clip is)
    speaking = speech.get("enabled", True) is not False
    capabilities = [voice.capability(speech)] if speaking else []
    token = str(config.get("token") or os.getenv(str(config.get("token_env", "DISCORD_BOT_TOKEN_WHALE_CHAN")), ""))
    token = token.strip().strip("\"'")
    if not token:
        context.log("no_token", hint="her voice only; set the bot token to start the Discord bot")
        return Contributions(capabilities=capabilities)
    custom = dict(config.get("assignment") or {})
    assignment = {"engine": "momochat", "personas": [persona],
                  "budget": {"model_calls": 30, "tool_calls": 24, "seconds": 1800},
                  **custom, "options": {**chat_options(config), **dict(custom.get("options") or {})}}
    bot = WhaleChanBot(name, token, context.data_dir, config=config, persona=persona,
                       voice={**speech, "enabled": speaking})
    capabilities = [voice.capability(speech, silenced=bot.silenced)] if speaking else []
    return Contributions(capabilities=[*capabilities, *bot.capabilities()], interfaces=[bot],
                         assignments={f"{name}:*": assignment},
                         admission={f"{name}:*": {"enabled": True, "require_mention_in_groups": True}},
                         permissions={f"{name}:*": {"tiers": {"write": "always-ask", "critical": "always-ask"}}})


EXTENSION = Extension("whale_chan", setup, requires=("students", "momochat"), platforms={"whale_chan": "discord"},
                      description="Example drop-in: 鲸酱's own Discord bot, a personal AI chat client on MomoChat, "
                                  "speaking as the DeepSeek student", settings=(
    Setting("token", "鲸酱's own Discord bot token (a second application in the Developer Portal)", "secret",
            env="DISCORD_BOT_TOKEN_WHALE_CHAN", check=check_token),
    Setting("persona", "The student her bot speaks as", "text", "deepseek"),
))
