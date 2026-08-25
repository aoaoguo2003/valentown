"""世界状态与感知规则：现在几点、谁在哪、哪里开着门、还有没有位子。

这一层最重要的设计约束是**信息不对称**：

    世界知道所有人在哪，但没有任何一个居民知道。

居民只能看见和自己处在同一区域的人。想知道远处某人在哪，只能靠通信去
打听——如果每个人都能随时读取全局位置表，通信就失去了存在的理由，多智能体
之间也就没有协作可言了。

这个约束是用代码结构强制的，不是靠 prompt 叮嘱模型"请不要作弊"：决策上下文
里根本拿不到别人的位置，拒绝动作时给出的理由也刻意不透露对方的去向。这和项目
既有的隐私设计一脉相承——卧室从不进入目的地白名单，所以模型没有"闯进卧室"
这个选项可选。
"""

from agent_state import parse_clock_to_minutes
from tools import AGENT_NAMES

# 各公共区域的营业时间（游戏内分钟，左闭右开）。
# 公园与住宅不在表内：公园全天开放，家永远可回。
OPENING_HOURS = {
    "Café_bar": (7 * 60, 22 * 60),      # 早餐到夜宵
    "Supermarket": (8 * 60, 21 * 60),
    "Pharmacy": (9 * 60, 18 * 60),      # 药房关得早
}

# 谁经营哪家店。老板不占顾客名额，也可以在非营业时间进自己的店
# （备货、盘点）。Café_bar 没有居民经营，那个位子始终空着。
SHOP_OWNERS = {
    "Supermarket": "Ron Parker",
    "Pharmacy": "Ella Parker",
}

# 每家店同时容纳的顾客数；老板不计入。
CUSTOMER_CAPACITY = 3

# 有营业时间和容量限制的区域，就是上面两张表覆盖的商业区域。
COMMERCIAL_AREAS = set(OPENING_HOURS)


def area_of(location):
    """锚点 "Café_bar.Counter" 所属的区域是 "Café_bar"。"""
    return str(location or "").split(".")[0]


def format_clock(minutes):
    """把游戏内分钟数格式化成前端同款的 "7:00 AM" 时钟文本。"""
    minutes = int(minutes) % (24 * 60)
    hour24, minute = divmod(minutes, 60)
    suffix = "AM" if hour24 < 12 else "PM"
    return f"{hour24 % 12 or 12}:{minute:02d} {suffix}"


class World:
    """某一刻的世界快照：时间，以及每个居民所在的位置。

    调用方（路由层）负责在持锁状态下构造它，因此它一旦建好就是只读的；
    并发下"决策依据的快照已经过期"这件事，由提交前重新构造快照来处理。
    """

    def __init__(self, time_text=None, time_minutes=None, agent_locations=None,
                 unread_counts=None, balances=None, weather_code=None, life_day=1,
                 holdings=None):
        if time_minutes is None:
            time_minutes = parse_clock_to_minutes(time_text)
        self.time_minutes = int(time_minutes)
        self.time_text = format_clock(self.time_minutes)
        self.agent_locations = dict(agent_locations or {})
        # 未读信件数随快照一起取，而不是另外查一次：分两次拿会拼出一个
        # 从未真实存在过的状态（位置是这一刻的，未读数是下一刻的）。
        self.unread_counts = dict(unread_counts or {})
        # 余额同理：和位置、未读数在同一把锁里一起取，避免拼出一个
        # 从未真实存在过的世界状态。
        self.balances = dict(balances or {})
        # 天气随快照一起带进来：它是外部依赖，绝不能在裁决动作的路径上
        # 现取——那会把一次网络往返塞进锁里。
        self.life_day = int(life_day or 1)
        self.weather_code = weather_code
        # 谁手上有什么。这是**世界视角**的全量数据，只用于任务判定；
        # 居民自己的那份由 check_balance 返回，别人的东西看不到。
        self.holdings = dict(holdings or {})

    # --- 感知：居民能知道什么 ---------------------------------------

    def visible_agents(self, agent_name):
        """``agent_name`` 此刻能看见的其他居民。

        可见性以**区域**为单位而非锚点：同在咖啡馆就算照面，不要求挤在
        同一张桌子旁。这是居民唯一能合法获得的他人位置信息。"""
        here = area_of(self.agent_locations.get(agent_name))
        if not here:
            return []
        return sorted(
            name
            for name, location in self.agent_locations.items()
            if name != agent_name and area_of(location) == here
        )

    def unread_for(self, agent_name):
        """某人有多少封未读——只看得到自己的，看不到别人的。"""
        return int(self.unread_counts.get(agent_name, 0))

    def balance_for(self, agent_name):
        """某人有多少钱——**只看得到自己的**，别人的钱是私事。"""
        from economy import INITIAL_BALANCE

        return int(self.balances.get(agent_name, INITIAL_BALANCE))

    def holdings_for(self, agent_name):
        """某人身上带着什么——同样只看得到自己的。"""
        return dict(self.holdings.get(agent_name) or {})

    def weather_text(self):
        """此刻的天气，一个词。抬头就能看见，所以它免费进决策上下文。"""
        from weather import describe

        return describe(self.weather_code) if self.weather_code is not None else None

    def weather_blocks_outdoors(self):
        """现在的天气是不是恶劣到不该待在露天。

        只拦大雨、暴雪、雷暴这一类；毛毛雨和小雨照常——撑把伞就行。
        连小雨都拦的话，居民一个雨天什么都干不成，约束就成了瘫痪。
        """
        from weather import is_severe

        return self.weather_code is not None and is_severe(self.weather_code)

    def agents_in_area(self, area, exclude=None):
        """某区域内的居民。

        ⚠️ 这是**世界视角**的查询，不是居民视角。只允许在裁决动作、
        或者构造"你到达之后看见了什么"时使用——那时居民本人已经身处
        该区域，看得见现场。绝不能拿它去回答"某人现在在哪"。"""
        return sorted(
            name
            for name, location in self.agent_locations.items()
            if name != exclude and area_of(location) == area
        )

    # --- 规则：世界允许什么 -----------------------------------------

    def is_open(self, area, agent_name=None):
        """该区域此刻是否对 ``agent_name`` 开放。店主不受营业时间限制。"""
        if area not in OPENING_HOURS:
            return True                      # 公园与住宅全天开放
        if agent_name and SHOP_OWNERS.get(area) == agent_name:
            return True                      # 店主可以提前来备货
        open_minute, close_minute = OPENING_HOURS[area]
        return open_minute <= self.time_minutes < close_minute

    def opening_hours_text(self, area):
        open_minute, close_minute = OPENING_HOURS[area]
        return f"{format_clock(open_minute)} to {format_clock(close_minute)}"

    def customer_count(self, area, exclude=None):
        """区域内的顾客数——店主在自己店里不算顾客。"""
        owner = SHOP_OWNERS.get(area)
        return sum(
            1
            for name in self.agents_in_area(area, exclude=exclude)
            if name != owner
        )

    def has_room(self, area, agent_name=None):
        """``agent_name`` 还挤不挤得进这个区域。"""
        if area not in COMMERCIAL_AREAS:
            return True                      # 公园是开放空间，家里不数座位
        if SHOP_OWNERS.get(area) == agent_name:
            return True                      # 店主总有自己的位置
        return self.customer_count(area, exclude=agent_name) < CUSTOMER_CAPACITY

    def is_present(self, agent_name, area):
        """某人是否就在该区域——**仅用于裁决**，判定结果不可回传细节。"""
        return agent_name in AGENT_NAMES and area_of(self.agent_locations.get(agent_name)) == area


# 没有世界状态时使用的空世界：一切开放、一切有位、看不见任何人。
# 它让 handler 在缺少世界快照时退化为"只做结构校验"，与改造前的行为一致。
EMPTY_WORLD = World(time_minutes=12 * 60, agent_locations={})
