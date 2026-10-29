"""Streamlit view; no model initialization at import time."""

import json
from dataclasses import replace

from game_npc.bootstrap import build_conversation
from game_npc.cognition import CHECK_LABELS
from game_npc.config import Settings
from game_npc.persona import WorldContext, builtin_profiles, load_profile, parse_profile_json


def main():
    import streamlit as st

    st.set_page_config(page_title="NPC 对话实验室", page_icon="💬", layout="wide")
    st.title("NPC 对话实验室")
    st.caption("中文角色对话 · 可信任务状态 · 带来源的知识检索")
    try:
        initial = Settings.from_env()
        external_profile = load_profile(initial.npc_profile_path)
        presets = builtin_profiles()
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
        preset_key = st.selectbox(
            "NPC 角色",
            ["external", *presets],
            format_func=lambda key: (
                "外部 / 默认档案"
                if key == "external"
                else f"{presets[key].name} · {presets[key].profession}"
            ),
        )
        base_profile = external_profile if preset_key == "external" else presets[preset_key]
        base_fingerprint = base_profile.fingerprint()
        with st.expander("外部角色档案（JSON）"):
            st.caption("游戏系统可传入同样的档案。应用修改后会清空旧角色对话，保留玩家资产。")
            with st.form("npc_profile_form"):
                profile_text = st.text_area(
                    "角色 JSON",
                    value=json.dumps(base_profile.to_dict(), ensure_ascii=False, indent=2),
                    key=f"npc_json_{base_fingerprint}_{st.session_state.get('npc_editor_revision', 0)}",
                    height=260,
                    max_chars=65536,
                )
                apply_profile = st.form_submit_button("应用角色档案")
            if apply_profile:
                try:
                    custom_profile = parse_profile_json(profile_text)
                    st.session_state.npc_override = (base_fingerprint, custom_profile.to_dict())
                except ValueError as exc:
                    st.error(f"角色配置错误：{exc}")
            if st.button("恢复所选档案"):
                st.session_state.pop("npc_override", None)
                st.session_state.npc_editor_revision = (
                    st.session_state.get("npc_editor_revision", 0) + 1
                )
                st.rerun()
        profile = base_profile
        custom = st.session_state.get("npc_override")
        if custom and custom[0] == base_fingerprint:
            from game_npc.persona import NPCProfile

            profile = NPCProfile.from_dict(custom[1])
        with st.expander("实时情境（外部输入演示）"):
            st.caption("这些值模拟可信游戏系统输入；玩家聊天不能自行修改危险、关系或区域。")
            context_key = profile.fingerprint()
            current_region = st.text_input(
                "当前区域", value=profile.region, max_chars=128, key=f"region_{context_key}"
            )
            day_period = st.selectbox(
                "时段", ["day", "dusk", "night", "dawn"], key=f"day_{context_key}"
            )
            danger = st.slider("区域危险度", 0, 100, 0, key=f"danger_{context_key}")
            relationship = st.slider(
                "与当前玩家的关系", -100, 100, 0, key=f"relationship_{context_key}_{player}"
            )
            nearby_events = st.text_area(
                "附近事件（每行一条）", max_chars=2000, key=f"events_{context_key}"
            )
        try:
            context = WorldContext.from_dict(
                {
                    "region": current_region.strip() or profile.region,
                    "time_of_day": day_period,
                    "danger": danger,
                    "relationship": relationship,
                    "nearby_events": [
                        item.strip() for item in nearby_events.splitlines() if item.strip()
                    ],
                }
            )
        except ValueError as exc:
            st.error(f"情境配置错误：{exc}")
            st.stop()
        report = st.toggle("只读进展报告")
        if st.button("清空对话", use_container_width=True):
            if "conversation" in st.session_state:
                st.session_state.conversation.clear()
        st.caption("任务与金币均为本地演示数据。切换玩家会新建对话，任务状态保留。")
    settings = replace(initial, mode=selected_mode)
    identity = (settings, player, profile.fingerprint())
    if st.session_state.get("identity") != identity:
        try:
            st.session_state.conversation = build_conversation(
                settings, player, profile=profile, context=context
            )
            st.session_state.identity = identity
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(f"初始化失败：{exc}")
            st.stop()
    conversation = st.session_state.conversation
    conversation.set_context(context)
    if settings.mode == "demo":
        st.info("本地演示使用规则回复和关键词检索，可验证任务流程；自然语言能力需切换在线模式。")
    elif not settings.api_key:
        st.warning("请在启动终端设置 DASHSCOPE_API_KEY 后重启；当前在线模式尚未连接。")
    with st.sidebar:
        st.subheader("知识库")
        try:
            status = conversation.knowledge.status()
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
            status = {}
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
        st.subheader("当前 NPC", anchor="npc-profile")
        st.text(f"{profile.name} · {profile.profession}")
        st.text(f"所在区域：{context.region or profile.region}")
        st.caption("性格：" + "、".join(profile.personality))
        st.caption("目标：" + " / ".join(profile.goals))
        st.caption("价值偏好：" + " > ".join(profile.values))
        st.caption("检查顺序：" + " → ".join(CHECK_LABELS[item] for item in profile.thinking_order))
        st.subheader("演示任务面板")
        try:
            info = conversation.game.player_info()
            tasks = conversation.game.player_tasks()
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
            st.stop()
        st.write(f"{info['name']} · {info['level']} 级 · {info['region']}")
        st.metric("金币 / 经验", f"{info['gold']} / {info['experience']}")
        for task in tasks:
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
        if st.session_state.get("turn_error"):
            st.error(st.session_state.pop("turn_error"))
            st.caption("如涉及任务操作，可在右侧面板核对结果后重新提交。")
        for message in conversation.history:
            st.chat_message(message["role"]).write(message["content"])
        query = st.chat_input(
            "试试：你是谁 / 城外冒险建议 / 领取 T002 奖励",
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
                st.session_state.turn_error = f"本轮未完成：{exc}"
                st.rerun()
        if conversation.last_decision:
            with st.expander("角色决策摘要（程序生成）"):
                st.caption("展示角色目标、候选策略、规则约束和动作结果，不展示模型内部推理。")
                st.json(conversation.last_decision)
        if conversation.last_sources:
            with st.expander("本轮参考资料"):
                for source in conversation.last_sources:
                    st.markdown(f"**{source['source']}**")
                    st.text(source["text"])


if __name__ == "__main__":
    main()
