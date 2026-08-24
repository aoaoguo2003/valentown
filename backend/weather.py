"""天气：这个项目里唯一的真实外部依赖。

其它一切——库存、钱、信件——都是本地状态，改不改由我们说了算。天气不是：
它来自一个真实的 HTTP 接口，**会超时、会限流、会 5xx**。所以重试、指数退避、
jitter、熔断、降级这一整套东西在这里才第一次有真正的用武之地；用一个模拟的
天气来做，它们全是没人走过的死代码。

## 三层保底

    ① 真实调用   Open-Meteo（免费、无需 API key），每个游戏日只调一次，
                 缓存当天 24 小时的逐小时数据
    ② 失败重试   指数退避 + jitter，次数用尽即放弃
    ③ 兜底降级   按 life_day 做种子的确定性伪天气

第 ③ 层不是妥协，而是这套设计的一部分：**别人 clone 下来没网也能跑**，
测试也不必打真实网络。真实系统里"下游挂了就走降级"本来就是标准做法。

## 为什么一天只调一次

七个居民 × 一天十几轮决策 = 上百次外部调用，纯属浪费；而且逐小时预报本来
就是一次拿一天。缓存把外部依赖的调用面压到最小——**每多打一次外部接口，
就多一次失败的机会**。

## jitter 为什么必须有

多个居民可能在同一时刻发现缓存失效而同时去取。若退避时间完全相同，它们会
一起重试、一起再失败——惊群效应。加一点随机抖动把重试时刻散开，代价是一行
代码。

## 选伦敦不是因为它特别，是因为它多雨

天气必须真的会变，否则这个系统对决策毫无影响：选个常年晴天的地方，
"下雨改计划"那条分支永远走不到，等于没做。
"""

import json
import random
import threading
import time
import urllib.error
import urllib.request

from config import (
    WEATHER_ENABLED,
    WEATHER_LATITUDE,
    WEATHER_LONGITUDE,
    WEATHER_TIMEOUT_SECONDS,
    WEATHER_TIMEZONE,
)

API_URL = "https://api.open-meteo.com/v1/forecast"

MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
JITTER_SECONDS = 0.4          # 退避时刻的随机抖动，防止多个居民一起重试

# 连续失败到这个次数就熔断：当天不再尝试，直接走降级。
# 没有它的话，接口挂掉时每个决策周期都要白等一轮超时。
FAILURE_THRESHOLD = 2

# WMO 天气代码（Open-Meteo 的 weather_code 用的就是这套标准）。
WMO_DESCRIPTIONS = {
    0: "clear",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "heavy freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}

# 恶劣到不该待在户外的天气。刻意**不含**毛毛雨和小雨——撑把伞就行；
# 若连小雨都拦，居民一个雨天什么都干不成，约束就成了瘫痪。
SEVERE_CODES = frozenset({65, 67, 75, 82, 86, 95, 96, 99})

# 降级用的天气池：晴天占多数，但恶劣天气必须够常见，否则那条分支走不到。
FALLBACK_CODES = [0, 1, 2, 3, 3, 61, 63, 65, 80, 95]


def describe(code):
    return WMO_DESCRIPTIONS.get(int(code), "strange weather")


def is_severe(code):
    return int(code) in SEVERE_CODES


class WeatherService:
    """按游戏日缓存的天气客户端。

    线程安全：多个居民会并发要天气，取数与写缓存都在同一把锁里。
    """

    def __init__(self, fetcher=None):
        self._lock = threading.Lock()
        self._cache = {}              # life_day -> 24 个小时的 weather_code
        self._sources = {}            # life_day -> "live" | "fallback"
        self._failures = 0            # 连续失败次数，用于熔断
        self._fetch = fetcher or self._fetch_live

    # --- 对外接口 ---------------------------------------------------

    def for_day(self, life_day):
        """取某个游戏日的 24 小时天气码，必要时现取并缓存。"""
        life_day = int(life_day or 1)
        with self._lock:
            if life_day in self._cache:
                return list(self._cache[life_day])

            codes, source = self._load_day(life_day)
            self._cache[life_day] = codes
            self._sources[life_day] = source
            return list(codes)

    def at(self, life_day, time_minutes):
        """某个游戏日、某一刻的天气码。游戏时钟走到几点就用那一小时。"""
        hour = max(0, min(23, int(time_minutes) // 60))
        return self.for_day(life_day)[hour]

    def source_for(self, life_day):
        """这一天的天气是真取来的还是降级来的——供追踪与测试断言。"""
        with self._lock:
            return self._sources.get(int(life_day or 1))

    def outlook(self, life_day, time_minutes, hours=6):
        """从当前时刻起若干小时的预报，压成一串 ``(时刻, 描述)``。

        这是 ``check_weather`` 的数据源，也是它值得花一步去调的理由：
        当前天气免费进上下文（抬头就能看见），**未来**得查预报。
        """
        codes = self.for_day(life_day)
        start = max(0, min(23, int(time_minutes) // 60))
        end = min(24, start + max(1, int(hours)))
        return [(hour, codes[hour]) for hour in range(start, end)]

    def reset(self):
        with self._lock:
            self._cache.clear()
            self._sources.clear()
            self._failures = 0

    # --- 内部实现 ---------------------------------------------------

    def _load_day(self, life_day):
        """真实调用 + 重试 + 熔断 + 降级。调用方须持有 ``self._lock``。"""
        if not WEATHER_ENABLED:
            return self._fallback_codes(life_day), "disabled"

        if self._failures >= FAILURE_THRESHOLD:
            # 熔断打开：不再白等超时，直接降级。
            return self._fallback_codes(life_day), "fallback"

        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                codes = self._fetch()
                if codes and len(codes) >= 24:
                    self._failures = 0            # 成功即闭合熔断
                    return [int(code) for code in codes[:24]], "live"
                last_error = "short or empty payload"
            except Exception as error:            # 网络层什么都可能抛
                last_error = str(error)

            if attempt < MAX_RETRIES - 1:
                # 指数退避 + jitter：抖动把多个居民的重试时刻散开，
                # 否则它们会一起重试、一起再失败（惊群效应）。
                backoff = BASE_BACKOFF_SECONDS * (2 ** attempt)
                time.sleep(backoff + random.uniform(0, JITTER_SECONDS))

        self._failures += 1
        print(f"Weather lookup failed ({last_error}); falling back to simulated weather.")
        return self._fallback_codes(life_day), "fallback"

    def _fetch_live(self):
        """向 Open-Meteo 取当天逐小时的天气码。免费接口，无需 API key。"""
        query = (
            f"?latitude={WEATHER_LATITUDE}&longitude={WEATHER_LONGITUDE}"
            f"&hourly=weather_code&forecast_days=1&timezone={WEATHER_TIMEZONE}"
        )
        request = urllib.request.Request(
            API_URL + query,
            headers={"User-Agent": "valentown-simulation"},
        )
        with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise urllib.error.HTTPError(
                    API_URL, response.status, "unexpected status", response.headers, None)
            payload = json.load(response)
        return (payload.get("hourly") or {}).get("weather_code") or []

    def _fallback_codes(self, life_day):
        """确定性的伪天气：同一个游戏日永远得到同一份天气。

        用 life_day 做种子而不是真随机，是为了让降级路径**可复现**——
        否则同一天的两次查询可能给出不同天气，模型会看到自相矛盾的世界。
        """
        generator = random.Random(f"valentown-weather-{life_day}")
        return [generator.choice(FALLBACK_CODES) for _ in range(24)]


weather_service = WeatherService()
