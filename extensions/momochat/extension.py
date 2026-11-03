"""MomoChat: the conversation harness. The general assistant: conversations, direct chats and group chats, tools and
commands; the students, each with her memory wherever she speaks, and a plain assistant for an agent. Chimera is the heavy-work one.
"""

from __future__ import annotations

from contracts import Contributions, Extension, Setting

from .engine import MomoChatEngine, Settings


def setup(context) -> Contributions:
    return Contributions(engines=[MomoChatEngine(Settings(context.config))])


EXTENSION = Extension("momochat", setup,
                      description="Conversations, direct and in groups: talk, tools, questions and hand-offs between "
                                  "classmates", settings=(
    Setting("max_steps", "Most steps (tool rounds) of one speaker per message", "number", 8),
    Setting("history_limit", "Earlier messages every speaker reads word for word", "number", 30),
    Setting("effort", "Reasoning effort: low, medium or high", "text", "low"),
    Setting("style", "brief (a speaker in a conversation), full (a chat client: complete answers, only the answer "
            "posted) or chat (a chat app: short and casual, only the answer posted)", "text", "brief"),
    Setting("chime_in", "A group message naming no one: whose turn it is answers, the others may join in", "boolean",
            False),
    Setting("compact", "Fold messages older than history_limit into the chat's rolling summary", "boolean", True),
    Setting("tool_calls", "Let models that can call tools do so natively (false: JSON steps only)", "boolean", True),
))
