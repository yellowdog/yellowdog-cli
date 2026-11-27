"""
How `yd usage` writes a duration, a cost and a size, and reads the report's times,
shared by the command and Commander's Usage Explorer so that both read
alike. Stdlib only: Commander imports it, and may import neither the SDK nor
the command's own modules.
"""

import re
from datetime import datetime

_SECONDS_PER_MINUTE = 60

# A time's fraction of a second, of any length
_FRACTION = re.compile(r"\.(\d+)")

# The keys whose column heading is not the key itself, capitalised
_HEADINGS = {
    "cr": "Compute Requirement",
    "cr-id": "Compute Requirement ID",
    "creator-id": "Creator ID",
    "instance-id": "Instance ID",
}


def heading(key: str) -> str:
    """
    A '--by' key's column heading: 'instance-type' as 'Instance type'.
    """
    return _HEADINGS.get(key) or key.replace("-", " ").capitalize()


def report_time(text: str) -> datetime:
    """
    A time as the report writes it ('2026-11-12T07:46:44.428279Z'), read
    alike on every Python the CLI supports: a 'Z' as UTC, and a fraction of
    a second of any length cut or padded to microseconds, since before 3.11
    datetime.fromisoformat() takes neither, and only 3 or 6 digits, where
    the Platform may write 0 to 9. Aware or naive as the text is; raises
    ValueError for a text that is not a time.
    """
    text = text.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = _FRACTION.sub(lambda m: "." + (m.group(1) + "000000")[:6], text, count=1)
    return datetime.fromisoformat(text)


def duration_text(seconds: float) -> str:
    """
    A duration as the table gives it, hours and minutes ('351:24', thousands
    of hours separated), to the nearest minute; under a minute but more than
    none is '<0:01', so that time spent never reads as none.
    """
    if 0 < seconds < _SECONDS_PER_MINUTE:
        return "<0:01"
    minutes = int(seconds / _SECONDS_PER_MINUTE + 0.5)
    return f"{minutes // 60:,}:{minutes % 60:02}"


def cost_text_of(cost: float | None, partial: bool) -> str:
    """
    A cost as the table shows it: '12.34', '12.34+' when some of the running
    time had no price (a lower bound, `partial`), '-' when none had one.
    """
    if cost is None:
        return "-"
    return f"{cost:,.2f}" + ("+" if partial else "")


def size_text(size: int) -> str:
    """
    A size in bytes in powers of 1000, as Finder and Windows Explorer give
    it (and Commander's file previews), one decimal place above a kilobyte.
    """
    if size < 1000:
        return f"{size} byte{'' if size == 1 else 's'}"
    scaled = float(size)
    for unit in ("kB", "MB"):
        scaled /= 1000
        if scaled < 1000:
            return f"{scaled:,.1f} {unit}"
    return f"{scaled / 1000:,.1f} GB"
