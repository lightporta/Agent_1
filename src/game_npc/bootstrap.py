"""Explicit composition root, called only by application entry points."""

from game_npc.agent import Conversation
from game_npc.domain import GameService
from game_npc.knowledge import KnowledgeBase


def build_knowledge(settings):
    return KnowledgeBase(
        data_dir=settings.data_dir,
        state_dir=settings.state_dir / "knowledge",
        mode=settings.retrieval,
        embedding_model=settings.embedding_model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )


def build_conversation(settings, player_id="1001"):
    game = GameService(settings.state_dir / "game.sqlite3", player_id)
    return Conversation(settings, game, build_knowledge(settings))
