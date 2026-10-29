"""CLI for diagnostics, indexing, conversations and the UI."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from game_npc import __version__
from game_npc.config import Settings
from game_npc.persona import builtin_profiles, load_context, load_profile
from game_npc.providers import provider_catalog
from game_npc.world import BUILTIN_WORLD_NAMES, builtin_worlds, load_builtin_world


def _configure_console():
    """Keep Chinese text and JSON UTF-8 even in redirected Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError, AttributeError):
            # Some redirected or closed streams reject reconfigure; _emit falls back.
            pass


def _emit(text: str = "", *, file=None, end: str = "\n") -> None:
    """Write text as UTF-8 even when the active console encoding is legacy."""
    stream = sys.stdout if file is None else file
    payload = f"{text}{end}"
    try:
        stream.write(payload)
        stream.flush()
    except UnicodeEncodeError:
        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            raise
        buffer.write(payload.encode("utf-8", "backslashreplace"))
        buffer.flush()


def main(argv=None):
    _configure_console()
    parser = argparse.ArgumentParser(description="NPC 对话、多模型接入与游戏世界包演示")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--state-dir", type=Path, help="索引与演示状态目录")
    parser.add_argument("--mode", choices=["demo", "live"])
    parser.add_argument("--npc-profile", type=Path, help="外部 NPC 角色 JSON 档案")
    parser.add_argument("--world-pack", type=Path, help="外部或内置路径上的世界包目录 / world.json")
    parser.add_argument(
        "--use-world-npc",
        action="store_true",
        help="若世界包声明了 default_npc，则使用该角色档案",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查配置、依赖和知识索引，不请求模型")
    sub.add_parser("ingest", help="构建或同步知识索引")
    providers = sub.add_parser("providers", help="列出 OpenAI 兼容模型提供商预设")
    providers.add_argument("--json", action="store_true", help="以 JSON 输出")
    npc = sub.add_parser("npc", help="输出 NPC 档案，可重定向为外部 JSON 模板")
    npc.add_argument("--sample", choices=["village_elder", "guard", "merchant"])
    world = sub.add_parser("world", help="输出世界包 JSON，或列出内置世界")
    world.add_argument("--sample", choices=list(BUILTIN_WORLD_NAMES))
    world.add_argument("--list", action="store_true", help="列出内置世界包")
    chat = sub.add_parser("chat", help="单次提问或终端交互")
    chat.add_argument("query", nargs="?")
    chat.add_argument("--player", choices=["1001", "1002"], default="1001")
    chat.add_argument("--report", action="store_true")
    chat.add_argument("--context-file", type=Path, help="可信实时情境 JSON 文件，每轮重新读取")
    chat.add_argument("--explain", action="store_true", help="额外显示结构化角色决策摘要")
    ui = sub.add_parser("ui", help="启动 Streamlit 界面")
    ui.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    try:
        if args.command == "providers":
            catalog = provider_catalog()
            if args.json:
                _emit(json.dumps(catalog, ensure_ascii=False, indent=2))
            else:
                for item in catalog:
                    _emit(
                        f"{item['name']}: {item['label']} -> {item['model']} @ {item['base_url']}"
                    )
                    if item["notes"]:
                        _emit(f"  {item['notes']}")
            return 0
        if args.command == "npc":
            profile = (
                builtin_profiles()[args.sample]
                if args.sample
                else load_profile(args.npc_profile or os.getenv("GAME_NPC_PROFILE_PATH"))
            )
            _emit(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "world":
            if args.list or not args.sample:
                payload = {
                    name: {
                        "title": pack.title,
                        "setting_name": pack.setting_name,
                        "default_npc": pack.default_npc,
                    }
                    for name, pack in builtin_worlds().items()
                }
                _emit(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
            pack, _ = load_builtin_world(args.sample)
            _emit(json.dumps(pack.to_dict(), ensure_ascii=False, indent=2))
            return 0
        settings = Settings.from_env(state_dir=args.state_dir)
        overrides = {}
        if args.mode:
            overrides["mode"] = args.mode
        if args.npc_profile:
            overrides["npc_profile_path"] = args.npc_profile
        if args.world_pack:
            overrides["world_pack_path"] = args.world_pack
        settings = replace(settings, **overrides)
        if args.command == "doctor":
            return _doctor(settings)
        if args.command == "ui":
            if importlib.util.find_spec("streamlit") is None:
                raise ValueError("请安装界面依赖：python -m pip install 'game-npc-agent[ui]'")
            if not 1 <= args.port <= 65535:
                raise ValueError("端口必须在 1 到 65535 之间")
            env = dict(
                os.environ, GAME_NPC_STATE_DIR=str(settings.state_dir), GAME_NPC_MODE=settings.mode
            )
            if settings.npc_profile_path:
                env["GAME_NPC_PROFILE_PATH"] = str(settings.npc_profile_path)
            if settings.world_pack_path:
                env["GAME_NPC_WORLD_PATH"] = str(settings.world_pack_path)
            return subprocess.call(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(Path(__file__).with_name("ui.py")),
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    str(args.port),
                    "--browser.gatherUsageStats",
                    "false",
                ],
                env=env,
            )
        from game_npc.bootstrap import build_conversation

        if args.command == "ingest":
            conversation = build_conversation(settings, use_world_npc=args.use_world_npc)
            _emit(json.dumps(conversation.knowledge.ingest(), ensure_ascii=False, indent=2))
            return 0
        conversation = build_conversation(
            settings,
            args.player,
            context=load_context(args.context_file),
            use_world_npc=args.use_world_npc,
        )
        mode = "report" if args.report else "dialogue"

        def respond(query):
            # File updates are trusted host input, separate from what the player says.
            answer = conversation.reply(query, mode, context=load_context(args.context_file))
            _emit(answer)
            if args.explain:
                _emit(json.dumps(conversation.last_decision, ensure_ascii=False, indent=2))

        if args.query:
            respond(args.query)
            return 0
        provider = settings.provider_label() if settings.mode == "live" else "offline-demo"
        world_name = conversation.world.setting_name if conversation.world else "默认演示"
        _emit(
            f"NPC {settings.mode} · {provider} · 世界「{world_name}」；"
            "输入 /quit 退出，/clear 清空对话。"
        )
        while True:
            try:
                query = input("你 > ").strip()
            except EOFError:
                return 0
            if query == "/quit":
                return 0
            if query == "/clear":
                conversation.clear()
                continue
            if query:
                try:
                    respond(query)
                except (ValueError, RuntimeError) as exc:
                    _emit(f"本轮未完成：{exc}", file=sys.stderr)
    except (ValueError, RuntimeError, OSError) as exc:
        _emit(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _doctor(settings):
    from game_npc.bootstrap import build_knowledge, resolve_world
    from game_npc.config import ASSETS

    problems = []
    profile = load_profile(settings.npc_profile_path)
    world_info = None
    data_dir = settings.data_dir
    try:
        pack, pack_dir = resolve_world(settings)
        if pack is not None:
            world_info = {
                "world_id": pack.world_id,
                "setting_name": pack.setting_name,
                "title": pack.title,
            }
            resolved = pack.resolve_knowledge_dir(pack_dir)
            if (
                resolved is not None
                and resolved.is_dir()
                and settings.data_dir == (ASSETS / "knowledge").resolve()
            ):
                data_dir = resolved
    except (ValueError, RuntimeError, OSError) as exc:
        problems.append(str(exc))
    if not data_dir.is_dir():
        problems.append("知识目录不存在")
    knowledge = build_knowledge(settings, data_dir=data_dir)
    online = settings.mode == "live" or settings.retrieval == "vector"
    if online and not settings.api_key:
        problems.append("缺少 GAME_NPC_API_KEY 或当前提供商对应密钥")
    installed = {
        name: importlib.util.find_spec(name) is not None
        for name in ("streamlit", "openai", "pypdf", "chromadb")
    }
    if online and not installed["openai"]:
        problems.append("请安装 [live] 依赖")
    if settings.retrieval == "vector" and not installed["chromadb"]:
        problems.append("请安装 [vector] 依赖")
    _emit(
        json.dumps(
            {
                "version": __version__,
                "python": sys.version.split()[0],
                "mode": settings.mode,
                "provider": settings.provider,
                "provider_label": settings.provider_label(),
                "model": settings.model,
                "base_url": settings.base_url,
                "retrieval": settings.retrieval,
                "data_dir": str(data_dir),
                "state_dir": str(settings.state_dir),
                "world": world_info,
                "npc": {
                    "npc_id": profile.npc_id,
                    "name": profile.name,
                    "profession": profile.profession,
                    "region": profile.region,
                    "thinking_order": list(profile.thinking_order),
                    "fingerprint": profile.fingerprint(),
                },
                "dependencies": installed,
                "knowledge": knowledge.status(),
                "problems": problems,
                "next_step": "索引未就绪时运行 game-npc ingest；doctor 不发出模型请求",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(bool(problems))
