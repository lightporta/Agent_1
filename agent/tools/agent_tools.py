import os
from utils.logger_handler import logger
from langchain_core.tools import tool
from rag.rag_service import RagSummarizeService
import random
from utils.config_handler import agent_conf
from utils.path_tool import get_abs_path

rag = RagSummarizeService()

user_ids = ["1001", "1002", "1003", "1004", "1005", "1006", "1007", "1008", "1009", "1010",]
month_arr = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06",
             "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", ]

external_data = {}


@tool(description=(
    "入参为query（检索词），从向量库精准检索NPC角色设定、对话规范、任务体系、世界观设定、异常处理方案等相关专业资料。"
    "出参为字符串类型的NPC设定资料内容，包含与检索词匹配的精准人设、话术、规则、剧情信息。"
    "使用场景：当回应用户对话需要补充NPC人设、游戏世界观、任务规则、话术规范，现有信息无法精准贴合人设回应时，调用此工具获取专业内容。"
    "调用规则：必须传入纯文本字符串类型的query参数，参数为贴合玩家对话的核心检索词。"
))
def rag_summarize(query: str) -> str:
    return rag.rag_summarize(query)


@tool(description=(
    "无入参，精准获取当前发起对话的玩家基础信息，包含玩家ID、等级、职业、所在区域、剧情进度、阵营声望、NPC好感度。"
    "出参为字符串类型的玩家结构化基础信息。"
    "使用场景：当需要基于玩家的当前等级、剧情进度、声望、好感度，调整对话内容、任务发布权限、交互态度时，调用此工具。"
    "调用规则：无需传入任何参数，直接触发调用即可。"
))
def get_player_info() -> str:
    return random.choice(user_ids)


@tool(description=(
    "无入参，精准获取当前玩家的任务列表，包含已接取任务、完成进度、已交付任务、失败任务。"
    "出参为字符串类型的玩家任务结构化数据，包含任务ID、任务名称、完成进度、接取时间、截止时间。"
    "使用场景：当玩家询问任务进度、交付任务、接取系列任务、需要校验任务前置条件时，调用此工具。"
    "调用规则：无需传入任何参数，直接触发调用即可。"
))
def get_player_task() -> str:
    return random.choice(month_arr)


@tool(description=(
    "入参为task_id（任务ID）、task_status（任务状态），更新玩家对应任务的进度/状态，"
    "支持「进行中/已完成/已失败/已放弃」四种状态。"
    "出参为字符串类型的更新结果，包含是否更新成功、玩家任务最新进度。"
    "使用场景：当玩家完成任务、放弃任务、任务失败，需要更新玩家任务状态时，调用此工具。"
    "调用规则：必须同时传入纯文本字符串类型的task_id和task_status参数，task_status严格遵循指定的四种状态枚举。"
))
def update_player_task(task_id: str, task_status: str) -> str:
    logger.info(f"[update_player_task] task_id={task_id}, task_status={task_status}")
    return f"任务{task_id}状态已更新为：{task_status}"


@tool(description=(
    "入参为keyword（关键词），获取游戏世界观、地图、剧情、NPC关系、历史事件等相关设定信息。"
    "出参为字符串类型的游戏世界观结构化信息，与关键词精准匹配。"
    "使用场景：当玩家询问游戏世界观、剧情背景、地理设定、其他NPC信息，需要精准回应时，调用此工具。"
    "调用规则：必须传入纯文本字符串类型的keyword参数，参数为玩家提问的核心关键词。"
))
def get_game_world_info(keyword: str) -> str:
    logger.info(f"[get_game_world_info] keyword={keyword}")
    return f"已检索到与「{keyword}」相关的世界观设定信息"


def generate_external_data():
    """
    {
        "user_id": {
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            ...
        },
        "user_id": {
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            ...
        },
        "user_id": {
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            "month" : {"特征": xxx, "效率": xxx, ...}
            ...
        },
        ...
    }
    :return:
    """
    if not external_data:
        external_data_path = get_abs_path(agent_conf["external_data_path"])

        if not os.path.exists(external_data_path):
            raise FileNotFoundError(f"外部数据文件{external_data_path}不存在")

        with open(external_data_path, "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                arr: list[str] = line.strip().split(",")

                user_id: str = arr[0].replace('"', "")
                feature: str = arr[1].replace('"', "")
                efficiency: str = arr[2].replace('"', "")
                consumables: str = arr[3].replace('"', "")
                comparison: str = arr[4].replace('"', "")
                time: str = arr[5].replace('"', "")

                if user_id not in external_data:
                    external_data[user_id] = {}

                external_data[user_id][time] = {
                    "特征": feature,
                    "效率": efficiency,
                    "耗材": consumables,
                    "对比": comparison,
                }


@tool(description=(
    "入参为task_id（任务ID）、player_id（玩家ID），为玩家发放对应任务的奖励，包含金币、经验、道具、装备、声望、好感度。"
    "出参为字符串类型的奖励发放结果，包含是否发放成功、玩家获得的奖励明细。"
    "使用场景：当玩家完成任务校验通过，需要发放任务奖励时，调用此工具。"
    "调用规则：必须同时传入纯文本字符串类型的task_id和player_id参数，player_id可通过get_player_info工具获取。"
))
def grant_task_reward(task_id: str, player_id: str) -> str:
    generate_external_data()

    try:
        return str(external_data[player_id])
    except KeyError:
        logger.warning(f"[grant_task_reward]未能检索到玩家：{player_id}的奖励数据")
        return ""


@tool(description=(
    "无入参，调用后触发中间件自动为剧情对话场景动态注入上下文信息，为后续提示词切换、人设适配、剧情处理提供上下文支撑。"
    "出参：无返回值，仅完成上下文注入的底层操作。"
    "使用场景：仅当明确识别出玩家核心意图为「剧情对话/任务交互/闲聊交互」（如'你好''我来交任务''给我发布个任务'）时，优先调用此工具；非对话交互场景严禁调用。"
    "调用规则："
    "1. 无需传入任何参数，直接触发调用即可；"
    "2. 禁用场景：玩家仅咨询游戏BUG、账号问题、现实相关内容等非游戏内对话场景时，绝对不调用此工具。"
))
def fill_context_for_dialogue():
    return "fill_context_for_dialogue已调用"