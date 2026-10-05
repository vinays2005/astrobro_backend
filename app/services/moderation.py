"""Keep consultations on the platform: refuse phone numbers, email addresses and links in chat messages.

Birth details must stay possible ("15-08-1990 at 14:30"), so a phone number means a run of ten digits shaped like a
mobile number, not any text that contains many digits.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|in|co|me|io|app|net|org|xyz|link)\b", re.IGNORECASE)
_PHONE = re.compile(
    r"(?<!\d)(?:\+?91[\s-]*)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"          # 98765 43210, +91-9876543210
    r"|(?<!\d)[6-9]\d(?:[\s-]\d{2}){4}(?!\d)"                      # 98 76 54 32 10
    r"|\+\d[\d\s-]{8,}\d"                                          # international numbers
    r"|(?:\b\d\b[\s.,-]+){9,}\b\d\b"                               # 9 8 7 6 5 4 3 2 1 0 (digits spelled out one by one)
)


def contact_info_reason(text: str) -> str | None:
    """What kind of contact detail the text contains, or None when it is fine."""
    if _EMAIL.search(text):
        return "an email address"
    if _PHONE.search(text):
        return "a phone number"
    if _URL.search(text):
        return "a web link"
    return None
