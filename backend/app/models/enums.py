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
