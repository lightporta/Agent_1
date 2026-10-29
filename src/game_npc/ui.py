"""Streamlit view; no model initialization at import time."""

from dataclasses import replace

from game_npc.bootstrap import build_conversation
from game_npc.config import Settings


def main():
    import streamlit as st

    st.set_page_config(page_title="NPC 对话实验室", page_icon="💬", layout="wide")
    st.title("NPC 对话实验室")
    st.caption("中文角色对话 · 可信任务状态 · 带来源的知识检索")
    try:
        initial = Settings.from_env()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    with st.sidebar:
        st.header("演示设置")
        selected_mode = st.selectbox(
            "模型模式",
            ["demo", "live"],
            index=0 if initial.mode == "demo" else 1,
            format_func=lambda x: "本地演示（无需密钥）" if x == "demo" else "在线千问（需要密钥）",
        )
        player = st.selectbox("演示玩家", ["1001", "1002"])
        report = st.toggle("只读进展报告")
        if st.button("清空对话", use_container_width=True):
            if "conversation" in st.session_state:
                st.session_state.conversation.clear()
        st.caption("任务与金币均为本地演示数据。切换玩家会新建对话，任务状态保留。")
    settings = replace(initial, mode=selected_mode)
    identity = (settings, player)
    if st.session_state.get("identity") != identity:
        try:
            st.session_state.conversation = build_conversation(settings, player)
            st.session_state.identity = identity
        except (ValueError, RuntimeError, OSError):
            st.error("无法打开本地状态目录，请检查 GAME_NPC_STATE_DIR 及目录权限。")
            st.stop()
    conversation = st.session_state.conversation
    if settings.mode == "demo":
        st.info("本地演示使用规则回复和关键词检索，可验证任务流程；自然语言能力需切换在线模式。")
    elif not settings.api_key:
        st.warning("请在启动终端设置 DASHSCOPE_API_KEY 后重启；当前在线模式尚未连接。")
    with st.sidebar:
        st.subheader("知识库")
        status = conversation.knowledge.status()
        st.caption(f"检索模式：{settings.retrieval} · 分片：{status.get('chunks', 0)}")
        if not status.get("ready") or status.get("needs_ingest"):
            st.warning("请构建 / 同步知识索引")
        if st.button("构建 / 同步知识库", use_container_width=True):
            try:
                with st.spinner("正在同步资料..."):
                    result = conversation.knowledge.ingest()
                st.success(f"已索引 {result['files']} 个文件、{result['chunks']} 个分片")
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
        st.caption(f"状态目录：{settings.state_dir}")
    chat_column, state_column = st.columns([3, 2])
    with state_column:
        st.subheader("演示任务面板")
        info = conversation.game.player_info()
        st.write(f"{info['name']} · {info['level']} 级 · {info['region']}")
        st.metric("金币 / 经验", f"{info['gold']} / {info['experience']}")
        for task in conversation.game.player_tasks():
            st.markdown(f"**{task['task_id']} · {task['name']}**")
            st.progress(
                task["progress"] / task["target"],
                text=f"{task['status']} · {task['progress']}/{task['target']}",
            )
            st.caption("已领奖" if task["reward_claimed"] else "未领奖")
        with st.expander("演示事件"):
            st.caption("模拟可信游戏事件增加 T001 采集进度，聊天和模型没有这个权限。")
            if st.button("模拟采集一次"):
                try:
                    task = next(
                        t for t in conversation.game.player_tasks() if t["task_id"] == "T001"
                    )
                    conversation.game.record_progress(
                        "T001", min(task["target"], task["progress"] + 1)
                    )
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
    with chat_column:
        for message in conversation.history:
            st.chat_message(message["role"]).write(message["content"])
        query = st.chat_input(
            "试试：我的任务 / 领取 T002 奖励 / NPC 对话规范",
            disabled=settings.mode == "live" and not settings.api_key,
            max_chars=4000,
        )
        if query:
            st.chat_message("user").write(query)
            try:
                with st.spinner("正在生成报告..." if report else "NPC 正在回应..."):
                    conversation.reply(query, "report" if report else "dialogue")
                st.rerun()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(f"本轮未完成：{exc}")
                st.caption("如涉及任务操作，可在右侧面板核对结果后重新提交。")
        if conversation.last_sources:
            with st.expander("本轮参考资料"):
                for source in conversation.last_sources:
                    st.markdown(f"**{source['source']}**")
                    st.text(source["text"])


if __name__ == "__main__":
    main()
