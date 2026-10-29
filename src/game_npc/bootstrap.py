"""Explicit composition root, called only by application entry points."""

from pathlib import Path

from game_npc.agent import Conversation
from game_npc.config import ASSETS
from game_npc.domain import GameService
from game_npc.knowledge import KnowledgeBase
from game_npc.persona import NPCProfile, WorldContext, load_profile
from game_npc.world import WorldPack, load_builtin_world, load_world, load_world_npc


def resolve_world(settings, world=None):
    if world is not None:
        if isinstance(world, WorldPack):
            return world, None
        if isinstance(world, (str, Path)):
            return load_world(world)
        return WorldPack.from_dict(world), None
    if settings.world_pack_path is not None:
        return load_world(settings.world_pack_path)
    return None, None


def build_knowledge(settings, *, data_dir=None):
    return KnowledgeBase(
        data_dir=data_dir or settings.data_dir,
        state_dir=settings.state_dir / "knowledge",
        mode=settings.retrieval,
        embedding_model=settings.embedding_model,
        api_key=settings.api_key,
        base_url=settings.base_url,
    )


def build_conversation(
    settings, player_id="1001", *, profile=None, context=None, world=None, use_world_npc=False
):
    # Validate external role / world data before opening any game state.
    pack, pack_dir = resolve_world(settings, world)
    if profile is None:
        if use_world_npc and pack is not None and pack.default_npc and pack_dir is not None:
            profile = load_world_npc(pack_dir, pack.default_npc)
        else:
            profile = load_profile(settings.npc_profile_path)
    if not isinstance(profile, NPCProfile):
        profile = NPCProfile.from_dict(profile)
    if context is not None and not isinstance(context, WorldContext):
        context = WorldContext.from_dict(context)
    data_dir = settings.data_dir
    if pack is not None:
        resolved = pack.resolve_knowledge_dir(pack_dir)
        # World lore replaces the bundled default knowledge only; an explicit
        # GAME_NPC_DATA_DIR / settings.data_dir override always wins.
        if (
            resolved is not None
            and resolved.is_dir()
            and settings.data_dir == (ASSETS / "knowledge").resolve()
        ):
            data_dir = resolved
    game = GameService(settings.state_dir / "game.sqlite3", player_id)
    return Conversation(
        settings,
        game,
        build_knowledge(settings, data_dir=data_dir),
        profile=profile,
        context=context,
        world=pack,
    )


def open_builtin_world(name: str):
    """Helper for hosts: load a packaged world frame and its directory."""
    return load_builtin_world(name)
