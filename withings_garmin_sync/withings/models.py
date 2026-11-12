"""Data models for Withings measurements."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


class WithingsMeasure:
    """Individual measurement reading from Withings."""

    TYPE_WEIGHT = 1
    TYPE_HEIGHT = 4
    TYPE_FAT_FREE_MASS = 5
    TYPE_FAT_RATIO = 6
    TYPE_FAT_MASS_WEIGHT = 8
    TYPE_DIASTOLIC_BP = 9
    TYPE_SYSTOLIC_BP = 10
    TYPE_HEART_PULSE = 11
    TYPE_MUSCLE_MASS = 76
    TYPE_HYDRATION = 77
    TYPE_BONE_MASS = 88
    TYPE_PULSE_WAVE_VELOCITY = 91

    def __init__(self, raw: Dict[str, Any]):
        self._raw = raw
        self.value = raw.get("value", 0)
        self.type = raw.get("type", 0)
        self.unit = raw.get("unit", 0)

    def get_value(self) -> float:
        """Returns the actual value after applying the 10^unit exponent."""
        return float(self.value * pow(10, self.unit))


class WithingsMeasureGroup:
    """A group of measurements taken at the same timestamp."""

    def __init__(self, raw_group: Dict[str, Any]):
        self._raw = raw_group
        self.grpid: int = raw_group.get("grpid", 0)
        self.attrib: int = raw_group.get("attrib", 0)
        self.date: int = raw_group.get("date", 0)
        self.category: int = raw_group.get("category", 1)
        self.measures: List[WithingsMeasure] = [
            WithingsMeasure(m) for m in raw_group.get("measures", [])
        ]

    def get_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.date)

    def get_weight(self) -> Optional[float]:
        for m in self.measures:
            if m.type == WithingsMeasure.TYPE_WEIGHT:
                return round(m.get_value(), 2)
        return None

    def get_height(self) -> Optional[float]:
        for m in self.measures:
            if m.type == WithingsMeasure.TYPE_HEIGHT:
                return round(m.get_value(), 2)
        return None

    def get_fat_ratio(self) -> Optional[float]:
        for m in self.measures:
            if m.type == WithingsMeasure.TYPE_FAT_RATIO:
                return round(m.get_value(), 2)
        return None

    def get_muscle_mass(self) -> Optional[float]:
        for m in self.measures:
            if m.type == WithingsMeasure.TYPE_MUSCLE_MASS:
                return round(m.get_value(), 2)
        return None

    def get_hydration(self) -> Optional[float]:
        for m in self.measures:
            if m.type == WithingsMeasure.TYPE_HYDRATION:
                return round(m.get_value(), 2)
        return None

    def get_bone_mass(self) -> Optional[float]:
        for m in self.measures:
            if m.type == WithingsMeasure.TYPE_BONE_MASS:
                return round(m.get_value(), 2)
        return None


@dataclass
class WeightRecord:
    """Consolidated weight and body composition measurement."""

    grpid: int
    date_time: datetime
    weight: float
    fat_ratio: Optional[float] = None
    muscle_mass: Optional[float] = None
    bone_mass: Optional[float] = None
    hydration: Optional[float] = None
    percent_hydration: Optional[float] = None
    bmi: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grpid": self.grpid,
            "date_time": self.date_time.isoformat(),
            "weight": self.weight,
            "fat_ratio": self.fat_ratio,
            "muscle_mass": self.muscle_mass,
            "bone_mass": self.bone_mass,
            "percent_hydration": self.percent_hydration,
            "bmi": self.bmi,
        }
