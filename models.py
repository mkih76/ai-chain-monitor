"""
信号模型定义 — 整个系统的核心数据结构
所有模块产生的信号都遵循此格式
"""
import uuid
import json
from datetime import datetime, timedelta
from enum import Enum


class Severity(str, Enum):
    S1_CRITICAL = "S1"  # 多源共振(>=3), 置信度>0.8
    S2_HIGH = "S2"      # 单源强信号+1个佐证
    S3_MEDIUM = "S3"    # 单源中等信号
    S4_WATCH = "S4"     # 弱信号/待确认


class Direction(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalStatus(str, Enum):
    ACTIVE = "active"           # 刚产生
    CONFIRMED = "confirmed"     # 被其他源佐证
    EXPIRED = "expired"         # 超时未验证
    VERIFIED = "verified"       # 价格按预期方向移动
    INVALIDATED = "invalidated" # 价格反向移动


class SignalSource(str, Enum):
    INVENTORY = "inventory"       # M1 库存
    CAPITAL = "capital"           # M2 资金
    COMMODITY = "commodity"       # M3 商品期货
    ANNOUNCEMENT = "announcement" # M6 公告
    OVERSEAS = "overseas"         # M7 海外
    NEWS = "news"                 # M8 新闻验证


class Signal:
    """
    信号对象 — 流水线的核心货币
    从检测器产生，经关联分析增强，由AI研判最终输出
    """

    def __init__(self, source: str, type_: str, target_stocks: list,
                 target_sectors: list, direction: str, severity: str,
                 description: str, raw_data: dict = None,
                 lead_time_days: int = 3, confidence: float = 0.5,
                 strength: float = 50.0):
        self.id = str(uuid.uuid4())[:12]
        self.timestamp = datetime.now().isoformat()
        self.source = source
        self.type = type_
        self.target_stocks = target_stocks or []
        self.target_sectors = target_sectors or []
        self.direction = direction
        self.severity = severity
        self.lead_time_days = lead_time_days
        self.confidence = min(max(confidence, 0), 1.0)
        self.strength = min(max(strength, 0), 100)
        self.raw_data = raw_data or {}
        self.description = description
        self.corroboration = []  # list of signal IDs
        self.status = SignalStatus.ACTIVE
        self.ai_verdict = None
        self.price_at_creation = None
        self.price_verified_at = None
        self.price_change_pct = None

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "source": self.source,
            "type": self.type,
            "target_stocks": self.target_stocks,
            "target_sectors": self.target_sectors,
            "direction": self.direction,
            "severity": self.severity,
            "lead_time_days": self.lead_time_days,
            "confidence": round(self.confidence, 3),
            "strength": round(self.strength, 1),
            "raw_data": self.raw_data,
            "description": self.description,
            "corroboration": self.corroboration,
            "status": self.status,
            "ai_verdict": self.ai_verdict,
            "price_at_creation": self.price_at_creation,
            "price_verified_at": self.price_verified_at,
            "price_change_pct": self.price_change_pct,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d):
        s = cls(
            source=d["source"],
            type_=d["type"],
            target_stocks=d.get("target_stocks", []),
            target_sectors=d.get("target_sectors", []),
            direction=d.get("direction", "neutral"),
            severity=d.get("severity", "S4"),
            description=d.get("description", ""),
            raw_data=d.get("raw_data", {}),
            lead_time_days=d.get("lead_time_days", 3),
            confidence=d.get("confidence", 0.5),
            strength=d.get("strength", 50),
        )
        s.id = d.get("id", s.id)
        s.timestamp = d.get("timestamp", s.timestamp)
        s.corroboration = d.get("corroboration", [])
        s.status = d.get("status", "active")
        s.ai_verdict = d.get("ai_verdict")
        s.price_at_creation = d.get("price_at_creation")
        s.price_verified_at = d.get("price_verified_at")
        s.price_change_pct = d.get("price_change_pct")
        return s

    def is_expired(self, hours=None):
        """检查信号是否过期"""
        if self.status in (SignalStatus.EXPIRED, SignalStatus.VERIFIED,
                           SignalStatus.INVALIDATED):
            return True
        created = datetime.fromisoformat(self.timestamp)
        ttl_hours = hours or (120 if self.corroboration else 72)
        return (datetime.now() - created).total_seconds() / 3600 > ttl_hours

    def __repr__(self):
        return (f"Signal({self.severity} {self.source}/{self.type} "
                f"→ {self.target_sectors} conf={self.confidence:.2f})")


def make_signal(source, type_, target_stocks, target_sectors,
                direction, severity, description, **kwargs):
    """工厂函数，简化信号创建"""
    return Signal(
        source=source,
        type_=type_,
        target_stocks=target_stocks,
        target_sectors=target_sectors,
        direction=direction,
        severity=severity,
        description=description,
        **kwargs,
    )
