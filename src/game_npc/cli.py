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


def main(argv=None):
    parser = argparse.ArgumentParser(description="中文 NPC 对话与知识检索演示")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--state-dir", type=Path, help="索引与演示状态目录")
    parser.add_argument("--mode", choices=["demo", "live"])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查配置、依赖和知识索引，不请求模型")
    sub.add_parser("ingest", help="构建或同步知识索引")
    chat = sub.add_parser("chat", help="单次提问或终端交互")
    chat.add_argument("query", nargs="?")
    chat.add_argument("--player", choices=["1001", "1002"], default="1001")
    chat.add_argument("--report", action="store_true")
    ui = sub.add_parser("ui", help="启动 Streamlit 界面")
    ui.add_argument("--port", type=int, default=8501)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        overrides = {}
        if args.state_dir:
            overrides["state_dir"] = args.state_dir
        if args.mode:
            overrides["mode"] = args.mode
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
        from game_npc.bootstrap import build_conversation, build_knowledge

        if args.command == "ingest":
            print(json.dumps(build_knowledge(settings).ingest(), ensure_ascii=False, indent=2))
            return 0
        conversation = build_conversation(settings, args.player)
        mode = "report" if args.report else "dialogue"
        if args.query:
            print(conversation.reply(args.query, mode))
            return 0
        print(f"NPC {settings.mode} 模式；输入 /quit 退出，/clear 清空对话。")
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
                    print("NPC >", conversation.reply(query, mode))
                except (ValueError, RuntimeError) as exc:
                    print(f"本轮未完成：{exc}", file=sys.stderr)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def _doctor(settings):
    from game_npc.bootstrap import build_knowledge

    problems = []
    if not settings.data_dir.is_dir():
        problems.append("知识目录不存在")
    online = settings.mode == "live" or settings.retrieval == "vector"
    if online and not settings.api_key:
        problems.append("缺少 DASHSCOPE_API_KEY")
    installed = {
        name: importlib.util.find_spec(name) is not None
        for name in ("streamlit", "openai", "pypdf", "chromadb")
    }
    if online and not installed["openai"]:
        problems.append("请安装 [live] 依赖")
    if settings.retrieval == "vector" and not installed["chromadb"]:
        problems.append("请安装 [vector] 依赖")
    print(
        json.dumps(
            {
                "version": __version__,
                "python": sys.version.split()[0],
                "mode": settings.mode,
                "retrieval": settings.retrieval,
                "data_dir": str(settings.data_dir),
                "state_dir": str(settings.state_dir),
                "dependencies": installed,
                "knowledge": build_knowledge(settings).status(),
                "problems": problems,
                "next_step": "索引未就绪时运行 game-npc ingest；doctor 不发出模型请求",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(bool(problems))
