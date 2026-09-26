from enum import StrEnum


class ProjectType(StrEnum):
    SUBSTATION = "substation"
    TRANSMISSION_LINE = "transmission line"
    GENERATION = "generation"

    @classmethod
    def coerce(cls, value: object) -> "ProjectType | None":
        """Map a loosely-typed value to the enum, or None when it can't be classified."""
        if value is None:
            return None
        text = str(value).strip().lower().replace("_", " ").replace("-", " ")
        if not text:
            return None
        for member in cls:
            if text == member.value:
                return member
        aliases = {
            "sub": cls.SUBSTATION,
            "substations": cls.SUBSTATION,
            "transmission": cls.TRANSMISSION_LINE,
            "line": cls.TRANSMISSION_LINE,
            "transmission lines": cls.TRANSMISSION_LINE,
            "gen": cls.GENERATION,
            "generator": cls.GENERATION,
            "generating station": cls.GENERATION,
        }
        return aliases.get(text)


class DatePrecision(StrEnum):
    YEAR = "year"
    QUARTER = "quarter"
    MONTH = "month"
    DAY = "day"


class PlanStatus(StrEnum):
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class CostScope(StrEnum):
    """What a project physically does, which drives its cost (services/pricing.py)."""

    NEW_LINE = "new_line"
    LINE_REBUILD = "line_rebuild"
    RECONDUCTOR = "reconductor"
    UPRATE = "uprate"
    LINE_TERMINAL = "line_terminal"
    NEW_SUBSTATION = "new_substation"
    SUBSTATION_REBUILD = "substation_rebuild"
    EXPANSION = "expansion"
    TRANSFORMER = "transformer"
    REACTIVE = "reactive"
    BREAKER = "breaker"
    PROTECTION = "protection"
    RETIREMENT = "retirement"
    SUBSTATION_GENERAL = "substation_general"
