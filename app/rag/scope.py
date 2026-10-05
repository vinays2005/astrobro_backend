"""Which parts of the knowledge base a question may draw on.

The main collection holds Vedic astrology. Specialist material (tarot, numerology, Vastu, festivals, calendar
science, Puranic lore) lives in a separate collection, so a question about Saturn's transit can never be answered
from a tarot book. A question is routed by its detected topic: tarot and numerology questions read only their own
books, while Vastu, panchang, muhurat and remedies questions read the Vedic collection plus the matching domains.
"""
from __future__ import annotations

from dataclasses import dataclass

DOMAINS = ("tarot", "numerology", "vastu", "festivals", "calendar", "lore")

# Titles in the main collection that belong to another tradition or are off-topic for a Vedic astrology app.
# They carry no domain tag, so they are hidden by exact title. Edit this list to change what the chat may quote.
HIDDEN_TITLES: tuple[str, ...] = (
    "Hellenistic Astrology - Chris Brennan",
    "Tetrabiblos - Ptolemy",
    "tetrabiblos",
    "Christian Astrology - William Lilly",
    "Christian Astrology",
    "Ptolemy's Science of The Stars in the Middle Ages",
    "Early Christianity And Ancient Astrology",
    "Encyclopedia of Medical Astrology L. Cornell",
    "Astrology For Beginners An Easy Guide To Understanding & Interpreting Your Chart ( Llewellyn's Modern Astrology Library ",
    "Gallileo Was Wrong",
    "Numerology The Romance In Your Name",
    "Cheiro Ank Jyotish By Cheiro Hindi Numerology Delhi 2014 New Sadhana Pocket Books",
)


@dataclass(frozen=True)
class Scope:
    general: bool = True              # search the main (Vedic astrology) collection
    domains: tuple[str, ...] = ()     # specialist domains that may also be searched


DEFAULT = Scope()

_ROUTES: dict[str, Scope] = {
    "tarot": Scope(general=False, domains=("tarot",)),
    "numerology": Scope(general=False, domains=("numerology",)),
    "vastu": Scope(domains=("vastu", "lore")),
    "panchang": Scope(domains=("festivals", "calendar", "lore")),
    "muhurat": Scope(domains=("festivals", "calendar", "lore")),
    "remedies": Scope(domains=("lore",)),
}


def scope_for(question: str) -> Scope:
    """Route a question by its detected topic; anything unrecognised searches the Vedic collection only."""
    from app.astrology.intent import classify

    return _ROUTES.get(classify(question)["category"], DEFAULT)
