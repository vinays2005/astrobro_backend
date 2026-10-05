"""Marriage compatibility: Ashtakoota (Guna Milan) and related checks. Deterministic, no I/O.

Conventions where sources differ are fixed here and noted inline. Yoni matrix, Vashya matrix
and Graha Maitri values were cross-checked against the PyJHora library and mainstream references.
Roles: "boy" = groom, "girl" = bride.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.astrology.constants import (
    NAKSHATRA_LORDS,
    NAKSHATRAS,
    NATURAL_ENEMIES,
    NATURAL_FRIENDS,
    SIGN_LORDS,
    SIGNS,
)

NAK_SPAN = 360.0 / 27.0

# ── Nakshatra / sign attribute tables ─────────────────────────────────────────

GANA_NAMES = ["Deva", "Manushya", "Rakshasa"]
_DEVA = {0, 4, 6, 7, 12, 14, 16, 21, 26}
_RAKSHASA = {2, 8, 9, 13, 15, 17, 18, 22, 23}
NAK_GANA: list[int] = [0 if i in _DEVA else 2 if i in _RAKSHASA else 1 for i in range(27)]

NADI_NAMES = ["Aadi", "Madhya", "Antya"]
NAK_NADI: list[int] = [0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 1, 2]

YONI_ANIMALS = [
    "Horse", "Elephant", "Sheep", "Serpent", "Dog", "Cat", "Rat",
    "Cow", "Buffalo", "Tiger", "Deer", "Monkey", "Mongoose", "Lion",
]
NAK_YONI: list[int] = [0, 1, 2, 3, 3, 4, 5, 2, 5, 6, 6, 7, 8, 9, 8, 9, 10, 10, 4, 11, 12, 11, 13, 0, 13, 7, 1]
YONI_MATRIX: list[list[int]] = [
    [4, 2, 2, 3, 2, 2, 2, 1, 0, 1, 1, 3, 2, 1],
    [2, 4, 3, 3, 2, 2, 2, 2, 3, 1, 2, 3, 2, 0],
    [2, 3, 4, 2, 1, 2, 1, 3, 3, 1, 2, 0, 3, 1],
    [3, 3, 2, 4, 2, 1, 1, 1, 1, 2, 2, 2, 0, 2],
    [2, 2, 1, 2, 4, 2, 1, 2, 2, 1, 0, 2, 1, 1],
    [2, 2, 2, 1, 2, 4, 0, 2, 2, 1, 3, 3, 2, 1],
    [2, 2, 1, 1, 1, 0, 4, 2, 2, 2, 2, 2, 1, 2],
    [1, 2, 3, 1, 2, 2, 2, 4, 3, 0, 3, 2, 2, 1],
    [0, 3, 3, 1, 2, 2, 2, 3, 4, 1, 2, 2, 2, 1],
    [1, 1, 1, 2, 1, 1, 2, 0, 1, 4, 1, 1, 2, 1],
    [1, 2, 2, 2, 0, 3, 2, 3, 2, 1, 4, 2, 2, 1],
    [3, 3, 0, 2, 2, 3, 2, 2, 2, 1, 2, 4, 3, 2],
    [2, 2, 3, 0, 1, 2, 1, 2, 2, 2, 2, 3, 4, 2],
    [1, 0, 1, 2, 1, 1, 2, 1, 1, 1, 1, 2, 2, 4],
]

# Varna by Moon sign: 0 Brahmin, 1 Kshatriya, 2 Vaishya, 3 Shudra (element based)
VARNA_NAMES = ["Brahmin", "Kshatriya", "Vaishya", "Shudra"]
VARNA_BY_SIGN = [1, 2, 3, 0, 1, 2, 3, 0, 1, 2, 3, 0]

# Vashya groups: 0 Chatushpada, 1 Manava, 2 Jalachara, 3 Vanachara, 4 Keeta
VASHYA_NAMES = ["Chatushpada", "Manava", "Jalachara", "Vanachara", "Keeta"]
VASHYA_MATRIX = [  # [girl group][boy group]
    [2.0, 1.0, 1.0, 1.5, 1.0],
    [1.0, 2.0, 1.5, 0.0, 1.0],
    [1.0, 1.5, 2.0, 1.0, 1.0],
    [0.0, 0.0, 0.0, 2.0, 0.0],
    [1.0, 1.0, 1.0, 0.0, 2.0],
]

# Gana points [boy gana][girl gana]; mixed cells follow the direction-aware convention
GANA_MATRIX = [
    [6, 5, 0],
    [5, 6, 1],
    [0, 0, 6],
]

TARA_NAMES = [
    "Janma", "Sampat", "Vipat", "Kshema", "Pratyari",
    "Sadhana", "Naidhana", "Mitra", "Parama Mitra",
]
_BAD_TARAS = {3, 5, 7}

# Rajju groups by 1-based nakshatra number
_RAJJU = {
    "Head": {5, 14, 23},
    "Neck": {4, 6, 13, 15, 22, 24},
    "Stomach": {3, 7, 12, 16, 21, 25},
    "Waist": {2, 8, 11, 17, 20, 26},
    "Foot": {1, 9, 10, 18, 19, 27},
}
_RAJJU_MEANING = {
    "Head": "traditionally linked to the wellbeing of the husband",
    "Neck": "traditionally linked to the wellbeing of the wife",
    "Stomach": "traditionally linked to children and family growth",
    "Waist": "traditionally linked to financial and domestic stability",
    "Foot": "traditionally linked to restlessness and frequent change",
}
_VEDHA_SUMS = {19, 28, 37}
_MAHENDRA_COUNTS = {4, 7, 10, 13, 16, 19, 22, 25}

_KOOTA_MAX = {
    "varna": 1, "vashya": 2, "tara": 3, "yoni": 4,
    "graha_maitri": 5, "gana": 6, "bhakut": 7, "nadi": 8,
}
_KOOTA_MEANING = {
    "varna": "ego and spiritual compatibility",
    "vashya": "mutual attraction and influence",
    "tara": "health and shared destiny",
    "yoni": "physical and intimate compatibility",
    "graha_maitri": "mental compatibility and friendship",
    "gana": "temperament and behaviour",
    "bhakut": "emotional bond and family prosperity",
    "nadi": "health, genetics and progeny",
}


# ── Moon placement ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MoonPlacement:
    longitude: float  # sidereal, 0-360

    @property
    def sign_index(self) -> int:
        return int(self.longitude / 30.0) % 12

    @property
    def nak_index(self) -> int:
        return int(self.longitude / NAK_SPAN) % 27

    @property
    def pada(self) -> int:
        return int((self.longitude % NAK_SPAN) / (NAK_SPAN / 4)) + 1

    @property
    def deg_in_sign(self) -> float:
        return self.longitude % 30.0


def placement_from_indices(nak_index: int, sign_index: int) -> MoonPlacement:
    """Build a placement from nakshatra + sign indices (legacy callers without degrees)."""
    lo = max(sign_index * 30.0, nak_index * NAK_SPAN)
    hi = min((sign_index + 1) * 30.0, (nak_index + 1) * NAK_SPAN)
    lon = (lo + hi) / 2.0 if hi > lo else sign_index * 30.0 + 15.0
    return MoonPlacement(lon)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _attitude(a: str, b: str) -> str:
    if a == b:
        return "same"
    if b in NATURAL_FRIENDS.get(a, []):
        return "friend"
    if b in NATURAL_ENEMIES.get(a, []):
        return "enemy"
    return "neutral"


def _vashya_group(m: MoonPlacement) -> int:
    s, deg = m.sign_index, m.deg_in_sign
    if s in (0, 1):
        return 0
    if s in (2, 5, 6, 10):
        return 1
    if s in (3, 11):
        return 2
    if s == 4:
        return 3
    if s == 7:
        return 4
    if s == 8:  # Sagittarius: first half Manava, second half Chatushpada
        return 1 if deg < 15 else 0
    return 0 if deg < 15 else 2  # Capricorn: first half Chatushpada, second half Jalachara


def _count_from(a_nak: int, b_nak: int) -> int:
    """Inclusive count of nakshatras from a to b (1..27)."""
    return ((b_nak - a_nak) % 27) + 1


def graha_maitri_score(lord_a: str, lord_b: str) -> float:
    if lord_a == lord_b:
        return 5.0
    pair = {_attitude(lord_a, lord_b), _attitude(lord_b, lord_a)}
    if pair == {"friend"}:
        return 5.0
    if pair == {"friend", "neutral"}:
        return 4.0
    if pair == {"neutral"}:
        return 3.0
    if pair == {"friend", "enemy"}:
        return 1.0
    if pair == {"neutral", "enemy"}:
        return 0.5
    return 0.0


# ── The eight kootas ──────────────────────────────────────────────────────────

def ashtakoota(boy: MoonPlacement, girl: MoonPlacement) -> dict:
    """Guna Milan out of 36 with a per-koota breakdown, dosha flags and parihara notes."""
    bs, gs = boy.sign_index, girl.sign_index
    bn, gn = boy.nak_index, girl.nak_index
    breakdown: dict[str, dict] = {}

    # 1. Varna
    bv, gv = VARNA_BY_SIGN[bs], VARNA_BY_SIGN[gs]
    breakdown["varna"] = {
        "score": 1.0 if bv <= gv else 0.0,
        "boy_varna": VARNA_NAMES[bv], "girl_varna": VARNA_NAMES[gv],
        "boy": bv, "girl": gv,
    }

    # 2. Vashya
    bg, gg = _vashya_group(boy), _vashya_group(girl)
    breakdown["vashya"] = {
        "score": VASHYA_MATRIX[gg][bg],
        "boy_group": VASHYA_NAMES[bg], "girl_group": VASHYA_NAMES[gg],
    }

    # 3. Tara — counts both ways; remainders 3, 5, 7 are inauspicious
    rem_from_girl = (_count_from(gn, bn) % 9) or 9
    rem_from_boy = (_count_from(bn, gn) % 9) or 9
    bad = (rem_from_girl in _BAD_TARAS) + (rem_from_boy in _BAD_TARAS)
    breakdown["tara"] = {
        "score": {0: 3.0, 1: 1.5, 2: 0.0}[bad],
        "boy_tara": TARA_NAMES[rem_from_girl - 1],
        "girl_tara": TARA_NAMES[rem_from_boy - 1],
    }

    # 4. Yoni
    by, gy = NAK_YONI[bn], NAK_YONI[gn]
    breakdown["yoni"] = {
        "score": float(YONI_MATRIX[gy][by]),
        "boy_animal": YONI_ANIMALS[by], "girl_animal": YONI_ANIMALS[gy],
    }

    # 5. Graha Maitri
    bl, gl = SIGN_LORDS[bs], SIGN_LORDS[gs]
    gm = graha_maitri_score(bl, gl)
    breakdown["graha_maitri"] = {"score": gm, "boy_lord": bl, "girl_lord": gl}

    # 6. Gana
    bga, gga = NAK_GANA[bn], NAK_GANA[gn]
    breakdown["gana"] = {
        "score": float(GANA_MATRIX[bga][gga]),
        "boy_gana": GANA_NAMES[bga], "girl_gana": GANA_NAMES[gga],
    }

    # 7. Bhakoot — Moon signs 2/12, 5/9 or 6/8 apart score zero
    rel_bg = ((gs - bs) % 12) + 1
    rel_gb = ((bs - gs) % 12) + 1
    bhakoot_bad = {rel_bg, rel_gb} in ({2, 12}, {5, 9}, {6, 8})
    breakdown["bhakut"] = {
        "score": 0.0 if bhakoot_bad else 7.0,
        "relation": f"{min(rel_bg, rel_gb)}/{max(rel_bg, rel_gb)}",
        "boy_sign": SIGNS[bs], "girl_sign": SIGNS[gs],
    }

    # 8. Nadi
    bnadi, gnadi = NAK_NADI[bn], NAK_NADI[gn]
    breakdown["nadi"] = {
        "score": 0.0 if bnadi == gnadi else 8.0,
        "boy_nadi": NADI_NAMES[bnadi], "girl_nadi": NADI_NAMES[gnadi],
    }

    for key, item in breakdown.items():
        item["max"] = _KOOTA_MAX[key]
        item["meaning"] = _KOOTA_MEANING[key]

    total = round(sum(item["score"] for item in breakdown.values()), 1)
    doshas = _koota_doshas(boy, girl, breakdown, gm)

    return {
        "total_score": total,
        "max_score": 36,
        "percentage": round(total / 36 * 100, 1),
        "compatibility": compatibility_band(total),
        "breakdown": breakdown,
        "doshas": doshas,
    }


def compatibility_band(total: float) -> str:
    if total >= 33:
        return "Excellent"
    if total >= 25:
        return "Very Good"
    if total >= 18:
        return "Good"
    if total >= 12:
        return "Average"
    return "Poor"


# ── Doshas and their classical cancellations (parihara) ───────────────────────

def _koota_doshas(
    boy: MoonPlacement, girl: MoonPlacement, breakdown: dict[str, dict], gm_score: float
) -> dict[str, dict]:
    bs, gs, bn, gn = boy.sign_index, girl.sign_index, boy.nak_index, girl.nak_index
    same_lord = SIGN_LORDS[bs] == SIGN_LORDS[gs]
    out: dict[str, dict] = {}

    # Nadi dosha
    nadi_present = breakdown["nadi"]["score"] == 0.0
    nadi_cancel: list[str] = []
    if nadi_present:
        if bs == gs and bn != gn:
            nadi_cancel.append("Same Moon sign but different nakshatra")
        if bn == gn and boy.pada != girl.pada:
            nadi_cancel.append("Same nakshatra but different pada")
        if bn == gn and bs != gs:
            nadi_cancel.append("Same nakshatra but different Moon sign")
        if same_lord:
            nadi_cancel.append("Both Moon signs are ruled by the same planet")
    out["nadi"] = _dosha(
        nadi_present, nadi_cancel, severity="high",
        note="Same Nadi: classically associated with health and progeny concerns.",
    )

    # Bhakoot dosha
    bh_present = breakdown["bhakut"]["score"] == 0.0
    bh_cancel: list[str] = []
    if bh_present:
        if same_lord:
            bh_cancel.append("Both Moon signs are ruled by the same planet")
        elif gm_score >= 5.0:
            bh_cancel.append("The Moon-sign lords are mutual friends")
    out["bhakoot"] = _dosha(
        bh_present, bh_cancel, severity="high",
        note=f"Moon signs are {breakdown['bhakut']['relation']} apart: "
             "classically linked to emotional friction and financial strain.",
    )

    # Gana dosha
    gana_present = breakdown["gana"]["score"] <= 1.0
    gana_cancel: list[str] = []
    if gana_present:
        if bs == gs:
            gana_cancel.append("Same Moon sign")
        if gm_score >= 4.0:
            gana_cancel.append("The Moon-sign lords are friendly")
        if NAKSHATRA_LORDS[bn] == NAKSHATRA_LORDS[gn]:
            gana_cancel.append("Both nakshatras share the same ruling planet")
    out["gana"] = _dosha(
        gana_present, gana_cancel, severity="medium",
        note="Differing temperaments (Gana): classically linked to ego clashes.",
    )
    return out


def _dosha(present: bool, cancellations: list[str], severity: str, note: str) -> dict:
    return {
        "present": present,
        "cancelled": present and bool(cancellations),
        "cancellation_reasons": cancellations,
        "severity": severity if present and not cancellations else ("none" if not present else "reduced"),
        "note": note if present else "",
    }


# ── Additional checks used in detailed reports ────────────────────────────────

def rajju_group(nak_index: int) -> str:
    n = nak_index + 1
    return next(name for name, members in _RAJJU.items() if n in members)


def additional_checks(boy: MoonPlacement, girl: MoonPlacement) -> dict:
    bn, gn = boy.nak_index, girl.nak_index
    bg, gg = rajju_group(bn), rajju_group(gn)
    rajju_present = bg == gg and bn != gn
    count_from_girl = _count_from(gn, bn)
    return {
        "rajju": {
            "present": rajju_present,
            "boy_group": bg, "girl_group": gg,
            "note": f"Both stars fall in the {bg} Rajju, {_RAJJU_MEANING[bg]}." if rajju_present else "",
        },
        "vedha": {
            "present": (bn + 1) + (gn + 1) in _VEDHA_SUMS,
            "note": "The two nakshatras form a Vedha (mutual obstruction) pair."
            if (bn + 1) + (gn + 1) in _VEDHA_SUMS else "",
        },
        "mahendra": {"favourable": count_from_girl in _MAHENDRA_COUNTS},
        "stree_dheerga": {"favourable": count_from_girl > 13, "count": count_from_girl},
    }


def nakshatra_name(index: int) -> str:
    return NAKSHATRAS[index % 27]
