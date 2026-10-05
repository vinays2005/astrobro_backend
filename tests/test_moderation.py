"""Chat moderation: block ways of taking a conversation off the platform, but never birth details."""
from __future__ import annotations

import pytest

from app.services.moderation import contact_info_reason


@pytest.mark.parametrize("text,kind", [
    ("call me on 9876543210", "a phone number"),
    ("my number is 98765 43210", "a phone number"),
    ("+91 98765-43210 whatsapp", "a phone number"),
    ("+919876543210", "a phone number"),
    ("98 76 54 32 10", "a phone number"),
    ("9 8 7 6 5 4 3 2 1 0", "a phone number"),
    ("+1 415 555 2671", "a phone number"),
    ("mail me at someone@example.com", "an email address"),
    ("find me at https://instagram.com/xyz", "a web link"),
    ("see www.mysite.in", "a web link"),
    ("astro.co is my site", "a web link"),
])
def test_contact_details_are_caught(text, kind):
    assert contact_info_reason(text) == kind


@pytest.mark.parametrize("text", [
    "I was born on 15-08-1990 at 14:30 in Mumbai",
    "DOB 15/08/1990, time 02:30 PM, place: Pune",
    "born 1990 08 15 14 30",                                    # lots of digits, but not a phone number
    "my birth year is 1990 and my wife was born in 1992",
    "will I get a job in 2027? I have 3 offers and 2 interviews",
    "my lucky number is 7 and my flat number is 1204",
    "Saturn transit in 2026 and 2027 and 2028 and 2029",
    "I scored 85 percent in class 12 and 92 in class 10",
    "yes", "thank you, that helps a lot",
])
def test_birth_details_and_ordinary_numbers_are_fine(text):
    assert contact_info_reason(text) is None
