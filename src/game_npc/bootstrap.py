"""Explicit composition root, called only by application entry points."""

from game_npc.agent import Conversation
from game_npc.domain import GameService
from game_npc.knowledge import KnowledgeBase
from game_npc.persona import load_profile


def build_knowledge(settings):
    return KnowledgeBase(
        data_dir=settings.data_dir,
        state_dir=settings.state_dir / "knowledge",
        mode=settings.retrieval,
        embedding_model=settings.embedding_model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )


def build_conversation(settings, player_id="1001", *, profile=None, context=None):
    # Validate external role data before opening any game state.
    if profile is None:
        profile = load_profile(settings.npc_profile_path)
    from game_npc.persona import NPCProfile, WorldContext

    if not isinstance(profile, NPCProfile):
        profile = NPCProfile.from_dict(profile)
    if context is not None and not isinstance(context, WorldContext):
        context = WorldContext.from_dict(context)
    game = GameService(settings.state_dir / "game.sqlite3", player_id)
    return Conversation(settings, game, build_knowledge(settings), profile=profile, context=context)
