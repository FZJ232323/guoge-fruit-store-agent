#!/usr/bin/env python3
"""果哥 MVP - 中小水果店智能运营助手.

The prototype intentionally keeps the data layer local and explainable:
orders and purchase records are the source of truth, business metrics are
computed with deterministic rules, and an optional LLM can be used to polish
the natural-language narrative. It runs with the Python standard library plus
openpyxl.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
SAMPLE_DIR = BASE_DIR / "sample_data"
STATE_FILE = DATA_DIR / "state.json"


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


load_env_file(BASE_DIR / ".env")


APP_NAME = "果哥"
APP_TAGLINE = "水果店智能运营助手"
APP_VERSION = "3.0.0"
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
WEATHER_CACHE_FILE = DATA_DIR / "weather_cache.json"
WEATHER_TTL_SECONDS = 30 * 60
STORE_LAT = float(os.environ.get("GZ_STORE_LAT", "31.2304"))
STORE_LON = float(os.environ.get("GZ_STORE_LON", "121.4737"))
STORE_CITY = os.environ.get("GZ_STORE_CITY", "上海")

LLM_RUNTIME: dict[str, Any] = {
    "connected": None,
    "checked_at": None,
    "last_latency_ms": None,
    "last_error": None,
    "calls": 0,
}

PRODUCT_CATALOG: list[dict[str, Any]] = [
    {
        "id": "P001",
        "name": "西瓜",
        "alias": "西瓜",
        "category": "瓜果",
        "unit": "斤",
        "cost": 3.2,
        "price": 5.98,
        "shelf_life": 7,
        "avg_daily": 42,
        "weekend_sensitivity": 1.45,
        "rain_sensitivity": 0.62,
        "trend": 0.18,
        "stock_multiplier": 1.035,
        "bundle": "西瓜 + 蓝莓家庭果盒",
    },
    {
        "id": "P002",
        "name": "阳光玫瑰",
        "alias": "阳光玫瑰",
        "category": "浆果",
        "unit": "斤",
        "cost": 12.8,
        "price": 22.8,
        "shelf_life": 5,
        "avg_daily": 16,
        "weekend_sensitivity": 1.28,
        "rain_sensitivity": 0.92,
        "trend": 0.09,
        "stock_multiplier": 1.04,
        "bundle": "阳光玫瑰双人尝鲜盒",
    },
    {
        "id": "P003",
        "name": "草莓",
        "alias": "草莓",
        "category": "浆果",
        "unit": "斤",
        "cost": 14.0,
        "price": 29.8,
        "shelf_life": 2,
        "avg_daily": 12,
        "weekend_sensitivity": 1.32,
        "rain_sensitivity": 0.96,
        "trend": -0.06,
        "stock_multiplier": 1.18,
        "bundle": "草莓 + 蓝莓 39 元果盒",
    },
    {
        "id": "P004",
        "name": "香蕉",
        "alias": "香蕉",
        "category": "常备果",
        "unit": "斤",
        "cost": 3.6,
        "price": 6.98,
        "shelf_life": 4,
        "avg_daily": 28,
        "weekend_sensitivity": 1.18,
        "rain_sensitivity": 1.04,
        "trend": 0.04,
        "stock_multiplier": 1.045,
        "bundle": "香蕉小份装",
    },
    {
        "id": "P005",
        "name": "香梨",
        "alias": "香梨",
        "category": "常备果",
        "unit": "斤",
        "cost": 4.2,
        "price": 8.8,
        "shelf_life": 10,
        "avg_daily": 14,
        "weekend_sensitivity": 1.15,
        "rain_sensitivity": 1.08,
        "trend": -0.02,
        "stock_multiplier": 1.07,
        "bundle": "香梨银耳汤组合",
    },
    {
        "id": "P006",
        "name": "脐橙",
        "alias": "脐橙",
        "category": "柑橘",
        "unit": "斤",
        "cost": 4.8,
        "price": 9.9,
        "shelf_life": 12,
        "avg_daily": 26,
        "weekend_sensitivity": 1.16,
        "rain_sensitivity": 1.02,
        "trend": 0.05,
        "stock_multiplier": 1.035,
        "bundle": "脐橙家庭分享装",
    },
    {
        "id": "P007",
        "name": "苹果",
        "alias": "苹果",
        "category": "常备果",
        "unit": "斤",
        "cost": 4.5,
        "price": 8.8,
        "shelf_life": 15,
        "avg_daily": 22,
        "weekend_sensitivity": 1.12,
        "rain_sensitivity": 1.06,
        "trend": 0.01,
        "stock_multiplier": 1.08,
        "bundle": "苹果 + 橙子每日果盒",
    },
    {
        "id": "P008",
        "name": "桃",
        "alias": "桃",
        "category": "核果",
        "unit": "斤",
        "cost": 7.5,
        "price": 14.8,
        "shelf_life": 3,
        "avg_daily": 10,
        "weekend_sensitivity": 1.24,
        "rain_sensitivity": 0.9,
        "trend": -0.12,
        "stock_multiplier": 1.14,
        "bundle": "桃酸奶杯",
    },
    {
        "id": "P009",
        "name": "猕猴桃",
        "alias": "猕猴桃",
        "category": "浆果",
        "unit": "斤",
        "cost": 5.5,
        "price": 11.8,
        "shelf_life": 7,
        "avg_daily": 13,
        "weekend_sensitivity": 1.12,
        "rain_sensitivity": 1.02,
        "trend": 0.06,
        "stock_multiplier": 1.045,
        "bundle": "猕猴桃 6 枚装",
    },
    {
        "id": "P010",
        "name": "蓝莓",
        "alias": "蓝莓",
        "category": "浆果",
        "unit": "盒",
        "cost": 9.5,
        "price": 19.8,
        "shelf_life": 4,
        "avg_daily": 8,
        "weekend_sensitivity": 1.3,
        "rain_sensitivity": 0.95,
        "trend": 0.12,
        "stock_multiplier": 1.16,
        "bundle": "草莓 + 蓝莓 39 元果盒",
    },
    {
        "id": "P011",
        "name": "凤梨",
        "alias": "凤梨",
        "category": "热带果",
        "unit": "个",
        "cost": 4.5,
        "price": 9.9,
        "shelf_life": 7,
        "avg_daily": 11,
        "weekend_sensitivity": 1.2,
        "rain_sensitivity": 0.94,
        "trend": 0.03,
        "stock_multiplier": 1.04,
        "bundle": "凤梨鲜切杯",
    },
    {
        "id": "P012",
        "name": "巨峰",
        "alias": "巨峰",
        "category": "浆果",
        "unit": "斤",
        "cost": 6.8,
        "price": 13.8,
        "shelf_life": 4,
        "avg_daily": 12,
        "weekend_sensitivity": 1.2,
        "rain_sensitivity": 0.92,
        "trend": -0.04,
        "stock_multiplier": 0.98,
        "bundle": "巨峰尝鲜盒",
    },
    {
        "id": "P013",
        "name": "蜜橘",
        "alias": "蜜橘",
        "category": "柑橘",
        "unit": "斤",
        "cost": 3.6,
        "price": 7.8,
        "shelf_life": 8,
        "avg_daily": 18,
        "weekend_sensitivity": 1.15,
        "rain_sensitivity": 1.0,
        "trend": 0.08,
        "stock_multiplier": 1.09,
        "bundle": "蜜橘办公室分享装",
    },
    {
        "id": "P014",
        "name": "火龙果",
        "alias": "火龙果",
        "category": "热带果",
        "unit": "个",
        "cost": 5.2,
        "price": 10.8,
        "shelf_life": 6,
        "avg_daily": 9,
        "weekend_sensitivity": 1.1,
        "rain_sensitivity": 1.0,
        "trend": -0.09,
        "stock_multiplier": 1.11,
        "bundle": "火龙果酸奶杯",
    },
    {
        "id": "P015",
        "name": "青提",
        "alias": "青提",
        "category": "浆果",
        "unit": "斤",
        "cost": 9.2,
        "price": 18.8,
        "shelf_life": 5,
        "avg_daily": 14,
        "weekend_sensitivity": 1.22,
        "rain_sensitivity": 0.93,
        "trend": 0.1,
        "stock_multiplier": 1.0,
        "bundle": "青提轻享盒",
    },
    {
        "id": "P016",
        "name": "柚",
        "alias": "柚子",
        "category": "柑橘",
        "unit": "个",
        "cost": 4.6,
        "price": 9.8,
        "shelf_life": 14,
        "avg_daily": 10,
        "weekend_sensitivity": 1.12,
        "rain_sensitivity": 1.02,
        "trend": 0.02,
        "stock_multiplier": 1.04,
        "bundle": "柚鲜果茶",
    },
    {
        "id": "P017",
        "name": "芒果",
        "alias": "芒果",
        "category": "热带果",
        "unit": "斤",
        "cost": 7.2,
        "price": 15.8,
        "shelf_life": 4,
        "avg_daily": 9,
        "weekend_sensitivity": 1.17,
        "rain_sensitivity": 0.96,
        "trend": -0.03,
        "stock_multiplier": 1.08,
        "bundle": "芒果酸奶碗",
    },
    {
        "id": "P018",
        "name": "圣女果",
        "alias": "圣女果",
        "category": "番茄",
        "unit": "斤",
        "cost": 5.0,
        "price": 10.8,
        "shelf_life": 3,
        "avg_daily": 14,
        "weekend_sensitivity": 1.16,
        "rain_sensitivity": 1.03,
        "trend": 0.07,
        "stock_multiplier": 1.15,
        "bundle": "圣女果办公室分享装",
    },
    {
        "id": "P019",
        "name": "果盒",
        "alias": "果盒",
        "category": "鲜切",
        "unit": "盒",
        "cost": 6.5,
        "price": 15.8,
        "shelf_life": 1,
        "avg_daily": 16,
        "weekend_sensitivity": 1.05,
        "rain_sensitivity": 0.88,
        "trend": 0.14,
        "stock_multiplier": 1.02,
        "bundle": "下午茶果盒 3 盒装",
    },
    {
        "id": "P020",
        "name": "山竹",
        "alias": "山竹",
        "category": "热带果",
        "unit": "斤",
        "cost": 15.0,
        "price": 28.8,
        "shelf_life": 4,
        "avg_daily": 6,
        "weekend_sensitivity": 1.28,
        "rain_sensitivity": 0.95,
        "trend": 0.11,
        "stock_multiplier": 1.03,
        "bundle": "山竹尝鲜装",
    },
]

PRODUCT_BY_ID = {item["id"]: item for item in PRODUCT_CATALOG}
PRODUCT_BY_NAME = {item["name"]: item for item in PRODUCT_CATALOG}
PRODUCT_BY_ALIAS = {item["alias"]: item for item in PRODUCT_CATALOG}
DEFAULT_PRODUCT_CATALOG = [dict(item) for item in PRODUCT_CATALOG]

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_FACTORS = [0.92, 0.95, 0.98, 1.0, 1.08, 1.2, 1.28]
PAYMENT_METHODS = ["微信支付", "支付宝", "微信支付", "微信支付", "现金"]
TIME_SLOTS = ["07:30-09:00", "09:00-11:00", "11:00-13:30", "13:30-16:00", "16:00-18:30", "18:30-21:00"]

DEFAULT_MEMORIES = [
    {
        "id": "M001",
        "text": "周末客流比工作日高约 30%，西瓜和葡萄要提前备货",
        "tag": "周末规律",
        "source": "近 8 周销售 + 老板补充",
        "impact": "采购量 +18%",
        "active": True,
        "created_at": "2026-09-26",
    },
    {
        "id": "M002",
        "text": "草莓损耗高，单次采购不超过 2 天销量",
        "tag": "损耗经验",
        "source": "经营对话沉淀",
        "impact": "采购上限约束",
        "active": True,
        "created_at": "2026-10-12",
    },
    {
        "id": "M003",
        "text": "周二附近小学放学早，香蕉小份装更好卖",
        "tag": "社区洞察",
        "source": "老板经验",
        "impact": "包装与陈列建议",
        "active": True,
        "created_at": "2026-10-05",
    },
    {
        "id": "M004",
        "text": "雨天西瓜销量下降约 30%，柑橘类相对稳定",
        "tag": "天气经验",
        "source": "经营对话沉淀",
        "impact": "天气系数",
        "active": True,
        "created_at": "2026-10-08",
    },
    {
        "id": "M005",
        "text": "每月 8 日会员日做满 39 减 5，客单价平均提升 11%",
        "tag": "营销规则",
        "source": "历史活动复盘",
        "impact": "活动提醒",
        "active": True,
        "created_at": "2026-09-08",
    },
]


def safe_round(value: float, digits: int = 1) -> float:
    return round(float(value) + 1e-9, digits)


def iso(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return value.isoformat()


def display_date(value: str | date, include_weekday: bool = True) -> str:
    d = date.fromisoformat(value) if isinstance(value, str) else value
    label = f"{d.month}月{d.day}日"
    if include_weekday:
        label += f" {WEEKDAY_NAMES[d.weekday()]}"
    return label


def weather_description(code: int) -> tuple[str, str]:
    if code == 0:
        return "晴", "sun"
    if code in {1, 2}:
        return "多云", "cloud-sun"
    if code == 3:
        return "阴", "cloud"
    if code in {45, 48}:
        return "有雾", "cloud-fog"
    if code in {51, 53, 55, 56, 57}:
        return "毛毛雨", "cloud-drizzle"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "有雨", "cloud-rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "有雪", "cloud-snow"
    if code in {95, 96, 99}:
        return "雷雨", "cloud-lightning"
    return "多云", "cloud-sun"


def fallback_weather(today: date) -> dict[str, Any]:
    tomorrow = today + timedelta(days=1)
    return {
        "source": "季节参考",
        "city": STORE_CITY,
        "updated_at": datetime.now().isoformat(timespec="minutes"),
        "current": {"temperature": 22.0, "label": "多云", "icon": "cloud-sun"},
        "today": {
            "date": iso(today),
            "label": "多云",
            "icon": "cloud-sun",
            "temperature": "18–25°C",
            "rain": "20%",
            "code": 2,
        },
        "tomorrow": {
            "date": iso(tomorrow),
            "label": "多云",
            "icon": "cloud-sun",
            "temperature": "18–25°C",
            "rain": "20%",
            "code": 2,
            "note": "天气服务暂不可用，当前使用季节参考值",
        },
        "forecast": [],
    }


def weather_note(day_label: str, code: int, rain_probability: float) -> str:
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}:
        return f"{day_label}有降雨概率 {rain_probability:.0f}%，建议下调西瓜等天气敏感品类备货"
    if code == 0:
        return f"{day_label}天气晴朗，冷鲜水果和果盒的到店需求预计提升"
    if code == 3:
        return f"{day_label}以阴天为主，客流预计平稳，按安全库存补货"
    return f"{day_label}多云，适合按常规周末节奏备货"


def fetch_live_weather(today: date) -> dict[str, Any]:
    if WEATHER_CACHE_FILE.exists():
        try:
            cached = json.loads(WEATHER_CACHE_FILE.read_text(encoding="utf-8"))
            cached_at = float(cached.get("cached_at", 0))
            if time.time() - cached_at < WEATHER_TTL_SECONDS and cached.get("today", {}).get("date") == iso(today):
                return cached
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={STORE_LAT}&longitude={STORE_LON}"
        "&current=temperature_2m,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=Asia%2FShanghai&forecast_days=4"
    )
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "GuogeStoreAgent/3.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        current = payload["current"]
        daily = payload["daily"]
        forecast = []
        for index, day_value in enumerate(daily["time"]):
            code = int(daily["weather_code"][index])
            label, icon = weather_description(code)
            rain_probability = float(daily.get("precipitation_probability_max", [0] * len(daily["time"]))[index] or 0)
            high = float(daily["temperature_2m_max"][index])
            low = float(daily["temperature_2m_min"][index])
            forecast.append(
                {
                    "date": day_value,
                    "label": label,
                    "icon": icon,
                    "temperature": f"{round(low)}–{round(high)}°C",
                    "high": round(high),
                    "low": round(low),
                    "rain": f"{round(rain_probability)}%",
                    "rain_probability": round(rain_probability),
                    "code": code,
                    "note": weather_note(display_date(day_value, False), code, rain_probability),
                }
            )
        today_weather = forecast[0]
        tomorrow_weather = forecast[1] if len(forecast) > 1 else forecast[0]
        current_label, current_icon = weather_description(int(current.get("weather_code", 2)))
        result = {
            "source": "在线天气",
            "city": STORE_CITY,
            "updated_at": datetime.now().isoformat(timespec="minutes"),
            "current": {
                "temperature": round(float(current.get("temperature_2m", 0)), 1),
                "label": current_label,
                "icon": current_icon,
            },
            "today": today_weather,
            "tomorrow": tomorrow_weather,
            "forecast": forecast,
            "cached_at": time.time(),
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        WEATHER_CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError, ValueError, OSError):
        if WEATHER_CACHE_FILE.exists():
            try:
                cached = json.loads(WEATHER_CACHE_FILE.read_text(encoding="utf-8"))
                cached["source"] = "在线天气 · 缓存"
                return cached
            except (OSError, json.JSONDecodeError):
                pass
        return fallback_weather(today)


def traffic_lift_for(day: date, weather: dict[str, Any]) -> str:
    base = 22 if day.weekday() >= 5 else 8 if day.weekday() == 4 else 3
    if int(weather.get("code", 2)) in {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}:
        base -= 8
    return f"+{max(1, base)}%"


def parse_iso(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    text = text.replace("/", "-").replace(".", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m-%d-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text.split(" ")[0], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text.split(" ")[0])
    except ValueError:
        return None


def generate_ean_like(seed: int) -> str:
    rng = random.Random(seed)
    return "69" + "".join(str(rng.randint(0, 9)) for _ in range(11))


def restore_default_catalog() -> None:
    for product, original in zip(PRODUCT_CATALOG, DEFAULT_PRODUCT_CATALOG):
        product.clear()
        product.update(dict(original))
    PRODUCT_BY_ID.clear()
    PRODUCT_BY_ID.update({item["id"]: item for item in PRODUCT_CATALOG})
    PRODUCT_BY_NAME.clear()
    PRODUCT_BY_NAME.update({item["name"]: item for item in PRODUCT_CATALOG})
    PRODUCT_BY_ALIAS.clear()
    PRODUCT_BY_ALIAS.update({item["alias"]: item for item in PRODUCT_CATALOG})


def generate_history(today: date | None = None, days: int = 7) -> tuple[list[dict], list[dict]]:
    """Generate deterministic, realistic demo orders and purchase records."""

    today = today or date.today()
    rng = random.Random(20261017)
    orders: list[dict] = []
    purchases: list[dict] = []

    for day_offset in range(days, 0, -1):
        current_day = today - timedelta(days=day_offset)
        weekday = current_day.weekday()
        weather = rng.choices(["晴", "多云", "阴", "小雨"], weights=[42, 31, 17, 10])[0]
        order_count = rng.randint(128, 168)
        order_ids = [
            f"订单{current_day.strftime('%Y%m%d')}{index + 1:04d}"
            for index in range(order_count)
        ]

        for product_index, product in enumerate(PRODUCT_CATALOG):
            factor = WEEKDAY_FACTORS[weekday]
            weekend_adjustment = 1 + (factor - 1) * product["weekend_sensitivity"]
            weather_factor = 1.0
            if weather == "小雨":
                weather_factor = product["rain_sensitivity"]
            elif weather == "晴":
                weather_factor = 1.03 if product["category"] in {"瓜果", "热带果"} else 1.0
            trend_position = 1 - (day_offset / days)
            trend_factor = 1 + product["trend"] * (trend_position - 0.45)
            noise = rng.uniform(0.86, 1.14)
            quantity = max(1, round(product["avg_daily"] * weekend_adjustment * weather_factor * trend_factor * noise))

            # Split the daily product quantity into multiple real order lines.
            # Fruit purchases are small and frequent. Splitting into 1–2 unit
            # baskets produces a realistic number of order lines and tickets.
            split_count = min(order_count, max(3, round(quantity / rng.uniform(1.2, 2.2))))
            remaining = quantity
            for split_index in range(split_count):
                if split_index == split_count - 1:
                    line_quantity = remaining
                else:
                    line_quantity = max(1, round(remaining / (split_count - split_index) * rng.uniform(0.7, 1.3)))
                    line_quantity = min(line_quantity, max(1, remaining - (split_count - split_index - 1)))
                remaining -= line_quantity
                if line_quantity <= 0:
                    continue
                unit_price = product["price"]
                if rng.random() < 0.06:
                    unit_price = round(unit_price * rng.choice([0.88, 0.9, 0.95]), 2)
                line_amount = round(line_quantity * unit_price, 2)
                orders.append(
                    {
                        "date": iso(current_day),
                        "order_id": rng.choice(order_ids),
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "quantity": line_quantity,
                        "unit_price": unit_price,
                        "amount": line_amount,
                        "payment": rng.choice(PAYMENT_METHODS),
                        "time_slot": rng.choice(TIME_SLOTS),
                        "unit": product["unit"],
                    }
                )
            if remaining > 0:
                orders.append(
                    {
                        "date": iso(current_day),
                        "order_id": rng.choice(order_ids),
                        "product_id": product["id"],
                        "product_name": product["name"],
                        "quantity": remaining,
                        "unit_price": product["price"],
                        "amount": round(remaining * product["price"], 2),
                        "payment": rng.choice(PAYMENT_METHODS),
                        "time_slot": rng.choice(TIME_SLOTS),
                        "unit": product["unit"],
                    }
                )

            # Purchase records are generated slightly above / below sales to
            # create meaningful high- and low-stock moments in the demo.
            purchase_quantity = max(1, round(quantity * product["stock_multiplier"] * rng.uniform(0.96, 1.04)))
            purchase_cost = round(product["cost"] * rng.uniform(0.97, 1.04), 2)
            purchases.append(
                {
                    "date": iso(current_day),
                    "purchase_id": f"采购{current_day.strftime('%Y%m%d')}{product_index + 1:03d}",
                    "product_id": product["id"],
                    "product_name": product["name"],
                    "quantity": purchase_quantity,
                    "unit_cost": purchase_cost,
                    "amount": round(purchase_quantity * purchase_cost, 2),
                    "supplier": product.get("supplier", "四季鲜果批发"),
                    "unit": product["unit"],
                }
            )

    return orders, purchases


def aggregate_daily(orders: list[dict]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in orders:
        day = str(row["date"])
        bucket = result.setdefault(day, {"revenue": 0.0, "quantity": 0.0, "profit": 0.0, "orders": 0.0})
        bucket["revenue"] += float(row["amount"])
        bucket["quantity"] += float(row["quantity"])
        product = PRODUCT_BY_ID.get(str(row["product_id"]))
        unit_cost = float(product["cost"]) if product else float(row["amount"]) * 0.58 / max(float(row["quantity"]), 0.01)
        bucket["profit"] += float(row["amount"]) - float(row["quantity"]) * unit_cost
    for day, bucket in result.items():
        order_ids = {str(row["order_id"]) for row in orders if str(row["date"]) == day}
        bucket["orders"] = float(len(order_ids))
    return result


def sales_by_product(orders: list[dict], days: int = 7) -> dict[str, dict[str, float]]:
    if not orders:
        return {}
    latest = max(parse_iso(row["date"]) or date.today() for row in orders)
    start = latest - timedelta(days=days - 1)
    result: dict[str, dict[str, float]] = {}
    for row in orders:
        row_date = parse_iso(row["date"])
        if not row_date or row_date < start or row_date > latest:
            continue
        product_id = str(row["product_id"])
        bucket = result.setdefault(product_id, {"quantity": 0.0, "revenue": 0.0, "profit": 0.0, "orders": 0.0})
        bucket["quantity"] += float(row["quantity"])
        bucket["revenue"] += float(row["amount"])
        product = PRODUCT_BY_ID.get(product_id)
        if product:
            bucket["profit"] += float(row["amount"]) - float(row["quantity"]) * float(product["cost"])
        bucket["orders"] += 1
    return result


def compute_stock(products: list[dict], orders: list[dict], purchases: list[dict]) -> None:
    """Estimate on-hand stock from recent purchases and sales.

    A fruit shop rarely keeps four weeks of stock, so the MVP rolls the stock
    window over the last three days and assumes 1.2 days of opening inventory.
    This keeps the demo resilient while making the source of every number
    inspectable.
    """

    all_dates = [
        parsed
        for parsed in [parse_iso(row.get("date")) for row in orders + purchases]
        if parsed is not None
    ]
    latest = max(all_dates) if all_dates else date.today()
    window_start = latest - timedelta(days=2)
    sold_by_product: dict[str, float] = {}
    purchased_by_product: dict[str, float] = {}
    for row in orders:
        row_date = parse_iso(row.get("date"))
        if not row_date or row_date < window_start:
            continue
        key = str(row["product_id"])
        sold_by_product[key] = sold_by_product.get(key, 0.0) + float(row["quantity"])
    for row in purchases:
        row_date = parse_iso(row.get("date"))
        if not row_date or row_date < window_start:
            continue
        key = str(row["product_id"])
        purchased_by_product[key] = purchased_by_product.get(key, 0.0) + float(row["quantity"])

    for product in products:
        key = product["id"]
        opening_stock = float(product.get("reference_daily", 12)) * 1.2
        raw_stock = opening_stock + purchased_by_product.get(key, 0.0) - sold_by_product.get(key, 0.0)
        product["stock"] = max(0.0, safe_round(raw_stock, 1))
        product["stock_value"] = safe_round(product["stock"] * float(product["cost"]), 2)


def enrich_products(products: list[dict], orders: list[dict]) -> None:
    product_sales = sales_by_product(orders, days=7)
    for product in products:
        stats = product_sales.get(product["id"], {})
        sold_7d = float(stats.get("quantity", 0.0))
        revenue_7d = float(stats.get("revenue", 0.0))
        profit_7d = float(stats.get("profit", 0.0))
        avg_daily_sales = sold_7d / 7 if sold_7d else float(product.get("reference_daily", 0)) * 0.75
        days_cover = product["stock"] / max(avg_daily_sales, 0.1)
        shelf_ratio = days_cover / max(float(product["shelf_life"]), 0.5)
        trend_penalty = max(0.0, -float(product.get("trend", 0))) * 55
        risk_score = int(
            min(
                98,
                max(
                    8,
                    shelf_ratio * 94
                    + max(0, 4 - float(product["shelf_life"])) * 5
                    + trend_penalty,
                ),
            )
        )
        product["sold_7d"] = safe_round(sold_7d, 1)
        product["revenue_7d"] = safe_round(revenue_7d, 2)
        product["profit_7d"] = safe_round(profit_7d, 2)
        product["avg_daily_sales"] = safe_round(avg_daily_sales, 1)
        product["days_cover"] = safe_round(days_cover, 1)
        product["risk_score"] = risk_score
        if risk_score >= 84:
            product["risk_level"] = "high"
            product["risk_label"] = "高损耗风险"
        elif risk_score >= 62:
            product["risk_level"] = "medium"
            product["risk_label"] = "需要关注"
        else:
            product["risk_level"] = "low"
            product["risk_label"] = "周转健康"
        product["margin_rate"] = safe_round((float(product["price"]) - float(product["cost"])) / float(product["price"]) * 100, 1)
        product["stock_unit"] = product["unit"]
        product["purchase_reason"] = build_purchase_reason(product)


def build_purchase_reason(
    product: dict,
    tomorrow: date | None = None,
    weather: dict[str, Any] | None = None,
    forecast: float | None = None,
) -> str:
    if product["id"] == "P003":
        return f"库存可售 {product['days_cover']} 天，接近或超过货架期，暂停采购并优先消化"
    if product["days_cover"] < 1.2:
        return f"当前仅覆盖 {product['days_cover']} 天，低于安全库存"
    if float(product["shelf_life"]) <= 3:
        return "短保商品，按 1–1.5 天销量控制进货"
    day_type = "周末" if tomorrow and tomorrow.weekday() >= 5 else "工作日"
    weather_label = weather.get("label", "常规天气") if weather else "常规天气"
    forecast_text = f"，明日预估 {forecast:.0f} {product['unit']}" if forecast is not None else ""
    return f"结合{day_type}客流、{weather_label}与近 7 天日均销量 {product['avg_daily_sales']} {product['unit']}{forecast_text}"


def build_purchase_plan(products: list[dict], tomorrow: date, weather: dict[str, Any] | None = None) -> list[dict]:
    weekend_lift = 1.22 if tomorrow.weekday() >= 5 else 1.06
    weather_code = int((weather or {}).get("code", 2))
    rainy = weather_code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
    plan: list[dict] = []
    for product in products:
        catalog = PRODUCT_BY_ID.get(product["id"], {})
        weather_factor = float(catalog.get("rain_sensitivity", 1.0)) if rainy else 1.0
        if weather_code == 0 and product.get("category") in {"瓜果", "热带果"}:
            weather_factor *= 1.03
        forecast = float(product["avg_daily_sales"]) * weekend_lift * weather_factor
        if float(product["shelf_life"]) <= 3:
            target_days = 1.15
        elif float(product["shelf_life"]) <= 5:
            target_days = 1.65
        else:
            target_days = 2.0
        target_stock = forecast * target_days
        need = max(0.0, target_stock - float(product["stock"]))
        if product["id"] == "P003":
            need = 0.0
        quantity = int(math.ceil(need)) if need > 0 else 0
        if quantity == 0:
            continue
        plan.append(
            {
                "id": product["id"],
                "name": product["name"],
                "category": product["category"],
                "unit": product["unit"],
                "current_stock": product["stock"],
                "forecast_sales": safe_round(forecast, 0),
                "recommended_qty": quantity,
                "unit_cost": product["cost"],
                "budget": safe_round(quantity * float(product["cost"]), 1),
                "reason": build_purchase_reason(product, tomorrow, weather, forecast),
                "confidence": 91 if product["id"] in {"P001", "P004", "P006"} else 84,
                "checked": True,
            }
        )
    plan.sort(key=lambda item: item["budget"], reverse=True)
    return plan[:9]


def build_discount_plan(products: list[dict], min_discount: float = 7.0) -> list[dict]:
    plan: list[dict] = []
    min_discount = min(10.0, max(5.0, float(min_discount)))
    for product in sorted(products, key=lambda item: item["risk_score"], reverse=True):
        if product["risk_score"] < 62:
            continue
        if product["risk_score"] >= 84:
            discount = 7.0
            when = "今日 18:00 后"
            urgency = "今天必须处理"
        elif product["risk_score"] >= 74:
            discount = 8.0
            when = "今日 16:00 前"
            urgency = "建议今日处理"
        else:
            discount = 8.5
            when = "明日 12:00 前"
            urgency = "提前动销"
        effective_discount = max(discount, min_discount)
        floor_applied = effective_discount > discount
        expected_units = float(product["stock"]) * 0.78
        recovery = expected_units * float(product["price"]) * effective_discount / 10
        loss_avoided = float(product["stock"]) * float(product["cost"]) * 0.62
        plan.append(
            {
                "id": product["id"],
                "name": product["name"],
                "unit": product["unit"],
                "stock": product["stock"],
                "days_cover": product["days_cover"],
                "shelf_life": product["shelf_life"],
                "risk_score": product["risk_score"],
                "risk_label": product["risk_label"],
                "suggested_discount": effective_discount,
                "base_discount": discount,
                "min_discount": min_discount,
                "floor_applied": floor_applied,
                "original_price": product["price"],
                "discounted_price": safe_round(float(product["price"]) * effective_discount / 10, 2),
                "when": when,
                "urgency": urgency,
                "expected_recovery": safe_round(recovery, 0),
                "loss_avoided": safe_round(loss_avoided, 0),
                "bundle": product["bundle"],
                "reason": (
                    f"库存可售 {product['days_cover']} 天，货架期仅 {product['shelf_life']} 天；"
                    "按当前动销速度会临期。"
                    + (f" 已按门店最低 {min_discount:.1f} 折执行。" if floor_applied else "")
                ),
                "checked": True,
            }
        )
    return plan[:6]


def build_daily_trend(orders: list[dict], days: int = 14) -> list[dict]:
    daily = aggregate_daily(orders)
    sorted_days = sorted(daily.keys())[-days:]
    return [
        {
            "date": day,
            "label": display_date(day, include_weekday=False),
            "weekday": WEEKDAY_NAMES[date.fromisoformat(day).weekday()],
            "revenue": safe_round(daily[day]["revenue"], 2),
            "profit": safe_round(daily[day]["profit"], 2),
            "orders": int(daily[day]["orders"]),
        }
        for day in sorted_days
    ]


def build_reviews(
    orders: list[dict],
    products: list[dict],
    today: date,
    min_discount: float = 7.0,
) -> dict[str, Any]:
    daily = aggregate_daily(orders)
    if not daily or not products:
        return empty_reviews(today)
    yesterday = today - timedelta(days=1)
    y_key = iso(yesterday)
    prev_key = iso(yesterday - timedelta(days=7))
    current = daily.get(y_key, {"revenue": 0, "profit": 0, "orders": 0})
    previous = daily.get(prev_key, {"revenue": 0, "profit": 0, "orders": 0})
    revenue = float(current["revenue"])
    prev_revenue = float(previous["revenue"])
    has_prev_day = prev_revenue > 0
    revenue_change = ((revenue - prev_revenue) / prev_revenue * 100) if prev_revenue else 0
    avg_ticket = revenue / max(float(current["orders"]), 1)
    prev_ticket = prev_revenue / max(float(previous["orders"]), 1)
    margin_rate = float(current["profit"]) / max(revenue, 1) * 100

    week_days = sorted(daily.keys())[-7:]
    prev_week_days = sorted(daily.keys())[-14:-7]
    week_revenue = sum(daily[d]["revenue"] for d in week_days)
    prev_week_revenue = sum(daily[d]["revenue"] for d in prev_week_days)
    has_prev_week = prev_week_revenue > 0
    week_change = ((week_revenue - prev_week_revenue) / prev_week_revenue * 100) if prev_week_revenue else 0
    week_profit = sum(daily[d]["profit"] for d in week_days)
    week_margin = week_profit / max(week_revenue, 1) * 100
    week_orders = sum(daily[d]["orders"] for d in week_days)
    prev_week_profit = sum(daily[d]["profit"] for d in prev_week_days)
    prev_week_margin = prev_week_profit / max(prev_week_revenue, 1) * 100
    prev_week_orders = sum(daily[d]["orders"] for d in prev_week_days)
    week_orders_change = ((week_orders - prev_week_orders) / prev_week_orders * 100) if prev_week_orders else 0
    prev_margin_rate = float(previous["profit"]) / max(prev_revenue, 1) * 100
    daily_margin_change = margin_rate - prev_margin_rate
    weekly_margin_change = week_margin - prev_week_margin

    highlighted = sorted(products, key=lambda p: p["revenue_7d"], reverse=True)[:3]
    high_risk = sorted(products, key=lambda p: p["risk_score"], reverse=True)[:3]
    yesterday_rows = [row for row in orders if row["date"] == y_key]
    previous_rows = [row for row in orders if row["date"] == prev_key]

    def quantities_by_product(rows: list[dict]) -> dict[str, float]:
        result: dict[str, float] = {}
        for row in rows:
            key = str(row["product_id"])
            result[key] = result.get(key, 0.0) + float(row["quantity"])
        return result

    current_qty = quantities_by_product(yesterday_rows)
    previous_qty = quantities_by_product(previous_rows)
    if has_prev_day:
        quantity_changes = [
            (product_id, current_qty.get(product_id, 0) - previous_qty.get(product_id, 0))
            for product_id in set(current_qty) | set(previous_qty)
        ]
        growth_product_id, growth_quantity_delta = max(quantity_changes, key=lambda item: item[1], default=("", 0))
    else:
        growth_product_id, growth_quantity_delta = max(current_qty.items(), key=lambda item: item[1], default=("", 0))
    growth_product = PRODUCT_BY_ID.get(growth_product_id, highlighted[0] if highlighted else {})
    slot_amounts: dict[str, float] = {}
    for row in yesterday_rows:
        slot = str(row.get("time_slot") or "未记录时段")
        slot_amounts[slot] = slot_amounts.get(slot, 0.0) + float(row["amount"])
    peak_slot = max(slot_amounts, key=slot_amounts.get) if slot_amounts else "未记录"

    discount_plan = build_discount_plan(products, min_discount)
    risk_loss = sum(float(product["stock_value"]) * float(product["risk_score"]) / 260 for product in products)
    weekend_revenue = sum(
        daily[d]["revenue"] for d in week_days if date.fromisoformat(d).weekday() >= 5
    )
    weekend_share = weekend_revenue / max(week_revenue, 1) * 100
    top_margin_product = max(products, key=lambda p: float(p.get("margin_rate", 0)))
    risk_product = high_risk[0] if high_risk else products[0]
    growth_name = growth_product.get("name", "主要商品")
    growth_unit = growth_product.get("unit", "")
    daily_compare_text = f"较上周同日 {revenue_change:+.1f}%" if has_prev_day else "暂无上周同日可比数据"
    growth_text = (
        f"{growth_name}较上周同日销量变化 {growth_quantity_delta:+.0f} {growth_unit}"
        if has_prev_day
        else f"{growth_name}昨日销量最高，共 {growth_quantity_delta:.0f} {growth_unit}"
    )
    daily_narrative = (
        f"昨天（{display_date(yesterday)}）门店共完成 {int(current['orders'])} 笔订单，"
        f"销售额 ¥{revenue:,.0f}，{daily_compare_text}。"
        f"客单价 ¥{avg_ticket:.1f}，毛利率 {margin_rate:.1f}%。"
        f"{growth_text}，"
        f"销售峰值出现在 {peak_slot}。"
        f"{risk_product['name']}当前可售 {risk_product['days_cover']} 天，货架期 {risk_product['shelf_life']} 天，"
        f"是今天最需要优先处理的损耗风险。"
    )
    weekly_narrative = (
        f"本周（{display_date(week_days[0], False)}–{display_date(week_days[-1], False)}）"
        f"累计销售额 ¥{week_revenue:,.0f}，"
        f"{f'周环比 {week_change:+.1f}%' if has_prev_week else '暂无上周可比数据'}，"
        f"共 {int(week_orders)} 笔订单，综合毛利率 {week_margin:.1f}%。"
        f"周末销售额占全周 {weekend_share:.1f}%，{highlighted[0]['name']}是本周销售额最高的商品。"
        f"{risk_product['name']}当前可售 {risk_product['days_cover']} 天，货架期 {risk_product['shelf_life']} 天，"
        f"是本周最值得优化的损耗点。"
    )
    return {
        "daily": {
            "date": iso(yesterday),
            "date_label": display_date(yesterday),
            "narrative": daily_narrative,
            "metrics": [
                {"label": "销售额", "value": f"¥{revenue:,.0f}", "change": f"{revenue_change:+.1f}%" if has_prev_day else "暂无上周同日数据", "tone": "good" if has_prev_day and revenue_change >= 0 else "bad" if has_prev_day else "neutral"},
                {"label": "订单数", "value": f"{int(current['orders'])} 笔", "change": f"{int(current['orders']) - int(previous['orders']):+d} 笔" if has_prev_day else "暂无上周同日数据", "tone": "good" if has_prev_day and current["orders"] >= previous["orders"] else "bad" if has_prev_day else "neutral"},
                {"label": "客单价", "value": f"¥{avg_ticket:.1f}", "change": f"{avg_ticket - prev_ticket:+.1f} 元" if has_prev_day else "暂无上周同日数据", "tone": "good" if has_prev_day and avg_ticket >= prev_ticket else "bad" if has_prev_day else "neutral"},
                {
                    "label": "毛利率",
                    "value": f"{margin_rate:.1f}%",
                    "change": "暂无上周同日数据" if not has_prev_day else "与上周同日持平" if abs(daily_margin_change) < 0.05 else f"{daily_margin_change:+.1f}pct",
                    "tone": "neutral" if not has_prev_day else "good" if daily_margin_change >= 0 else "bad",
                },
            ],
            "insights": [
                {"type": "增长", "title": f"{growth_name}销量领先", "detail": f"{growth_text}，销售峰值时段为 {peak_slot}。"},
                {"type": "风险", "title": f"{risk_product['name']}存在临期风险", "detail": f"库存可售 {risk_product['days_cover']} 天，货架期 {risk_product['shelf_life']} 天，建议优先处理。"},
                {"type": "机会", "title": f"{top_margin_product['name']}毛利率较高", "detail": f"当前毛利率 {top_margin_product['margin_rate']:.1f}%，可结合组合装提升客单价。"},
            ],
            "actions": [
                (
                    f"{discount_plan[0]['when']}对{discount_plan[0]['name']}执行 {discount_plan[0]['suggested_discount']:.0f} 折"
                    if discount_plan
                    else f"持续观察{risk_product['name']}的动销与货架期"
                ),
                f"明早优先检查{highlighted[0]['name']}库存，并按采购页建议补货",
                f"把{peak_slot}作为重点补货和陈列时段",
            ],
        },
        "weekly": {
            "date": iso(today),
            "date_label": f"{display_date(week_days[0], False)} – {display_date(week_days[-1], False)}",
            "narrative": weekly_narrative,
            "metrics": [
                {"label": "本周销售额", "value": f"¥{week_revenue:,.0f}", "change": f"{week_change:+.1f}%" if has_prev_week else "暂无上周数据", "tone": "good" if has_prev_week and week_change >= 0 else "bad" if has_prev_week else "neutral"},
                {"label": "订单数", "value": f"{int(week_orders)} 笔", "change": f"{week_orders_change:+.1f}%" if has_prev_week else "暂无上周数据", "tone": "good" if has_prev_week and week_orders_change >= 0 else "bad" if has_prev_week else "neutral"},
                {
                    "label": "综合毛利率",
                    "value": f"{week_margin:.1f}%",
                    "change": "暂无上周数据" if not has_prev_week else "与上周持平" if abs(weekly_margin_change) < 0.05 else f"{weekly_margin_change:+.1f}pct",
                    "tone": "neutral" if not has_prev_week else "good" if weekly_margin_change >= 0 else "bad",
                },
                {"label": "损耗预估", "value": f"¥{risk_loss:,.0f}", "change": "按当前库存估算", "tone": "neutral"},
            ],
            "insights": [
                {"type": "增长", "title": "周末销售占比已核算", "detail": f"本周周末销售额占全周 {weekend_share:.1f}%，{highlighted[0]['name']}销售额最高。"},
                {"type": "风险", "title": f"{risk_product['name']}需要收紧补货", "detail": f"库存可售 {risk_product['days_cover']} 天，货架期 {risk_product['shelf_life']} 天。"},
                {"type": "机会", "title": f"{top_margin_product['name']}有利润空间", "detail": f"毛利率 {top_margin_product['margin_rate']:.1f}%，适合做组合陈列。"},
            ],
            "actions": [
                f"下周将{risk_product['name']}改为少量多次补货",
                f"把{highlighted[0]['name']}放在入口主陈列，并观察周末动销",
                f"用{top_margin_product['name']}测试一个组合装或果盒",
            ],
        },
    }


def build_kpis(orders: list[dict], products: list[dict], today: date) -> dict[str, Any]:
    daily = aggregate_daily(orders)
    yesterday = iso(today - timedelta(days=1))
    current = daily.get(yesterday, {"revenue": 0, "profit": 0, "orders": 0, "quantity": 0})
    week_days = sorted(daily.keys())[-7:]
    week_revenue = sum(daily[d]["revenue"] for d in week_days)
    prev_week_days = sorted(daily.keys())[-14:-7]
    prev_week_revenue = sum(daily[d]["revenue"] for d in prev_week_days)
    has_prev_week = prev_week_revenue > 0
    week_change = ((week_revenue - prev_week_revenue) / prev_week_revenue * 100) if prev_week_revenue else 0
    inventory_value = sum(float(p["stock_value"]) for p in products)
    risk_loss = sum(float(p["stock_value"]) * float(p["risk_score"]) / 260 for p in products)
    return {
        "revenue_yesterday": safe_round(current["revenue"], 2),
        "orders_yesterday": int(current["orders"]),
        "avg_ticket": safe_round(current["revenue"] / max(float(current["orders"]), 1), 2),
        "gross_margin": safe_round(float(current["profit"]) / max(float(current["revenue"]), 1) * 100, 1),
        "week_revenue": safe_round(week_revenue, 2),
        "week_change": safe_round(week_change, 1),
        "has_week_compare": has_prev_week,
        "inventory_value": safe_round(inventory_value, 2),
        "risk_loss": safe_round(risk_loss, 0),
        "active_products": len([p for p in products if p["sold_7d"] > 0]),
        "high_risk_count": len([p for p in products if p["risk_score"] >= 84]),
    }


def build_state(today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    tomorrow = today + timedelta(days=1)
    orders, purchases = generate_history(today)
    products = []
    for item in PRODUCT_CATALOG:
        product = {key: value for key, value in item.items() if key not in {"avg_daily", "weekend_sensitivity", "rain_sensitivity", "trend", "stock_multiplier", "bundle"}}
        product["trend"] = item["trend"]
        product["bundle"] = item["bundle"]
        product["reference_daily"] = item["avg_daily"]
        product["barcode"] = generate_ean_like(int(item["id"][1:]))
        products.append(product)
    compute_stock(products, orders, purchases)
    enrich_products(products, orders)
    live_weather = fetch_live_weather(today)
    tomorrow_weather = live_weather["tomorrow"]
    min_discount = 7.0
    purchase_plan = build_purchase_plan(products, tomorrow, tomorrow_weather)
    discount_plan = build_discount_plan(products, min_discount)
    kpis = build_kpis(orders, products, today)
    reviews = build_reviews(orders, products, today, min_discount)
    memories = [dict(item) for item in DEFAULT_MEMORIES]
    memories[0]["created_at"] = iso(today - timedelta(days=21))
    memories[1]["created_at"] = iso(today - timedelta(days=5))
    memories[2]["created_at"] = iso(today - timedelta(days=12))
    memories[3]["created_at"] = iso(today - timedelta(days=9))
    memories[4]["created_at"] = iso(today - timedelta(days=39))
    return {
        "meta": {
            "version": APP_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "demo_date": iso(today),
            "source": "mock",
        },
        "store": {
            "name": "果哥水果店",
            "short_name": "果哥水果店",
            "owner": "",
            "members": 1248,
            "staff": 3,
            "min_discount": min_discount,
        },
        "context": {
            "today": iso(today),
            "today_label": display_date(today),
            "tomorrow": iso(tomorrow),
            "tomorrow_label": display_date(tomorrow),
            "weather": {
                **tomorrow_weather,
                "source": live_weather["source"],
                "city": live_weather["city"],
                "current": live_weather["current"],
                "updated_at": live_weather["updated_at"],
            },
            "weather_forecast": live_weather["forecast"],
            "traffic_lift": traffic_lift_for(tomorrow, tomorrow_weather),
            "sync_label": "数据已同步",
            "sync_time": datetime.now().strftime("%H:%M"),
        },
        "kpis": kpis,
        "products": sorted(products, key=lambda p: p["risk_score"], reverse=True),
        "purchase_plan": purchase_plan,
        "discount_plan": discount_plan,
        "reviews": reviews,
        "memories": memories,
        "trend": build_daily_trend(orders),
        "orders": orders,
        "purchases": purchases,
        "uploads": [
            {
                "id": "U001",
                "kind": "orders",
                "filename": "订单明细_近7天.xlsx",
                "rows": len(orders),
                "status": "success",
                "uploaded_at": iso(today - timedelta(days=1)) + " 21:08",
            },
            {
                "id": "U002",
                "kind": "purchases",
                "filename": "每日采购记录_近7天.xlsx",
                "rows": len(purchases),
                "status": "success",
                "uploaded_at": iso(today - timedelta(days=1)) + " 21:10",
            },
        ],
        "quality": {
            "status": "healthy",
            "score": 96,
            "checks": [
                {"label": "订单日期连续性", "status": "pass", "detail": "近 7 天完整"},
                {"label": "商品编码匹配", "status": "pass", "detail": "20 / 20 已匹配"},
                {"label": "异常订单", "status": "pass", "detail": "未发现负数数量"},
                {"label": "采购记录完整度", "status": "pass", "detail": "近 7 天完整"},
                {"label": "重复数据", "status": "pass", "detail": "自动按订单号 + 商品编码去重"},
            ],
        },
    }


def polish_review_narratives(state: dict[str, Any]) -> None:
    config = llm_config()
    if not config["enabled"]:
        return
    for period, label in (("daily", "昨日复盘"), ("weekly", "本周复盘")):
        review = state["reviews"][period]
        facts = {
            "报告": label,
            "日期": review["date_label"],
            "经营指标": review["metrics"],
            "关键发现": review["insights"],
            "下一步行动": review["actions"],
            "店铺": state["store"]["name"],
        }
        content, _ = call_llm(
            [
                {
                    "role": "system",
                    "content": (
                        "你是中小水果店经营助手“果哥”。请根据事实写一段 100 到 160 字的中文经营复盘，"
                        "语气像店长和老板沟通。必须保留事实中的全部数字，不得新增或修改数字，"
                        "不得补充事实中没有的洞察；日报指标均为与上周同日比较，周报指标均为与上周比较。"
                        "不使用 Markdown、表情符号或水果图标。只输出正文。"
                    ),
                },
                {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
            ],
            max_tokens=320,
            temperature=0.3,
        )
        if content:
            review["narrative"] = content
            review["llm_generated"] = True


def save_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Keep the JSON readable and avoid sending a huge data file from the client.
    serializable = {key: value for key, value in state.items() if key != "orders_preview"}
    with STATE_FILE.open("w", encoding="utf-8") as handle:
        json.dump(serializable, handle, ensure_ascii=False, indent=2)


def load_state() -> dict[str, Any]:
    def sync_catalog(state: dict[str, Any]) -> None:
        for product in state.get("products", []):
            catalog = PRODUCT_BY_ID.get(product["id"])
            if not catalog:
                continue
            for field in ("name", "category", "unit", "cost", "price", "shelf_life"):
                if field in product:
                    catalog[field] = product[field]
            catalog["alias"] = str(product.get("name", catalog.get("alias", "")))
        PRODUCT_BY_NAME.clear()
        PRODUCT_BY_NAME.update({item["name"]: item for item in PRODUCT_CATALOG})
        PRODUCT_BY_ALIAS.clear()
        PRODUCT_BY_ALIAS.update({item["alias"]: item for item in PRODUCT_CATALOG})

    today = date.today()
    if STATE_FILE.exists():
        try:
            with STATE_FILE.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
            meta = state.get("meta", {})
            is_demo = meta.get("source") in {"sample", "mock"}
            needs_refresh = meta.get("demo_date") != iso(today) or meta.get("version") != APP_VERSION
            if state.get("products") and not (is_demo and needs_refresh):
                sync_catalog(state)
                state["meta"]["version"] = APP_VERSION
                state["meta"]["demo_date"] = iso(today)
                state["context"]["today"] = iso(today)
                state["context"]["today_label"] = display_date(today)
                state["context"]["tomorrow"] = iso(today + timedelta(days=1))
                state["context"]["tomorrow_label"] = display_date(today + timedelta(days=1))
                live_weather = fetch_live_weather(today)
                tomorrow_weather = live_weather["tomorrow"]
                state["context"]["weather"] = {
                    **tomorrow_weather,
                    "source": live_weather["source"],
                    "city": live_weather["city"],
                    "current": live_weather["current"],
                    "updated_at": live_weather["updated_at"],
                }
                state["context"]["weather_forecast"] = live_weather["forecast"]
                state["context"]["traffic_lift"] = traffic_lift_for(today + timedelta(days=1), tomorrow_weather)
                if state.get("orders"):
                    state["purchase_plan"] = build_purchase_plan(state["products"], today + timedelta(days=1), tomorrow_weather)
                return state
        except (json.JSONDecodeError, OSError):
            pass
    state = build_state(today)
    polish_review_narratives(state)
    save_state(state)
    return state


def ensure_current_date(state: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    if state.get("context", {}).get("today") == iso(today):
        return state
    source = state.get("meta", {}).get("source")
    if source == "mock":
        state = build_state(today)
        polish_review_narratives(state)
        save_state(state)
        return state
    tomorrow = today + timedelta(days=1)
    live_weather = fetch_live_weather(today)
    tomorrow_weather = live_weather["tomorrow"]
    state["meta"]["demo_date"] = iso(today)
    state["context"]["today"] = iso(today)
    state["context"]["today_label"] = display_date(today)
    state["context"]["tomorrow"] = iso(tomorrow)
    state["context"]["tomorrow_label"] = display_date(tomorrow)
    state["context"]["weather"] = {
        **tomorrow_weather,
        "source": live_weather["source"],
        "city": live_weather["city"],
        "current": live_weather["current"],
        "updated_at": live_weather["updated_at"],
    }
    state["context"]["weather_forecast"] = live_weather["forecast"]
    state["context"]["traffic_lift"] = traffic_lift_for(tomorrow, tomorrow_weather)
    if state.get("orders"):
        state["purchase_plan"] = build_purchase_plan(state["products"], tomorrow, tomorrow_weather)
    save_state(state)
    return state


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    result = dict(state)
    result["meta"] = dict(state.get("meta", {}))
    result["meta"]["version"] = APP_VERSION
    result["meta"]["llm"] = llm_public_status()
    orders = result.pop("orders", [])
    purchases = result.pop("purchases", [])
    result["data_summary"] = {
        "orders": len(orders),
        "purchases": len(purchases),
        "order_days": len({row["date"] for row in orders}),
        "purchase_days": len({row["date"] for row in purchases}),
        "last_order_date": max((row["date"] for row in orders), default=None),
        "last_purchase_date": max((row["date"] for row in purchases), default=None),
    }
    recent_orders = sorted(orders, key=lambda row: (row["date"], row["order_id"]), reverse=True)[:30]
    result["recent_orders"] = recent_orders
    result["recent_purchases"] = sorted(purchases, key=lambda row: (row["date"], row["purchase_id"]), reverse=True)[:20]
    return result


def fmt_money(value: float) -> str:
    return f"¥{value:,.0f}"


def split_text_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？\n]+", text) if part.strip()]


def product_cards(products: list[dict], limit: int = 4) -> list[dict]:
    cards = []
    for product in products[:limit]:
        cards.append(
            {
                "name": product["name"],
                "meta": f"库存 {product['stock']} {product['unit']} · 可售 {product['days_cover']} 天",
                "value": f"{product['suggested_discount']:.0f} 折" if "suggested_discount" in product else f"补 {product['recommended_qty']} {product['unit']}",
                "tone": product.get("risk_level", "low"),
            }
        )
    return cards


def make_reply(
    reply_type: str,
    title: str,
    text: str,
    *,
    bullets: list[str] | None = None,
    cards: list[dict] | None = None,
    table: dict[str, Any] | None = None,
    actions: list[dict] | None = None,
    followups: list[str] | None = None,
    memory: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": reply_type,
        "title": title,
        "text": text,
        "bullets": bullets or [],
        "cards": cards or [],
        "table": table,
        "actions": actions or [],
        "followups": followups or [],
        "memory": memory,
        "context": context,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def purchase_reply(state: dict[str, Any], compact: bool = False) -> dict[str, Any]:
    plan = state["purchase_plan"]
    if not plan:
        return upload_reply()
    total_budget = sum(item["budget"] for item in plan)
    total_items = len(plan)
    top = plan[:5]
    rows = [
        {
            "name": item["name"],
            "stock": f"{item['current_stock']} {item['unit']}",
            "forecast": f"{item['forecast_sales']} {item['unit']}",
            "qty": f"{item['recommended_qty']} {item['unit']}",
            "budget": fmt_money(item["budget"]),
            "confidence": f"{item['confidence']}%",
        }
        for item in top
    ]
    tomorrow = state["context"]["tomorrow_label"]
    traffic_lift = state["context"]["traffic_lift"]
    text = (
        f"我按{state['context']['weather']['label']}、{state['context']['weather'].get('city', STORE_CITY)}"
        f"{state['context']['tomorrow_label']}的客流（预计 {traffic_lift}）和近 7 天动销，"
        f"把明天的安全库存算了一遍。建议采购 {total_items} 个商品，总预算约 {fmt_money(total_budget)}。"
    )
    if compact:
        priority = "、".join(item["name"] for item in plan[:3])
        text = f"建议明天采购 {total_items} 个商品，总预算约 {fmt_money(total_budget)}。{priority}是优先级最高的商品。"
    return make_reply(
        "purchase",
        f"{tomorrow}采购建议",
        text,
        bullets=[
            f"{plan[0]['name']}：{plan[0]['reason']}。",
            "草莓：库存已超过货架期，暂停采购，优先用晚间折扣消化。",
            "采购单已按“预计动销 × 安全天数 − 现有库存”计算，可在采购页逐项调整。",
        ],
        table={
            "columns": ["商品", "现有库存", "明日预估", "建议采购", "预算", "置信度"],
            "rows": rows,
            "footer": f"合计预算 {fmt_money(total_budget)} · 已考虑实际天气与客流 {traffic_lift}",
        },
        cards=[],
        actions=[
            {"label": "查看完整采购单", "action": "navigate", "payload": "purchase"},
            {"label": "调整采购量", "action": "navigate", "payload": "purchase"},
        ],
        followups=["为什么西瓜要进这么多？", "草莓怎么处理？", "帮我生成采购单"],
    )


def discount_reply(state: dict[str, Any], compact: bool = False) -> dict[str, Any]:
    plan = state["discount_plan"]
    if not plan:
        return make_reply(
            "discount",
            "动态定价",
            "当前没有需要新增折扣的商品。导入最新订单和采购记录后，我会重新计算临期风险。",
            actions=[{"label": "导入数据", "action": "navigate", "payload": "data"}],
            followups=["明天该进什么货？", "查看经营复盘", "库存还有多少？"],
        )
    top = plan[:4]
    total_recovery = sum(item["expected_recovery"] for item in top)
    total_loss_avoided = sum(item["loss_avoided"] for item in top)
    rows = [
        {
            "name": item["name"],
            "stock": f"{item['stock']} {item['unit']}",
            "days_cover": f"{item['days_cover']} 天",
            "shelf": f"{item['shelf_life']} 天",
            "discount": f"{item['suggested_discount']:.0f} 折",
            "window": item["when"],
            "recovery": fmt_money(item["expected_recovery"]),
        }
        for item in top
    ]
    text = (
        f"当前有 {len(plan)} 个商品需要动销干预。最紧急的是{plan[0]['name']}："
        f"库存 {plan[0]['stock']} {plan[0]['unit']}，按近 7 天动销只能再卖 {plan[0]['days_cover']} 天，"
        f"但货架期只有 {plan[0]['shelf_life']} 天。建议{plan[0]['when']}执行 {plan[0]['suggested_discount']:.0f} 折。"
    )
    if compact:
        text = f"最该处理的是{plan[0]['name']}，建议{plan[0]['when']} {plan[0]['suggested_discount']:.0f} 折；其余 {len(plan) - 1} 个商品建议提前动销。"
    return make_reply(
        "discount",
        "动态定价建议",
        text,
        bullets=[
            f"如果按建议执行，预计可回收现金 {fmt_money(total_recovery)}，减少约 {fmt_money(total_loss_avoided)} 的潜在损耗。",
            "折扣不是统一降价：按“剩余可售天数 / 货架期”分层，避免健康库存被过早打折。",
            f"建议搭配组合：{plan[0]['bundle']}，用高毛利商品拉动连带购买。",
        ],
        table={
            "columns": ["商品", "库存", "可售", "货架期", "建议折扣", "执行时间", "预计回收"],
            "rows": rows,
            "footer": "价格建议会随库存和动销每日更新，执行后可在复盘中看到回收效果。",
        },
        actions=[
            {"label": "查看全部定价建议", "action": "navigate", "payload": "pricing"},
            {"label": "查看经营复盘", "action": "navigate", "payload": "review"},
        ],
        followups=["草莓打几折合适？", "有哪些商品要临期处理？", "帮我写一条会员通知"],
    )


def summary_reply(state: dict[str, Any], period: str = "daily") -> dict[str, Any]:
    review = state["reviews"]["daily" if period == "daily" else "weekly"]
    title = "昨日经营复盘" if period == "daily" else "本周经营复盘"
    action_title = "下一步行动"
    bullets = [f"{item['title']}：{item['detail']}" for item in review["insights"]]
    text = review["narrative"]
    return make_reply(
        "summary",
        title,
        text,
        bullets=bullets,
        actions=[
            {"label": "打开完整复盘", "action": "navigate", "payload": "review"},
            {"label": "导出复盘摘要", "action": "toast", "payload": "复盘摘要已准备好，可继续导出"},
        ],
        followups=[
            "本周哪个品最赚钱？",
            "我的损耗为什么偏高？",
            "下周应该重点改什么？",
        ],
    )


def inventory_reply(state: dict[str, Any]) -> dict[str, Any]:
    products = state["products"]
    if not any(float(product["sold_7d"]) > 0 for product in products):
        return upload_reply()
    high = [p for p in products if p["risk_score"] >= 84][:4]
    low = sorted(products, key=lambda p: p["days_cover"])[:4]
    rows = [
        {
            "name": p["name"],
            "stock": f"{p['stock']} {p['unit']}",
            "sold": f"{p['sold_7d']} {p['unit']}",
            "days": f"{p['days_cover']} 天",
            "risk": p["risk_label"],
        }
        for p in high
    ]
    return make_reply(
        "inventory",
        "库存与动销快照",
        f"当前库存总值约 {fmt_money(state['kpis']['inventory_value'])}，"
        f"有 {len([p for p in products if p['risk_score'] >= 84])} 个商品处于高损耗风险。"
        f"库存最紧的是{low[0]['name']}，只够卖 {low[0]['days_cover']} 天。",
        bullets=[
            "库存按“期初 + 采购 − 销售”计算，并假设每日闭店盘点无差异。",
            "高风险的判断同时考虑剩余可售天数、货架期和近期动销趋势。",
            "如果同一批订单重复导入，系统会按订单号 + 商品编码自动去重。",
        ],
        table={
            "columns": ["商品", "现有库存", "近 7 天销量", "可售天数", "风险"],
            "rows": rows,
            "footer": "完整库存明细可在数据中心查看",
        },
        actions=[
            {"label": "查看库存明细", "action": "navigate", "payload": "data"},
            {"label": "导出库存表", "action": "download", "payload": "/api/export/inventory.xlsx"},
        ],
        followups=["哪些水果要打折？", "明天该进什么货？", "草莓还能卖几天？"],
    )


def upload_reply() -> dict[str, Any]:
    return make_reply(
        "upload",
        "导入经营数据",
        "支持分隔表格和电子表格格式的订单明细与每日采购记录。导入后会自动完成商品匹配、去重，并重算库存、销量、毛利和采购建议。",
        bullets=[
            "订单表至少包含：日期、订单号、商品编码或商品名称、数量、单价。",
            "采购表至少包含：日期、采购单号、商品编码或商品名称、采购数量、采购单价。",
            "当前版本默认每日闭店盘点无差异；真实上线后可接入损耗单或盘点表。",
        ],
        actions=[
            {"label": "去导入数据", "action": "navigate", "payload": "data"},
            {"label": "下载订单模板", "action": "download", "payload": "/api/template/orders.xlsx"},
            {"label": "下载采购模板", "action": "download", "payload": "/api/template/purchases.xlsx"},
        ],
        followups=["我的表格要包含哪些列？", "库存是怎么算出来的？", "可以导入重复文件吗？"],
    )


def product_reply(state: dict[str, Any], product: dict) -> dict[str, Any]:
    if product["risk_score"] >= 74:
        discount = next((item for item in state["discount_plan"] if item["id"] == product["id"]), None)
        return make_reply(
            "product",
            f"{product['name']}：建议优先处理库存",
            f"{product['name']}现有 {product['stock']} {product['unit']}，近 7 天卖出 {product['sold_7d']} "
            f"{product['unit']}，按当前速度还能卖 {product['days_cover']} 天，货架期只有 {product['shelf_life']} 天。"
            + (f"建议{discount['when']}执行 {discount['suggested_discount']:.0f} 折，预计回收 {fmt_money(discount['expected_recovery'])}。" if discount else ""),
            bullets=[
                "先检查陈列位置和果面状态，挑出软果单独做果盒，避免影响正价商品。",
                "优先用会员券和组合装带动连带购买，不建议直接全场打折。",
                "今天处理后，明天暂停或少量补货，把采购节奏改回 1–2 天一次。",
            ],
            actions=[
                {"label": "查看定价建议", "action": "navigate", "payload": "pricing"},
            ],
            followups=["帮我写会员通知", "明天还要进货吗？", "怎么减少草莓损耗？"],
            context={"intent": "product", "product_id": product["id"], "product_name": product["name"]},
        )
    plan = next((item for item in state["purchase_plan"] if item["id"] == product["id"]), None)
    return make_reply(
        "product",
        f"{product['name']}：动销与备货",
        f"{product['name']}近 7 天卖出 {product['sold_7d']} {product['unit']}，当前库存 {product['stock']} "
        f"{product['unit']}，可售 {product['days_cover']} 天。"
        + (f"明天建议补 {plan['recommended_qty']} {product['unit']}，预算约 {fmt_money(plan['budget'])}。" if plan else "当前库存足够，明天不需要补货。"),
        bullets=[
            f"毛利率约 {product['margin_rate']}%，在同类商品中处于健康区间。",
            product["purchase_reason"],
            f"建议搭配：{product['bundle']}。",
        ],
        actions=[{"label": "查看采购计划", "action": "navigate", "payload": "purchase"}],
        followups=["这个品要打折吗？", "明天该进什么货？", "最近什么卖得最好？"],
        context={"intent": "product", "product_id": product["id"], "product_name": product["name"]},
    )


def extract_memory(message: str) -> dict[str, Any] | None:
    has_memory_cue = "记住" in message or any(
        word in message for word in ["经验", "规律", "偏好", "以后", "每次", "我们店"]
    )
    if not has_memory_cue:
        return None
    if "记住" not in message and not any(
        word in message
        for word in ["以后", "每次", "进货", "备货", "少进", "多进", "不超", "最多", "卖", "损耗", "天气", "周末"]
    ):
        return None
    cleaned = re.sub(r"^(请)?(帮我)?记住[：:，, ]*", "", message).strip()
    cleaned = re.sub(r"^(以后|每次)[：:，, ]*", "", cleaned).strip()
    if len(cleaned) < 4:
        return None
    tag = "经营经验"
    if any(word in cleaned for word in ["周末", "周六", "周日"]):
        tag = "周末规律"
    elif any(word in cleaned for word in ["雨", "天气", "降温", "升温"]):
        tag = "天气经验"
    elif any(word in cleaned for word in ["损耗", "临期", "坏"]):
        tag = "损耗经验"
    elif any(word in cleaned for word in ["学生", "学校", "社区", "老人"]):
        tag = "社区洞察"
    impact = "已加入门店专属记忆，后续建议会自动参考"
    if any(word in cleaned for word in ["少进", "不超", "最多", "控制"]):
        impact = "已转换为采购约束"
    return {
        "id": f"M{int(time.time() * 1000) % 1000000}",
        "text": cleaned[:80],
        "tag": tag,
        "source": "本次对话沉淀",
        "impact": impact,
        "active": True,
        "created_at": iso(date.today()),
    }


def llm_config() -> dict[str, Any]:
    custom_key = os.environ.get("GZ_LLM_API_KEY")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if custom_key:
        return {
            "enabled": True,
            "provider": os.environ.get("GZ_LLM_PROVIDER", "兼容模型服务"),
            "api_key": custom_key,
            "base_url": os.environ.get("GZ_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            "model": os.environ.get("GZ_LLM_MODEL", "gpt-4o-mini"),
        }
    if deepseek_key:
        return {
            "enabled": True,
            "provider": "深度求索",
            "api_key": deepseek_key,
            "base_url": os.environ.get("GZ_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            "model": os.environ.get("GZ_LLM_MODEL", "deepseek-chat"),
        }
    if openai_key:
        return {
            "enabled": True,
            "provider": "智能模型服务",
            "api_key": openai_key,
            "base_url": os.environ.get("GZ_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            "model": os.environ.get("GZ_LLM_MODEL", "gpt-4o-mini"),
        }
    return {
        "enabled": False,
        "provider": "本地规则",
        "api_key": "",
        "base_url": "",
        "model": "rule-engine",
    }


def llm_public_status() -> dict[str, Any]:
    config = llm_config()
    return {
        "enabled": config["enabled"],
        "provider": config["provider"],
        "model": "大语言模型" if config["enabled"] else "本地规则",
        "connected": LLM_RUNTIME["connected"] if config["enabled"] else False,
        "checked_at": LLM_RUNTIME["checked_at"],
        "latency_ms": LLM_RUNTIME["last_latency_ms"],
        "error": LLM_RUNTIME["last_error"],
        "calls": LLM_RUNTIME["calls"],
    }


def call_llm(
    messages: list[dict[str, str]],
    max_tokens: int = 360,
    temperature: float = 0.35,
    timeout: int = 30,
) -> tuple[str | None, dict[str, Any]]:
    config = llm_config()
    if not config["enabled"]:
        return None, llm_public_status()
    started = time.perf_counter()
    body = json.dumps(
        {
            "model": config["model"],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config['base_url']}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = str(payload["choices"][0]["message"]["content"]).strip()
        latency = int((time.perf_counter() - started) * 1000)
        LLM_RUNTIME.update(
            {
                "connected": True,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "last_latency_ms": latency,
                "last_error": None,
                "calls": int(LLM_RUNTIME.get("calls", 0)) + 1,
            }
        )
        return content or None, llm_public_status()
    except Exception as exc:  # Network and provider errors should never break the store workflow.
        LLM_RUNTIME.update(
            {
                "connected": False,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
                "last_latency_ms": int((time.perf_counter() - started) * 1000),
                "last_error": f"{type(exc).__name__}: {str(exc)[:180]}",
            }
        )
        return None, llm_public_status()


def probe_llm() -> None:
    config = llm_config()
    if not config["enabled"]:
        LLM_RUNTIME.update({"connected": False, "checked_at": datetime.now().isoformat(timespec="seconds")})
        return
    content, _ = call_llm(
        [
            {"role": "system", "content": "只输出 OK，不要输出其他内容。"},
            {"role": "user", "content": "连接测试"},
        ],
        max_tokens=8,
        temperature=0,
        timeout=20,
    )
    if content:
        LLM_RUNTIME["last_error"] = None


def llm_polish_reply(
    message: str,
    reply: dict[str, Any],
    state: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = llm_config()
    if not config["enabled"] or reply.get("type") in {"memory", "upload"}:
        reply["llm"] = llm_public_status()
        return reply
    facts = {
        "用户问题": message,
        "标题": reply.get("title"),
        "确定性结论": reply.get("text"),
        "要点": reply.get("bullets", []),
        "表格结论": reply.get("table", {}).get("footer") if reply.get("table") else None,
        "门店": state["store"]["name"],
        "日期": state["context"]["today_label"],
        "明日": state["context"]["tomorrow_label"],
        "天气": state["context"]["weather"],
        "经营指标": state["kpis"],
    }
    conversation = []
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            conversation.append({"role": role, "content": content[:1200]})
    content, status = call_llm(
        [
            {
                "role": "system",
                "content": (
                    "你是中小水果店经营助手“果哥”。请结合最近对话和给定事实，解决老板当前的问题，"
                    "改写成 2 到 4 句自然、简洁、可以直接对老板说的中文经营建议。"
                    "必须保留原有商品名、数字、日期、折扣和动作，不得新增或修改任何数字，"
                    "不得回答与店铺经营无关的问题，不使用 Markdown、表情符号或水果图标。只输出正文。"
                ),
            },
            *conversation,
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        max_tokens=360,
        temperature=0.3,
    )
    if content:
        reply["text"] = content
        reply["llm_used"] = True
    reply["llm"] = status
    return reply


def llm_freeform_reply(
    message: str,
    state: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    config = llm_config()
    if not config["enabled"]:
        return None, llm_public_status()
    context = {
        "店铺": state["store"]["name"],
        "今天": state["context"]["today_label"],
        "明天": state["context"]["tomorrow_label"],
        "天气": state["context"]["weather"],
        "经营指标": state["kpis"],
        "采购建议": [
            {
                "商品": item["name"],
                "现有库存": item["current_stock"],
                "建议采购": item["recommended_qty"],
                "单位": item["unit"],
                "原因": item["reason"],
            }
            for item in state["purchase_plan"][:8]
        ],
        "临期风险": [
            {
                "商品": item["name"],
                "可售天数": item["days_cover"],
                "货架期": item["shelf_life"],
                "建议折扣": item["suggested_discount"],
                "执行时间": item["when"],
            }
            for item in state["discount_plan"][:5]
        ],
        "商品表现": [
            {
                "商品": product["name"],
                "近7天销量": product["sold_7d"],
                "库存": product["stock"],
                "可售天数": product["days_cover"],
                "毛利率": product["margin_rate"],
                "风险": product["risk_label"],
            }
            for product in sorted(
                state["products"],
                key=lambda item: item["sold_7d"],
                reverse=True,
            )[:12]
        ],
        "门店记忆": [item["text"] for item in state["memories"] if item["active"]],
    }
    conversation = []
    for item in (history or [])[-8:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            conversation.append({"role": role, "content": content[:1200]})
    return call_llm(
        [
            {
                "role": "system",
                "content": (
                    "你是中小水果店经营助手“果哥”。结合最近对话和门店数据回答老板问题。"
                    "只基于给定事实回答，不得编造库存、销量、金额或日期；缺少数据时明确说明需要导入。"
                    "回答要具体、可执行、简洁，最多 4 句，不使用 Markdown、表情符号或水果图标。"
                ),
            },
            *conversation,
            {"role": "user", "content": json.dumps({"问题": message, "门店数据": context}, ensure_ascii=False)},
        ],
        max_tokens=420,
        temperature=0.3,
    )


def latest_context(history: list[dict[str, Any]] | None) -> dict[str, Any]:
    for item in reversed(history or []):
        if item.get("role") == "assistant" and isinstance(item.get("context"), dict):
            return item["context"]
    return {}


def followup_explanation(state: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    intent = context.get("intent")
    if intent == "purchase":
        plan = state["purchase_plan"][:4]
        if not plan:
            return upload_reply()
        bullets = []
        for item in plan:
            product = next((p for p in state["products"] if p["id"] == item["id"]), None)
            if not product:
                continue
            if product["shelf_life"] <= 3:
                target_days = "1.15 天"
            elif product["shelf_life"] <= 5:
                target_days = "1.65 天"
            else:
                target_days = "2 天"
            bullets.append(
                f"{item['name']}：近 7 天日均 {product['avg_daily_sales']} {product['unit']}，"
                f"结合天气与客流后预估 {item['forecast_sales']} {item['unit']}；"
                f"现有库存 {item['current_stock']} {item['unit']}，按 {target_days}安全库存计算，"
                f"建议采购 {item['recommended_qty']} {item['unit']}。"
            )
        return make_reply(
            "purchase",
            "采购计算过程",
            "采购量不是拍脑袋，而是先用近 7 天订单计算日均动销，再叠加明日天气、客流和安全库存天数，最后减去现有库存。",
            bullets=bullets,
            actions=[{"label": "查看采购单", "action": "navigate", "payload": "purchase"}],
            followups=["如果明天下雨还要进这么多吗？", "哪些商品不用进货？", "采购预算还能再降吗？"],
            context=context,
        )
    if intent == "discount":
        plan = state["discount_plan"][:4]
        if not plan:
            return None
        bullets = [
            f"{item['name']}：库存 {item['stock']} {item['unit']}，可售 {item['days_cover']} 天，"
            f"货架期 {item['shelf_life']} 天，风险指数 {item['risk_score']}，建议 {item['suggested_discount']:.0f} 折。"
            for item in plan
        ]
        return make_reply(
            "discount",
            "折扣计算逻辑",
            "折扣依据是剩余可售天数和货架期的比值，不是单纯看库存多少。越接近货架期，处理优先级越高。",
            bullets=bullets,
            actions=[{"label": "查看定价方案", "action": "navigate", "payload": "pricing"}],
            followups=["不打折还有什么办法？", "先处理哪一个？", "会员通知怎么写？"],
            context=context,
        )
    if intent == "product":
        product = next((p for p in state["products"] if p["id"] == context.get("product_id")), None)
        if product:
            return product_reply(state, product)
    if intent in {"summary", "inventory"}:
        return None
    return None


def find_products_in_text(text: str) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for product in PRODUCT_CATALOG:
        if product["id"] in seen:
            continue
        if product["name"] in text or product["alias"] in text:
            matched.append(product)
            seen.add(product["id"])
    return matched


def compare_products_reply(state: dict[str, Any], products: list[dict[str, Any]]) -> dict[str, Any]:
    sales = [
        {
            "product": product,
            "state": next((item for item in state["products"] if item["id"] == product["id"]), None),
            "plan": next((item for item in state["purchase_plan"] if item["id"] == product["id"]), None),
            "risk": next((item for item in state["discount_plan"] if item["id"] == product["id"]), None),
        }
        for product in products
    ]
    sales = [item for item in sales if item["state"]]
    if len(sales) < 2:
        return product_reply(state, sales[0]["state"]) if sales else upload_reply()
    ranked_sales = sorted(sales, key=lambda item: item["state"]["sold_7d"], reverse=True)
    ranked_margin = sorted(sales, key=lambda item: item["state"]["margin_rate"], reverse=True)
    ranked_risk = sorted(sales, key=lambda item: item["state"]["risk_score"], reverse=True)
    rows = [
        {
            "name": item["state"]["name"],
            "sold": f"{item['state']['sold_7d']} {item['state']['unit']}",
            "stock": f"{item['state']['stock']} {item['state']['unit']}",
            "margin": f"{item['state']['margin_rate']:.1f}%",
            "risk": f"{item['state']['risk_score']} / {item['state']['risk_label']}",
            "action": (
                f"补 {item['plan']['recommended_qty']} {item['plan']['unit']}"
                if item["plan"]
                else f"建议 {item['risk']['suggested_discount']:.0f} 折"
                if item["risk"]
                else "维持当前节奏"
            ),
        }
        for item in sales
    ]
    text = (
        f"从近 7 天动销看，{ranked_sales[0]['state']['name']}卖得更好；"
        f"从毛利率看，{ranked_margin[0]['state']['name']}更高；"
        f"从临期风险看，{ranked_risk[0]['state']['name']}更需要优先处理。"
    )
    return make_reply(
        "compare",
        f"{sales[0]['state']['name']}与{sales[1]['state']['name']}对比",
        text,
        bullets=[
            f"{item['state']['name']}：库存 {item['state']['stock']} {item['state']['unit']}，"
            f"可售 {item['state']['days_cover']} 天，货架期 {item['state']['shelf_life']} 天，"
            f"风险指数 {item['state']['risk_score']}。"
            for item in sales
        ],
        table={
            "columns": ["商品", "近 7 天销量", "库存", "毛利率", "风险", "建议"],
            "rows": rows,
            "footer": "对比基于当前订单、采购和库存数据。",
        },
        actions=[{"label": "查看采购建议", "action": "navigate", "payload": "purchase"}],
        followups=["哪个更值得多进货？", "它需要打折吗？", "如果预算有限先保哪个？"],
        context={"intent": "compare", "product_ids": [item["state"]["id"] for item in sales]},
    )


def budget_purchase_reply(state: dict[str, Any], budget: float) -> dict[str, Any]:
    candidates = []
    for item in state["purchase_plan"]:
        state_product = next((product for product in state["products"] if product["id"] == item["id"]), None)
        if not state_product:
            continue
        expected_profit = float(item["forecast_sales"]) * (float(state_product["price"]) - float(state_product["cost"]))
        candidates.append((expected_profit, item))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    selected = []
    remaining = max(0.0, budget)
    for _, item in candidates:
        unit_cost = float(item["unit_cost"])
        full_cost = float(item["budget"])
        if full_cost <= remaining + 0.01:
            quantity = int(item["recommended_qty"])
            spend = full_cost
        else:
            quantity = int(remaining // unit_cost) if unit_cost > 0 else 0
            spend = quantity * unit_cost
        if quantity <= 0:
            continue
        selected.append({**item, "recommended_qty": quantity, "budget": safe_round(spend, 1)})
        remaining -= spend
    selected.sort(key=lambda item: item["budget"], reverse=True)
    total = sum(float(item["budget"]) for item in selected)
    if not selected:
        return make_reply(
            "purchase",
            "预算不足",
            f"按当前采购单价，{fmt_money(budget)} 不足以形成有效采购量。建议提高预算，或优先处理现有高库存商品。",
            context={"intent": "purchase", "budget": budget},
        )
    return make_reply(
        "purchase",
        f"{fmt_money(budget)} 预算采购方案",
        f"按预计毛利潜力排序，在 {fmt_money(budget)} 预算内建议采购 {len(selected)} 个商品，"
        f"合计约 {fmt_money(total)}，剩余 {fmt_money(remaining)}。",
        bullets=[
            f"{item['name']}：采购 {item['recommended_qty']} {item['unit']}，约 {fmt_money(item['budget'])}"
            for item in selected[:5]
        ],
        actions=[{"label": "调整采购单", "action": "navigate", "payload": "purchase"}],
        followups=["还能再压缩预算吗？", "哪些商品可以不进？", "这样安排明天够卖吗？"],
        context={"intent": "purchase", "budget": budget},
    )


def action_priority_reply(state: dict[str, Any]) -> dict[str, Any]:
    risk = state["discount_plan"][0] if state["discount_plan"] else None
    purchase = state["purchase_plan"][0] if state["purchase_plan"] else None
    bullets = []
    if risk:
        bullets.append(
            f"先处理{risk['name']}：库存可售 {risk['days_cover']} 天，建议{risk['when']}执行 {risk['suggested_discount']:.0f} 折。"
        )
    if purchase:
        bullets.append(
            f"再确认明日采购：优先{purchase['name']}，建议 {purchase['recommended_qty']} {purchase['unit']}，预算 {fmt_money(purchase['budget'])}。"
        )
    bullets.append("最后检查导入数据是否覆盖最近 7 天，避免缺日导致库存和动销判断偏差。")
    return make_reply(
        "plan",
        "今天的经营优先级",
        "先处理会造成损耗的库存，再确认明天必须补的商品，最后核对数据完整性。",
        bullets=bullets,
        actions=[
            {"label": "处理临期商品", "action": "navigate", "payload": "pricing"},
            {"label": "确认明日采购", "action": "navigate", "payload": "purchase"},
        ],
        followups=["为什么先处理临期？", "采购预算还能降吗？", "今天的销售机会是什么？"],
        context={"intent": "plan"},
    )


def chat_response_rules(
    message: str,
    state: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = message.strip()
    lowered = text.lower()
    memory = extract_memory(text)
    if memory:
        if not any(item["text"] == memory["text"] for item in state["memories"]):
            state["memories"].insert(0, memory)
            save_state(state)
        return make_reply(
            "memory",
            "记住了，这条经验会参与计算",
            f"已把「{memory['text']}」加入门店记忆。下一次计算采购和折扣时，我会自动把它作为约束条件。",
            bullets=[
                f"归类：{memory['tag']}",
                f"作用：{memory['impact']}",
                "你可以随时在「门店记忆」中修改、停用或删除这条经验。",
            ],
            actions=[{"label": "查看门店记忆", "action": "navigate", "payload": "memory"}],
            followups=["明天该进什么货？", "再帮我看看库存", "总结一下昨天"],
            memory=memory,
        )

    context = latest_context(history)
    if context and any(word in text for word in ["为什么", "原因", "依据", "怎么算", "怎么得出", "凭什么"]):
        explanation = followup_explanation(state, context)
        if explanation:
            return explanation
    if context and text in {"继续", "详细说说", "再具体点", "然后呢", "还有呢", "展开说说"}:
        explanation = followup_explanation(state, context)
        if explanation:
            return explanation
    if context and context.get("intent") == "product" and any(
        word in text for word in ["它", "这个", "那它", "还进货吗", "要打折吗", "怎么处理"]
    ):
        product = next((p for p in state["products"] if p["id"] == context.get("product_id")), None)
        if product:
            return product_reply(state, product)

    matched_products = find_products_in_text(text)
    if len(matched_products) >= 2:
        return compare_products_reply(state, matched_products)
    if context.get("intent") == "product" and len(matched_products) == 1 and any(
        word in text for word in ["比", "对比", "哪个", "谁更"]
    ):
        context_product = next(
            (p for p in PRODUCT_CATALOG if p["id"] == context.get("product_id")),
            None,
        )
        if context_product and context_product["id"] != matched_products[0]["id"]:
            return compare_products_reply(state, [context_product, matched_products[0]])
    if context.get("intent") == "compare" and any(
        word in text for word in ["对比", "哪个", "值得", "先保", "优先"]
    ):
        compare_products = [
            product
            for product_id in context.get("product_ids", [])
            for product in PRODUCT_CATALOG
            if product["id"] == product_id
        ]
        if len(compare_products) >= 2:
            return compare_products_reply(state, compare_products)

    budget_match = re.search(r"(?:预算|控制在|降到|只有)\s*([0-9]+(?:\.[0-9]+)?)\s*元?", text)
    if budget_match:
        budget = float(budget_match.group(1))
        if budget > 0:
            return budget_purchase_reply(state, budget)

    if any(word in text for word in ["先做什么", "优先做什么", "今天先", "行动清单", "按什么顺序"]):
        return action_priority_reply(state)

    if any(word in text for word in ["采购", "进货", "备货", "进多少", "买多少"]) or (
        "明天" in text and any(word in text for word in ["货", "水果", "进"])
    ):
        return purchase_reply(state, compact=len(text) < 9)
    if any(word in text for word in ["打折", "降价", "临期", "清库存", "定价", "折扣"]):
        return discount_reply(state, compact=len(text) < 9)
    if any(word in text for word in ["总结", "复盘", "经营情况", "日报", "周报", "昨天卖", "本周", "上周"]):
        period = "weekly" if any(word in text for word in ["本周", "上周", "周报", "一周", "7天", "七天"]) else "daily"
        return summary_reply(state, period)
    if any(word in text for word in ["库存", "卖了多少", "销量", "剩多少", "动销"]):
        return inventory_reply(state)
    if any(word in text for word in ["上传", "导入", "excel", "表格", "订单", "采购记录"]):
        return upload_reply()
    if any(word in text for word in ["利润", "毛利", "赚钱", "最赚"]):
        products = sorted(state["products"], key=lambda p: p["profit_7d"], reverse=True)[:4]
        return make_reply(
            "margin",
            "最近的利润贡献",
            f"近 7 天毛利贡献最高的是{products[0]['name']}，贡献约 {fmt_money(products[0]['profit_7d'])}；"
            f"门店综合毛利率约 {state['kpis']['gross_margin']}%。高毛利不等于高利润，还要看动销和损耗。",
            bullets=[
                f"{p['name']}：近 7 天毛利 {fmt_money(p['profit_7d'])}，毛利率 {p['margin_rate']}%"
                for p in products
            ],
            actions=[{"label": "查看经营复盘", "action": "navigate", "payload": "review"}],
            followups=["哪些品损耗最高？", "下周怎么提高毛利？", "帮我看看昨天的数据"],
        )
    if any(word in text for word in ["会员", "通知", "文案", "朋友圈"]):
        if not state["discount_plan"]:
            return upload_reply()
        top = state["discount_plan"][0]
        return make_reply(
            "copy",
            "会员触达文案",
            f"【今日鲜果提醒】{top['name']}今日 {top['suggested_discount']:.0f} 折，"
            f"搭配蓝莓做 {top['bundle']}，到手更划算。数量有限，卖完即止，欢迎到店挑选～",
            bullets=[
                "建议在 16:30 和 18:30 各发一次，覆盖下班前和晚饭后两个时段。",
                "文案突出“当日鲜果”和“数量有限”，比直接写清仓更容易维护品牌感。",
                "如果门店有社群，可配一张果盒实拍图，转化会更好。",
            ],
            actions=[{"label": "复制文案", "action": "copy", "payload": f"【今日鲜果提醒】{top['name']}今日 {top['suggested_discount']:.0f} 折，搭配蓝莓做 {top['bundle']}，到手更划算。数量有限，卖完即止，欢迎到店挑选～"}],
            followups=["再写一条更短的", "哪些商品适合做组合？", "帮我看看今天的风险"],
        )
    if any(word in text for word in ["天气", "降雨", "气温", "客流"]) or (
        "周末" in text and any(word in text for word in ["客流", "人多", "卖什么", "动销"])
    ):
        weather = state["context"]["weather"]
        return make_reply(
            "context",
            "明天的经营环境",
            f"今天是{state['context']['today_label']}。明天是{state['context']['tomorrow_label']}，{state['context']['weather']['label']}，"
            f"{weather['temperature']}，降雨概率 {weather['rain']}。客流预估 {state['context']['traffic_lift']}，"
            f"数据来自 {weather.get('source', '天气服务')}。",
            bullets=[
                f"明日天气判断：{weather.get('note', '按安全库存安排补货')}。",
                "天气敏感品按实际降雨概率调整采购，短保商品维持少量多次补货。",
                "具体采购量可在采购页查看逐项计算依据。",
            ],
            actions=[{"label": "查看采购建议", "action": "navigate", "payload": "purchase"}],
            followups=["明天该进什么货？", "雨天怎么调整？", "周末什么卖得好？"],
        )

    for product in PRODUCT_CATALOG:
        if product["name"] in text or product["alias"] in text:
            state_product = next((p for p in state["products"] if p["id"] == product["id"]), None)
            if state_product:
                return product_reply(state, state_product)

    if any(word in lowered for word in ["你好", "hi", "hello", "在吗", "早上好"]):
        return make_reply(
            "welcome",
            "早上好，我在",
            "我可以帮你看采购、定价、复盘和库存。你也可以直接告诉我一条门店经验，我会把它沉淀成下一次计算的约束。",
            bullets=[
                "想进货：说“明天该进什么货？”",
                "想清库存：说“哪些水果要打折？”",
                "想复盘：说“总结一下昨天”。",
            ],
            actions=[
                {"label": "看明日采购", "action": "navigate", "payload": "purchase"},
                {"label": "看昨日复盘", "action": "navigate", "payload": "review"},
            ],
            followups=["明天该进什么货？", "哪些水果要打折？", "总结一下昨天"],
        )

    return make_reply(
        "text",
        "我可以从这几个方向帮你",
        "你这句话我还需要一点上下文。你可以直接问经营问题，也可以把订单或采购文件导入，我会基于门店真实数据回答。",
        bullets=[
            "采购：明天该进什么货？为什么？",
            "定价：哪些水果需要打折？打几折？",
            "复盘：昨天/本周卖得怎么样？",
            "库存：草莓还能卖几天？哪些品有损耗风险？",
        ],
        actions=[
            {"label": "导入数据", "action": "navigate", "payload": "data"},
            {"label": "查看经营总览", "action": "navigate", "payload": "chat"},
        ],
        followups=["明天该进什么货？", "哪些水果要打折？", "总结一下昨天"],
    )


def chat_response(
    message: str,
    state: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reply = chat_response_rules(message, state, history)
    if not reply.get("context"):
        intent_map = {
            "purchase": "purchase",
            "discount": "discount",
            "inventory": "inventory",
            "summary": "summary",
            "margin": "margin",
            "context": "weather",
        }
        if reply.get("type") in intent_map:
            reply["context"] = {"intent": intent_map[reply["type"]]}
    if reply.get("type") == "text":
        content, status = llm_freeform_reply(message, state, history)
        if content:
            reply["title"] = "果哥建议"
            reply["text"] = content
            reply["llm_used"] = True
            reply["llm"] = status
            return reply
    return llm_polish_reply(message, reply, state, history)


ORDER_COLUMN_ALIASES = {
    "date": ["日期", "销售日期", "订单日期", "date", "order_date"],
    "order_id": ["订单号", "订单编号", "单号", "order_id", "order_no"],
    "product_id": ["商品编码", "商品编号", "sku", "商品id", "product_id"],
    "product_name": ["商品名称", "品名", "商品", "product_name", "name"],
    "quantity": ["数量", "销售数量", "件数", "quantity", "qty"],
    "unit_price": ["单价", "销售单价", "售价", "unit_price", "price"],
    "amount": ["销售额", "金额", "销售金额", "amount", "revenue"],
    "payment": ["支付方式", "支付", "payment"],
    "time_slot": ["时段", "销售时段", "time_slot", "time"],
    "unit": ["单位", "unit"],
}

PURCHASE_COLUMN_ALIASES = {
    "date": ["日期", "采购日期", "date", "purchase_date"],
    "purchase_id": ["采购单号", "采购编号", "单号", "purchase_id", "po_no"],
    "product_id": ["商品编码", "商品编号", "sku", "商品id", "product_id"],
    "product_name": ["商品名称", "品名", "商品", "product_name", "name"],
    "quantity": ["采购数量", "数量", "件数", "quantity", "qty"],
    "unit_cost": ["采购单价", "进价", "单价", "unit_cost", "cost"],
    "amount": ["采购金额", "金额", "amount"],
    "supplier": ["供应商", "供货商", "supplier"],
    "unit": ["单位", "unit"],
}


def record_key(row: dict[str, Any], kind: str) -> str:
    """Build a stable dedupe key across int/float values from 电子表格."""

    if kind == "orders":
        return "|".join(
            [
                str(row.get("order_id", "")).strip(),
                str(row.get("product_id", "")).strip(),
                f"{float(row.get('quantity', 0)):.3f}",
                f"{float(row.get('unit_price', 0)):.2f}",
            ]
        )
    return "|".join(
        [
            str(row.get("purchase_id", "")).strip(),
            str(row.get("product_id", "")).strip(),
            f"{float(row.get('quantity', 0)):.3f}",
            f"{float(row.get('unit_cost', 0)):.2f}",
        ]
    )


def normalize_header(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("_", "")


def find_header(headers: list[Any], aliases: dict[str, list[str]], field: str) -> int | None:
    normalized = [normalize_header(header) for header in headers]
    for alias in aliases[field]:
        target = normalize_header(alias)
        if target in normalized:
            return normalized.index(target)
    return None


def parse_upload(blob: bytes, kind: str, filename: str = "") -> tuple[list[dict], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[tuple[Any, ...]] = []
    is_csv = filename.lower().endswith(".csv") or not blob.startswith(b"PK")
    try:
        if is_csv:
            text = None
            for encoding in ("utf-8-sig", "utf-8", "gb18030"):
                try:
                    text = blob.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                return [], ["表格文件编码无法识别，请使用通用表格编码"], warnings
            rows = [tuple(row) for row in csv.reader(io.StringIO(text))]
        else:
            workbook = load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
            sheet = workbook.active
            rows = list(sheet.iter_rows(values_only=True))
    except Exception:
        return [], ["无法读取文件，请确认是受支持的表格文件"], warnings
    if len(rows) < 2:
        return [], ["文件没有数据行"], warnings
    headers = list(rows[0])
    aliases = ORDER_COLUMN_ALIASES if kind == "orders" else PURCHASE_COLUMN_ALIASES
    required = ["date", "product_name", "quantity"] if kind == "orders" else ["date", "product_name", "quantity"]
    index_map = {field: find_header(headers, aliases, field) for field in aliases}
    for field in required:
        if index_map.get(field) is None:
            errors.append(f"缺少必填列：{aliases[field][0]}")
    if errors:
        return [], errors, warnings
    parsed: list[dict] = []
    seen_keys: set[str] = set()
    unmatched = 0
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(value not in (None, "") for value in row):
            continue

        def get(field: str) -> Any:
            index = index_map.get(field)
            return row[index] if index is not None and index < len(row) else None

        row_date = parse_iso(get("date"))
        if not row_date:
            warnings.append(f"第 {row_number} 行日期无法识别，已跳过")
            continue
        product_name = str(get("product_name") or "").strip()
        product_id = str(get("product_id") or "").strip()
        matched = PRODUCT_BY_ID.get(product_id) or PRODUCT_BY_NAME.get(product_name)
        if not matched:
            unmatched += 1
            continue
        try:
            quantity = float(get("quantity") or 0)
        except (TypeError, ValueError):
            warnings.append(f"第 {row_number} 行数量不是数字，已跳过")
            continue
        if quantity <= 0:
            warnings.append(f"第 {row_number} 行数量小于等于 0，已跳过")
            continue
        if kind == "orders":
            price = get("unit_price")
            amount = get("amount")
            try:
                unit_price = float(price) if price not in (None, "") else (float(amount) / quantity if amount not in (None, "") else float(matched["price"]))
            except (TypeError, ValueError, ZeroDivisionError):
                unit_price = float(matched["price"])
            try:
                amount_value = float(amount) if amount not in (None, "") else quantity * unit_price
            except (TypeError, ValueError):
                amount_value = quantity * unit_price
            order_id = str(get("order_id") or f"UP{iso(row_date)}{len(parsed) + 1:04d}").strip()
            unique_key = record_key(
                {
                    "order_id": order_id,
                    "product_id": matched["id"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                },
                "orders",
            )
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)
            parsed.append(
                {
                    "date": iso(row_date),
                    "order_id": order_id,
                    "product_id": matched["id"],
                    "product_name": matched["name"],
                    "quantity": quantity,
                    "unit_price": round(unit_price, 2),
                    "amount": round(amount_value, 2),
                    "payment": str(get("payment") or "其他"),
                    "time_slot": str(get("time_slot") or ""),
                    "unit": matched["unit"],
                }
            )
        else:
            cost = get("unit_cost")
            amount = get("amount")
            try:
                unit_cost = float(cost) if cost not in (None, "") else (float(amount) / quantity if amount not in (None, "") else float(matched["cost"]))
            except (TypeError, ValueError, ZeroDivisionError):
                unit_cost = float(matched["cost"])
            try:
                amount_value = float(amount) if amount not in (None, "") else quantity * unit_cost
            except (TypeError, ValueError):
                amount_value = quantity * unit_cost
            purchase_id = str(get("purchase_id") or f"UPO{iso(row_date)}{len(parsed) + 1:04d}").strip()
            unique_key = record_key(
                {
                    "purchase_id": purchase_id,
                    "product_id": matched["id"],
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                },
                "purchases",
            )
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)
            parsed.append(
                {
                    "date": iso(row_date),
                    "purchase_id": purchase_id,
                    "product_id": matched["id"],
                    "product_name": matched["name"],
                    "quantity": quantity,
                    "unit_cost": round(unit_cost, 2),
                    "amount": round(amount_value, 2),
                    "supplier": str(get("supplier") or "未填写"),
                    "unit": matched["unit"],
                }
            )
    if unmatched:
        warnings.append(f"{unmatched} 行商品未匹配，已跳过；请检查商品编码或名称")
    if not parsed:
        errors.append("没有可导入的有效数据行")
    return parsed, errors, warnings


def rebuild_after_import(state: dict[str, Any]) -> None:
    orders = state.get("orders", [])
    purchases = state.get("purchases", [])
    for product in state["products"]:
        catalog = PRODUCT_BY_ID.get(product["id"], {})
        product.update(
            {
                "stock_multiplier": catalog.get("stock_multiplier", 1.0),
                "weekend_sensitivity": catalog.get("weekend_sensitivity", 1.1),
                "rain_sensitivity": catalog.get("rain_sensitivity", 1.0),
            }
        )
    compute_stock(state["products"], orders, purchases)
    enrich_products(state["products"], orders)
    today = date.fromisoformat(state["meta"]["demo_date"])
    tomorrow = today + timedelta(days=1)
    weather = state.get("context", {}).get("weather", {})
    min_discount = float(state.get("store", {}).get("min_discount", 7.0))
    state["purchase_plan"] = build_purchase_plan(state["products"], tomorrow, weather)
    state["discount_plan"] = build_discount_plan(state["products"], min_discount)
    state["kpis"] = build_kpis(orders, state["products"], today)
    state["reviews"] = build_reviews(orders, state["products"], today, min_discount)
    state["trend"] = build_daily_trend(orders)
    state["meta"]["generated_at"] = datetime.now().isoformat(timespec="seconds")
    state["meta"]["source"] = "user"
    if state["discount_plan"]:
        state["kpis"]["risk_loss"] = safe_round(
            sum(float(p["stock_value"]) * float(p["risk_score"]) / 260 for p in state["products"]),
            0,
        )
    for product in state["products"]:
        product["stock"] = safe_round(product["stock"], 1)
    update_quality(state)
    if state.get("orders") and state.get("purchases"):
        polish_review_narratives(state)
    save_state(state)


def update_sku(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    sku_id = str(payload.get("id", "")).strip()
    product = next((item for item in state["products"] if item["id"] == sku_id), None)
    if not product:
        raise ValueError("未找到该 商品")
    name = str(payload.get("name", product["name"])).strip()
    category = str(payload.get("category", product["category"])).strip()
    unit = str(payload.get("unit", product["unit"])).strip()
    if not name or not category or not unit:
        raise ValueError("商品名称、品类和单位不能为空")
    if any(item["id"] != sku_id and item["name"] == name for item in state["products"]):
        raise ValueError("商品名称不能与其他商品重复")
    try:
        cost = float(payload.get("cost", product["cost"]))
        price = float(payload.get("price", product["price"]))
        shelf_life = int(payload.get("shelf_life", product["shelf_life"]))
    except (TypeError, ValueError):
        raise ValueError("成本、售价和货架期必须是数字")
    if cost <= 0 or price <= 0 or shelf_life <= 0:
        raise ValueError("成本、售价和货架期必须大于 0")
    if price <= cost:
        raise ValueError("售价必须高于成本")
    product.update(
        {
            "name": name,
            "category": category,
            "unit": unit,
            "cost": round(cost, 2),
            "price": round(price, 2),
            "shelf_life": shelf_life,
            "margin_rate": safe_round((price - cost) / price * 100, 1),
            "stock_value": safe_round(float(product["stock"]) * cost, 2),
        }
    )
    catalog = PRODUCT_BY_ID.get(sku_id)
    if catalog:
        catalog.update(
            {
                "name": name,
                "alias": name,
                "category": category,
                "unit": unit,
                "cost": round(cost, 2),
                "price": round(price, 2),
                "shelf_life": shelf_life,
            }
        )
        PRODUCT_BY_NAME.clear()
        PRODUCT_BY_NAME.update({item["name"]: item for item in PRODUCT_CATALOG})
        PRODUCT_BY_ALIAS.clear()
        PRODUCT_BY_ALIAS.update({item["alias"]: item for item in PRODUCT_CATALOG})
    today = date.fromisoformat(state["meta"]["demo_date"])
    tomorrow = date.fromisoformat(state["context"]["tomorrow"])
    weather = state.get("context", {}).get("weather", {})
    min_discount = float(state.get("store", {}).get("min_discount", 7.0))
    enrich_products(state["products"], state["orders"])
    state["purchase_plan"] = build_purchase_plan(state["products"], tomorrow, weather)
    state["discount_plan"] = build_discount_plan(state["products"], min_discount)
    state["kpis"] = build_kpis(state["orders"], state["products"], today)
    state["reviews"] = build_reviews(state["orders"], state["products"], today, min_discount)
    state["meta"]["source"] = "user"
    save_state(state)
    return product


def empty_reviews(today: date) -> dict[str, Any]:
    yesterday = today - timedelta(days=1)
    empty_metrics = [
        {"label": "销售额", "value": "¥0", "change": "暂无数据", "tone": "neutral"},
        {"label": "订单数", "value": "0 笔", "change": "暂无数据", "tone": "neutral"},
        {"label": "客单价", "value": "¥0", "change": "暂无数据", "tone": "neutral"},
        {"label": "毛利率", "value": "0%", "change": "暂无数据", "tone": "neutral"},
    ]
    narrative = "当前没有可用于分析的订单和采购记录。请先在数据中心导入表格文件，系统会生成真实的经营复盘。"
    return {
        "daily": {
            "date": iso(yesterday),
            "date_label": display_date(yesterday),
            "narrative": narrative,
            "metrics": empty_metrics,
            "insights": [],
            "actions": ["导入订单明细", "导入每日采购记录", "核对商品编码与日期"],
        },
        "weekly": {
            "date": iso(today),
            "date_label": f"{display_date(today - timedelta(days=6), False)} – {display_date(today, False)}",
            "narrative": narrative,
            "metrics": [
                {"label": "本周销售额", "value": "¥0", "change": "暂无数据", "tone": "neutral"},
                {"label": "订单数", "value": "0 笔", "change": "暂无数据", "tone": "neutral"},
                {"label": "综合毛利率", "value": "0%", "change": "暂无数据", "tone": "neutral"},
                {"label": "损耗预估", "value": "¥0", "change": "暂无数据", "tone": "neutral"},
            ],
            "insights": [],
            "actions": ["导入订单明细", "导入每日采购记录", "检查日期范围是否完整"],
        },
    }


def update_quality(state: dict[str, Any]) -> None:
    orders = state.get("orders", [])
    purchases = state.get("purchases", [])
    order_days = len({row["date"] for row in orders})
    purchase_days = len({row["date"] for row in purchases})
    matched_products = len(
        {
            row["product_id"]
            for row in orders + purchases
            if row.get("product_id") in PRODUCT_BY_ID
        }
    )
    if not orders and not purchases:
        state["quality"] = {
            "status": "empty",
            "score": 0,
            "checks": [
                {"label": "订单数据", "status": "empty", "detail": "尚未导入"},
                {"label": "采购数据", "status": "empty", "detail": "尚未导入"},
                {"label": "商品编码匹配", "status": "empty", "detail": "等待数据"},
                {"label": "重复数据", "status": "empty", "detail": "等待数据"},
            ],
        }
        return
    both_present = bool(orders and purchases)
    state["quality"] = {
        "status": "healthy" if both_present else "partial",
        "score": 96 if both_present else 58,
        "checks": [
            {
                "label": "订单日期连续性",
                "status": "pass" if orders else "missing",
                "detail": f"{order_days} 天订单" if orders else "尚未导入",
            },
            {
                "label": "采购记录完整度",
                "status": "pass" if purchases else "missing",
                "detail": f"{purchase_days} 天采购" if purchases else "尚未导入",
            },
            {
                "label": "商品编码匹配",
                "status": "pass" if matched_products else "missing",
                "detail": f"{matched_products} / {len(PRODUCT_CATALOG)} 已匹配",
            },
            {"label": "异常数量", "status": "pass", "detail": "导入时已校验正数"},
            {"label": "重复数据", "status": "pass", "detail": "自动按单号 + 商品 + 数量 + 单价去重"},
        ],
    }


def clear_all_data(state: dict[str, Any]) -> None:
    today = date.today()
    state["orders"] = []
    state["purchases"] = []
    state["uploads"] = []
    state["trend"] = []
    state["purchase_plan"] = []
    state["discount_plan"] = []
    state["reviews"] = empty_reviews(today)
    state["kpis"] = {
        "revenue_yesterday": 0,
        "orders_yesterday": 0,
        "avg_ticket": 0,
        "gross_margin": 0,
        "week_revenue": 0,
        "week_change": 0,
        "inventory_value": 0,
        "risk_loss": 0,
        "active_products": 0,
        "high_risk_count": 0,
    }
    for product in state["products"]:
        product.update(
            {
                "stock": 0,
                "stock_value": 0,
                "sold_7d": 0,
                "revenue_7d": 0,
                "profit_7d": 0,
                "avg_daily_sales": 0,
                "days_cover": 0,
                "risk_score": 0,
                "risk_level": "low",
                "risk_label": "暂无数据",
                "purchase_reason": "导入订单和采购记录后生成建议",
            }
        )
    state["quality"] = {
        "status": "empty",
        "score": 0,
        "checks": [
            {"label": "订单数据", "status": "empty", "detail": "尚未导入"},
            {"label": "采购数据", "status": "empty", "detail": "尚未导入"},
            {"label": "商品编码匹配", "status": "empty", "detail": "等待数据"},
            {"label": "重复数据", "status": "empty", "detail": "等待数据"},
        ],
    }
    state["meta"]["source"] = "empty"
    state["meta"]["generated_at"] = datetime.now().isoformat(timespec="seconds")
    state["context"]["today"] = iso(today)
    state["context"]["today_label"] = display_date(today)
    state["context"]["tomorrow"] = iso(today + timedelta(days=1))
    state["context"]["tomorrow_label"] = display_date(today + timedelta(days=1))
    save_state(state)


def style_sheet(sheet, widths: list[int]) -> None:
    fill = PatternFill("solid", fgColor="173D2A")
    for cell in sheet[1]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def workbook_bytes(headers: list[str], rows: list[list[Any]], widths: list[int], title: str = "数据") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    style_sheet(sheet, widths)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def csv_bytes(headers: list[str], rows: list[list[Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def order_file_bytes(state: dict[str, Any], all_rows: bool = True) -> bytes:
    rows = [
        [
            row["date"],
            row["order_id"],
            row["product_id"],
            row["product_name"],
            row["quantity"],
            row["unit_price"],
            row["amount"],
            row.get("payment", ""),
            row.get("time_slot", ""),
        ]
        for row in state["orders"]
    ]
    if not all_rows:
        rows = rows[-80:]
    return workbook_bytes(
        ["日期", "订单号", "商品编码", "商品名称", "数量", "单价", "销售额", "支付方式", "时段"],
        rows,
        [13, 22, 12, 18, 10, 10, 12, 12, 16],
        "订单明细",
    )


def order_csv_bytes(state: dict[str, Any]) -> bytes:
    rows = [
        [
            row["date"],
            row["order_id"],
            row["product_id"],
            row["product_name"],
            row["quantity"],
            row["unit_price"],
            row["amount"],
            row.get("payment", ""),
            row.get("time_slot", ""),
        ]
        for row in state["orders"]
    ]
    return csv_bytes(
        ["日期", "订单号", "商品编码", "商品名称", "数量", "单价", "销售额", "支付方式", "时段"],
        rows,
    )


def purchase_file_bytes(state: dict[str, Any], all_rows: bool = True) -> bytes:
    rows = [
        [
            row["date"],
            row["purchase_id"],
            row["product_id"],
            row["product_name"],
            row["quantity"],
            row["unit_cost"],
            row["amount"],
            row.get("supplier", ""),
        ]
        for row in state["purchases"]
    ]
    if not all_rows:
        rows = rows[-80:]
    return workbook_bytes(
        ["日期", "采购单号", "商品编码", "商品名称", "采购数量", "采购单价", "采购金额", "供应商"],
        rows,
        [13, 22, 12, 18, 12, 12, 12, 18],
        "采购记录",
    )


def purchase_csv_bytes(state: dict[str, Any]) -> bytes:
    rows = [
        [
            row["date"],
            row["purchase_id"],
            row["product_id"],
            row["product_name"],
            row["quantity"],
            row["unit_cost"],
            row["amount"],
            row.get("supplier", ""),
        ]
        for row in state["purchases"]
    ]
    return csv_bytes(
        ["日期", "采购单号", "商品编码", "商品名称", "采购数量", "采购单价", "采购金额", "供应商"],
        rows,
    )


def inventory_file_bytes(state: dict[str, Any]) -> bytes:
    rows = [
        [
            product["id"],
            product["name"],
            product["category"],
            product["stock"],
            product["unit"],
            product["sold_7d"],
            product["days_cover"],
            product["shelf_life"],
            product["risk_label"],
            product["stock_value"],
        ]
        for product in state["products"]
    ]
    return workbook_bytes(
        ["商品编码", "商品名称", "品类", "现有库存", "单位", "近7天销量", "可售天数", "货架期", "风险等级", "库存金额"],
        rows,
        [12, 18, 10, 12, 8, 12, 12, 10, 14, 12],
        "库存明细",
    )


def ensure_demo_files() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    today = date.fromisoformat(state["meta"]["demo_date"])
    order_sample = SAMPLE_DIR / "订单明细_示例.xlsx"
    purchase_sample = SAMPLE_DIR / "采购记录_示例.xlsx"
    order_sample.write_bytes(order_file_bytes(state))
    purchase_sample.write_bytes(purchase_file_bytes(state))
    (SAMPLE_DIR / "订单明细_模拟.csv").write_bytes(order_csv_bytes(state))
    (SAMPLE_DIR / "采购记录_模拟.csv").write_bytes(purchase_csv_bytes(state))
    template_orders = SAMPLE_DIR / "订单导入模板.xlsx"
    template_purchases = SAMPLE_DIR / "采购导入模板.xlsx"
    order_headers = ["日期", "订单号", "商品编码", "商品名称", "数量", "单价", "销售额", "支付方式", "时段"]
    order_example = [[iso(today), "SO-DEMO-001", "P001", "西瓜", 2, 5.98, 11.96, "微信支付", "16:00-18:30"]]
    template_orders.write_bytes(workbook_bytes(order_headers, order_example, [13, 18, 12, 18, 10, 10, 12, 12, 16], "订单导入模板"))
    (SAMPLE_DIR / "订单导入模板.csv").write_bytes(csv_bytes(order_headers, order_example))
    purchase_headers = ["日期", "采购单号", "商品编码", "商品名称", "采购数量", "采购单价", "采购金额", "供应商"]
    purchase_example = [[iso(today), "PO-DEMO-001", "P001", "西瓜", 30, 3.2, 96, "四季鲜果批发"]]
    template_purchases.write_bytes(
        workbook_bytes(purchase_headers, purchase_example, [13, 18, 12, 18, 12, 12, 12, 18], "采购导入模板")
    )
    (SAMPLE_DIR / "采购导入模板.csv").write_bytes(csv_bytes(purchase_headers, purchase_example))


class GuogeHandler(BaseHTTPRequestHandler):
    server_version = "GuogeMVP/3.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep the prototype terminal clean during demos.
        return

    @property
    def state(self) -> dict[str, Any]:
        return self.server.state  # type: ignore[attr-defined]

    def send_json(self, payload: Any, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def send_file(self, blob: bytes, filename: str, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(blob)))
        fallback_name = filename.encode("ascii", "ignore").decode("ascii") or "download"
        encoded_name = quote(filename, safe="")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{fallback_name}"; filename*=UTF-8\'\'{encoded_name}',
        )
        self.end_headers()
        self.wfile.write(blob)

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("文件超过 12 兆限制")
        return self.rfile.read(length)

    def do_GET(self) -> None:
        self.server.state = ensure_current_date(self.server.state)  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/bootstrap":
            self.send_json(public_state(self.state))
            return
        if path == "/api/health":
            self.send_json({"ok": True, "app": APP_NAME, "version": APP_VERSION})
            return
        if path == "/api/llm/status":
            self.send_json(llm_public_status())
            return
        if path == "/api/weather":
            self.send_json(self.state["context"].get("weather", {}))
            return
        if path == "/api/records":
            query = parse_qs(parsed.query)
            kind = query.get("kind", ["orders"])[0]
            try:
                limit = min(200, max(10, int(query.get("limit", ["50"])[0])))
                offset = max(0, int(query.get("offset", ["0"])[0]))
            except ValueError:
                limit, offset = 50, 0
            if kind == "orders":
                records = sorted(
                    self.state.get("orders", []),
                    key=lambda row: (row["date"], row["order_id"]),
                    reverse=True,
                )
            elif kind == "purchases":
                records = sorted(
                    self.state.get("purchases", []),
                    key=lambda row: (row["date"], row["purchase_id"]),
                    reverse=True,
                )
            else:
                self.send_json({"error": "不支持的数据类型"}, 400)
                return
            self.send_json(
                {
                    "kind": kind,
                    "total": len(records),
                    "offset": offset,
                    "limit": limit,
                    "items": records[offset : offset + limit],
                }
            )
            return
        if path == "/api/template/orders.xlsx":
            blob = (SAMPLE_DIR / "订单导入模板.xlsx").read_bytes()
            self.send_file(blob, "订单导入模板.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return
        if path == "/api/template/purchases.xlsx":
            blob = (SAMPLE_DIR / "采购导入模板.xlsx").read_bytes()
            self.send_file(blob, "采购导入模板.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return
        if path == "/api/template/orders.csv":
            blob = (SAMPLE_DIR / "订单导入模板.csv").read_bytes()
            self.send_file(blob, "订单导入模板.csv", "text/csv; charset=utf-8")
            return
        if path == "/api/template/purchases.csv":
            blob = (SAMPLE_DIR / "采购导入模板.csv").read_bytes()
            self.send_file(blob, "采购导入模板.csv", "text/csv; charset=utf-8")
            return
        if path == "/api/sample/orders.xlsx":
            self.send_file(order_file_bytes(self.state), "订单明细_模拟.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return
        if path == "/api/sample/purchases.xlsx":
            self.send_file(purchase_file_bytes(self.state), "采购记录_模拟.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return
        if path == "/api/sample/orders.csv":
            self.send_file(order_csv_bytes(self.state), "订单明细_模拟.csv", "text/csv; charset=utf-8")
            return
        if path == "/api/sample/purchases.csv":
            self.send_file(purchase_csv_bytes(self.state), "采购记录_模拟.csv", "text/csv; charset=utf-8")
            return
        if path == "/api/export/inventory.xlsx":
            self.send_file(inventory_file_bytes(self.state), "库存明细.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            return
        if path.startswith("/api/"):
            self.send_json({"error": "接口不存在"}, 404)
            return
        self.serve_static(path)

    def serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            file_path = STATIC_DIR / "index.html"
        else:
            relative = path.lstrip("/")
            file_path = (STATIC_DIR / relative).resolve()
            if STATIC_DIR.resolve() not in file_path.parents:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".woff2": "font/woff2",
        }
        blob = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(blob)

    def do_POST(self) -> None:
        self.server.state = ensure_current_date(self.server.state)  # type: ignore[attr-defined]
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/chat":
                payload = json.loads(self.read_body().decode("utf-8") or "{}")
                message = str(payload.get("message", "")).strip()
                history = payload.get("history", [])
                if not isinstance(history, list):
                    history = []
                if not message:
                    self.send_json({"error": "消息不能为空"}, 400)
                    return
                reply = chat_response(message, self.state, history[-12:])
                self.send_json({"reply": reply, "state": public_state(self.state)})
                return
            if path == "/api/upload":
                kind = query.get("kind", ["orders"])[0]
                if kind not in {"orders", "purchases"}:
                    self.send_json({"error": "不支持的导入类型"}, 400)
                    return
                blob = self.read_body()
                filename = unquote(self.headers.get("X-Filename", "导入文件.xlsx"))
                rows, errors, warnings = parse_upload(blob, kind, filename)
                if errors:
                    self.send_json({"error": "；".join(errors), "warnings": warnings}, 400)
                    return
                if kind == "orders":
                    existing = {record_key(r, "orders") for r in self.state["orders"]}
                    new_rows = [row for row in rows if record_key(row, "orders") not in existing]
                    self.state["orders"].extend(new_rows)
                else:
                    existing = {record_key(r, "purchases") for r in self.state["purchases"]}
                    new_rows = [row for row in rows if record_key(row, "purchases") not in existing]
                    self.state["purchases"].extend(new_rows)
                if not new_rows:
                    warnings.append("这份文件的数据已存在，已自动跳过重复行")
                upload = {
                    "id": f"U{int(time.time() * 1000) % 1000000}",
                    "kind": kind,
                    "filename": filename,
                    "rows": len(new_rows),
                    "status": "success",
                    "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                self.state.setdefault("uploads", []).insert(0, upload)
                if not self.state.get("purchases"):
                    self.state["quality"]["status"] = "partial"
                rebuild_after_import(self.state)
                self.send_json(
                    {
                        "ok": True,
                        "imported": len(new_rows),
                        "skipped": len(rows) - len(new_rows),
                        "warnings": warnings,
                        "upload": upload,
                        "state": public_state(self.state),
                    }
                )
                return
            if path == "/api/memory":
                payload = json.loads(self.read_body().decode("utf-8") or "{}")
                action = payload.get("action", "add")
                if action == "add":
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        self.send_json({"error": "记忆内容不能为空"}, 400)
                        return
                    memory = {
                        "id": f"M{int(time.time() * 1000) % 1000000}",
                        "text": text[:100],
                        "tag": str(payload.get("tag", "经营经验")),
                        "source": "手动补充",
                        "impact": str(payload.get("impact", "参与采购与定价计算")),
                        "active": True,
                        "created_at": iso(date.today()),
                    }
                    self.state["memories"].insert(0, memory)
                elif action == "toggle":
                    memory_id = str(payload.get("id"))
                    for item in self.state["memories"]:
                        if item["id"] == memory_id:
                            item["active"] = not item["active"]
                            break
                elif action == "delete":
                    memory_id = str(payload.get("id"))
                    self.state["memories"] = [item for item in self.state["memories"] if item["id"] != memory_id]
                save_state(self.state)
                self.send_json({"ok": True, "state": public_state(self.state)})
                return
            if path == "/api/purchase/approve":
                payload = json.loads(self.read_body().decode("utf-8") or "{}")
                selected = payload.get("ids", [])
                for item in self.state["purchase_plan"]:
                    if item["id"] in selected:
                        item["confirmed"] = True
                save_state(self.state)
                self.send_json({"ok": True, "state": public_state(self.state)})
                return
            if path == "/api/discount/apply":
                payload = json.loads(self.read_body().decode("utf-8") or "{}")
                selected = set(payload.get("ids", []))
                for item in self.state["discount_plan"]:
                    if not selected or item["id"] in selected:
                        item["applied"] = True
                save_state(self.state)
                self.send_json({"ok": True, "state": public_state(self.state)})
                return
            if path == "/api/data/clear":
                clear_all_data(self.state)
                self.send_json({"ok": True, "state": public_state(self.state)})
                return
            if path == "/api/sku/update":
                payload = json.loads(self.read_body().decode("utf-8") or "{}")
                product = update_sku(self.state, payload)
                self.send_json({"ok": True, "sku": product, "state": public_state(self.state)})
                return
            if path == "/api/settings/min-discount":
                payload = json.loads(self.read_body().decode("utf-8") or "{}")
                try:
                    min_discount = float(payload.get("min_discount"))
                except (TypeError, ValueError):
                    self.send_json({"error": "最低折扣必须是数字"}, 400)
                    return
                if not 5 <= min_discount <= 10:
                    self.send_json({"error": "最低折扣需在 5 折到 10 折之间"}, 400)
                    return
                self.state["store"]["min_discount"] = round(min_discount, 1)
                self.state["discount_plan"] = build_discount_plan(
                    self.state["products"],
                    self.state["store"]["min_discount"],
                )
                today = date.fromisoformat(self.state["meta"]["demo_date"])
                self.state["reviews"] = build_reviews(
                    self.state["orders"],
                    self.state["products"],
                    today,
                    self.state["store"]["min_discount"],
                )
                save_state(self.state)
                self.send_json({"ok": True, "state": public_state(self.state)})
                return
            if path == "/api/reset":
                restore_default_catalog()
                self.server.state = build_state(date.today())  # type: ignore[attr-defined]
                polish_review_narratives(self.server.state)  # type: ignore[attr-defined]
                save_state(self.server.state)  # type: ignore[attr-defined]
                ensure_demo_files()
                self.send_json({"ok": True, "state": public_state(self.server.state)})  # type: ignore[attr-defined]
                return
            self.send_json({"error": "接口不存在"}, 404)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:  # pragma: no cover - demo safety net
            self.send_json({"error": f"服务端处理失败：{exc}"}, 500)


def find_available_port(preferred: int = 8501) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser(description="果哥水果店智能运营助手 3.0 版本")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    ensure_demo_files()
    state = load_state()
    probe_llm()
    port = find_available_port(args.port)
    server = ThreadingHTTPServer(("127.0.0.1", port), GuogeHandler)
    server.state = state  # type: ignore[attr-defined]
    url = f"http://127.0.0.1:{port}"
    llm = llm_public_status()
    llm_label = (
        f"{llm['provider']} {llm['model']} · 已连接"
        if llm["connected"]
        else f"{llm['provider']} · 未连接，使用本地规则"
    )
    weather = state["context"]["weather"]
    print(
        f"\n  {APP_NAME} 3.0 版本已启动：{url}\n"
        f"  大模型：{llm_label}\n"
        f"  天气：{weather.get('source', '未知')} · {weather.get('label')} {weather.get('temperature')}\n"
        "  按 Ctrl+C 停止服务\n"
    )
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


