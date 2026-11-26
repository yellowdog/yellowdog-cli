"""
How `yd usage` writes a duration and a cost, shared by the command and
Commander's Usage Explorer so that both read alike. Stdlib only: Commander
imports it, and may import neither the SDK nor the command's own modules.
"""

_SECONDS_PER_MINUTE = 60

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
