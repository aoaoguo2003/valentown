"""小镇的地理与居民名册。

这些常量本质上就是 ``move_to`` 的参数取值范围——把它们放在工具定义旁边，
比散在 agent 类里更贴切。整个包里只有这个模块不依赖任何其它项目模块，
所以它可以被 world.py 之类的底层模块安全导入而不引起循环。
"""

HOME_AREAS = [
    "Ron_home",
    "Ella_home",
    "Arthur_home",
    "Mia_home",
    "Emma_home",
    "Gavin_home",
    "Adam_home",
]

HOME_ROOM_LOCATIONS = [
    "Living_room",
    "Kitchen",
    "Dining_table",
    "Dinning_room",
    "Study_corner",
    "Desk",
    "Bookshelf",
    "Reading_chair",
    "Sofa",
    "Chair",
    "Porch",
    "Window",
]

PUBLIC_LOCATIONS = [
    "Park.Chair",
    "Park.River",
    "Park.Tree",
    "Park.Bench",
    "Park.Flower_bed",
    "Park.Playground",
    "Park.Bridge",
    "Café_bar.Boss",
    "Café_bar.Customer_cafe",
    "Café_bar.Customer_bar",
    "Café_bar.Window_seat",
    "Café_bar.Corner_table",
    "Café_bar.Counter",
    "Café_bar.Patio",
    "Supermarket.Boss",
    "Supermarket.Customer_drink",
    "Supermarket.Customer_eat",
    "Supermarket.Checkout",
    "Supermarket.Fruit_shelf",
    "Supermarket.Storage",
    "Supermarket.Entrance_aisle",
    "Pharmacy.Boss",
    "Pharmacy.Customer_left",
    "Pharmacy.Customer_right",
    "Pharmacy.Prescription_counter",
    "Pharmacy.Medicine_shelf",
    "Pharmacy.Waiting_chair",
    "Pharmacy.Consult_room",
]

AGENT_NAMES = [
    "Ron Parker",
    "Ella Parker",
    "Emma Harris",
    "Gavin Harris",
    "Adam Harris",
    "Mia Thompson",
    "Arthur Morgan",
]

# 单次动作的决策边界，单位为游戏内分钟。
MIN_ACTION_MINUTES = 15
MAX_ACTION_MINUTES = 180
DEFAULT_ACTION_MINUTES = 60

# 睡觉另算：它是唯一可以横跨整夜的动作，普通动作的 180 分钟上限套不住它。
# 上限 12 小时不是"限制睡多久"，是防止模型填出 99999 这种荒谬值——
# 一个动作的时长最终会变成世界时钟往前跳的幅度。
MIN_SLEEP_MINUTES = 30
MAX_SLEEP_MINUTES = 12 * 60


def build_allowed_destinations():
    """代理可选择的所有可导航目的地锚点。卧室和洗手间被特意排除在
    HOME_ROOM_LOCATIONS 之外，因此隐私规则是通过结构设计来强制保证的，
    而不是依靠 prompt 指令来约束。"""
    home_locations = [
        f"{home_area}.{room_name}"
        for home_area in HOME_AREAS
        for room_name in HOME_ROOM_LOCATIONS
    ]
    return home_locations + PUBLIC_LOCATIONS


ALLOWED_DESTINATIONS = build_allowed_destinations()


# 露天的锚点。注意这是**锚点级**判断而非区域级：Café_bar.Patio 是露台，
# 同一家店里既有室内也有户外。营业时间和容量按区域算，天气按锚点算——
# 这个差别是真实的，不是为了统一而统一。
OUTDOOR_ANCHORS = frozenset(
    [f"Park.{room}" for room in
     ["Chair", "River", "Tree", "Bench", "Flower_bed", "Playground", "Bridge"]]
    + ["Café_bar.Patio"]
)


def is_outdoor(location):
    """这个锚点是不是露天的——下大雨时待不住的那种。"""
    return str(location or "") in OUTDOOR_ANCHORS


# 可以约见的地方，按**区域**而非锚点——同在一个区域就算碰上面了，
# 不必挤在同一张长椅上。这和 world.visible_agents() 用的粒度一致。
MEETING_AREAS = sorted(
    set(HOME_AREAS) | {location.split(".")[0] for location in PUBLIC_LOCATIONS}
)
