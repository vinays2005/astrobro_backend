"""Hindu lunar calendar: amanta months (with Adhika), tithi days, festivals and vratas. Lahiri sidereal.

A lunar month runs new moon to new moon and is named after the sign the Sun *enters* during it
(Mesha -> Chaitra, ...). A month with no sankranti is Adhika and takes the name of the following month.
Festival dates use the tithi prevailing at the observance time (sunrise, midday, Pradosh, midnight or
moonrise), so they can differ by a day from regional panchangs that use other rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from app.astrology import ephem as E
from app.astrology.constants import SIGNS

MASA_NAMES = ["Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana", "Bhadrapada",
              "Ashwin", "Kartik", "Margashirsha", "Pausha", "Magha", "Phalguna"]
_TITHI = ["Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami", "Shashthi", "Saptami", "Ashtami",
          "Navami", "Dashami", "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi"]
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_LAT, DEFAULT_LON, DEFAULT_TZ = 28.6139, 77.2090, "Asia/Kolkata"


def tithi_label(n: int) -> tuple[str, str]:
    """(paksha, name) for an absolute tithi 1..30."""
    if n == 15:
        return "Shukla", "Purnima"
    if n == 30:
        return "Krishna", "Amavasya"
    if n < 15:
        return "Shukla", _TITHI[n - 1]
    return "Krishna", _TITHI[n - 16]


# ── Lunar months ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LunarMonth:
    start_jd: float
    end_jd: float
    name: str
    adhika: bool

    @property
    def label(self) -> str:
        return f"Adhika {self.name}" if self.adhika else self.name


@lru_cache(maxsize=16)
def months_for_year(year: int) -> tuple[LunarMonth, ...]:
    """All lunar months overlapping the Gregorian year (plus a margin either side)."""
    jd0 = E.to_jd(datetime(year - 1, 11, 1, tzinfo=timezone.utc))
    jd1 = E.to_jd(datetime(year + 1, 3, 1, tzinfo=timezone.utc))
    moons = E.lunations(jd0, jd1, 0.0)
    out = []
    for a, b in zip(moons, moons[1:]):
        s0 = E.sign_index(E.lon_speed(a, "Sun")[0])
        s1 = E.sign_index(E.lon_speed(b, "Sun")[0])
        adhika = s0 == s1
        out.append(LunarMonth(a, b, MASA_NAMES[(s1 + 1) % 12] if adhika else MASA_NAMES[s1], adhika))
    return tuple(out)


def month_at(jd: float) -> LunarMonth | None:
    year = E.from_jd(jd).year
    for m in months_for_year(year):
        if m.start_jd <= jd < m.end_jd:
            return m
    return None


def masa_info(jd: float) -> dict:
    """Amanta and Purnimanta month names plus paksha for an instant."""
    m = month_at(jd)
    tithi = E.tithi_number(jd)
    paksha = "Shukla" if tithi <= 15 else "Krishna"
    if not m:
        return {"amanta": "", "purnimanta": "", "adhika": False, "paksha": paksha}
    purni = m.name if paksha == "Shukla" else MASA_NAMES[(MASA_NAMES.index(m.name) + 1) % 12]
    return {"amanta": m.name, "purnimanta": purni, "adhika": m.adhika, "paksha": paksha, "label": m.label}


def new_year_start(year: int, tz: str = DEFAULT_TZ) -> date:
    """Chaitra Shukla Pratipada (Hindu new year) in a Gregorian year."""
    for m in months_for_year(year):
        if m.name == "Chaitra" and not m.adhika:
            d = find_tithi_day(m, 1, "sunrise", DEFAULT_LAT, DEFAULT_LON, tz)
            if d and date(year, 3, 1) <= d <= date(year, 5, 5):
                return d
    return date(year, 3, 25)


def hindu_year(d: date, tz: str = DEFAULT_TZ) -> dict:
    after = d >= new_year_start(d.year, tz)
    return {"vikram_samvat": d.year + 57 if after else d.year + 56,
            "shaka_samvat": d.year - 78 if after else d.year - 79}


# ── Observation times and tithi days ──────────────────────────────────────────

@lru_cache(maxsize=8192)
def day_times(d: date, lat: float, lon: float, tz: str) -> dict:
    """Sunrise, sunset and next sunrise (JD). Cached and read-only."""
    mid = E.local_midnight_jd(d, tz)
    sr, ss = E.sun_rise_set(mid, lat, lon)
    sr = sr if sr is not None else mid + 0.25
    ss = ss if ss is not None else mid + 0.75
    nxt_sr = E.sun_rise_set(mid + 1.0, lat, lon)[0] or sr + 1.0
    return {"sunrise": sr, "sunset": ss, "next_sunrise": nxt_sr}


def observe_points(d: date, kind: str, lat: float, lon: float, tz: str) -> list[float]:
    """Instants at which a tithi must prevail for a day to qualify. Windowed kinds return several."""
    t = day_times(d, lat, lon, tz)
    sr, ss, nxt = t["sunrise"], t["sunset"], t["next_sunrise"]
    span = ss - sr
    if kind == "sunrise":
        return [sr]
    if kind == "madhyahna":  # the 3rd fifth of the day
        return [sr + span * f for f in (0.4, 0.5, 0.6)]
    if kind == "aparahna":  # the 4th fifth of the day
        return [sr + span * f for f in (0.6, 0.7, 0.8)]
    if kind == "pradosh":
        return [ss + 1.0 / 24.0]
    if kind == "moonrise":
        return [ss + 3.0 / 24.0]
    if kind == "nishita":  # a window around true midnight; sample where it begins
        return [ss + (nxt - ss) / 2.0 - 20.0 / 1440.0]
    raise ValueError(kind)


def is_vishti(jd: float) -> bool:
    """Bhadra: the Vishti karana (the first half of every Shukla Chaturthi-style cycle position 7)."""
    k = int(E.elongation(jd) / 6.0)
    return 1 <= k <= 56 and (k - 1) % 7 == 6


def _in_month(month: LunarMonth, jd: float) -> bool:
    return month.start_jd <= jd < month.end_jd


def _days_of(month: LunarMonth, tz: str) -> list[date]:
    first = E.jd_to_local(month.start_jd, tz).date() - timedelta(days=1)
    last = E.jd_to_local(month.end_jd, tz).date() + timedelta(days=1)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def find_tithi_day(month: LunarMonth, tithi: int, kind: str, lat: float, lon: float, tz: str) -> date | None:
    """Civil date inside a lunar month on which `tithi` prevails at the observance time.

    Windowed observances need the tithi through the whole window; if no day qualifies the day with
    the tithi at the window's midpoint is used; a kshaya tithi (never present at the instant) is
    observed on the day it begins.
    """
    days = _days_of(month, tz)
    pts = {d: observe_points(d, kind, lat, lon, tz) for d in days}
    inside = [d for d in days if _in_month(month, pts[d][len(pts[d]) // 2])]

    strict = [d for d in inside if all(E.tithi_number(j) == tithi for j in pts[d])]
    if strict:
        return strict[0]
    loose = [d for d in inside if E.tithi_number(pts[d][len(pts[d]) // 2]) == tithi]
    if loose:
        return loose[0]
    # The tithi never prevails at the instant: observe it on the day it covers the most of
    return _day_with_most_overlap(month, tithi, lat, lon, tz)


def tithi_window(month: LunarMonth, tithi: int) -> tuple[float, float] | None:
    """(start_jd, end_jd) of an absolute tithi inside (or just around) a lunar month."""
    lo, hi = month.start_jd - 1.0, month.end_jd + 1.0
    starts = E.lunations(lo, hi, ((tithi - 1) * 12.0) % 360.0)
    if not starts:
        return None
    s = starts[0]
    ends = E.lunations(s, s + 3.0, (tithi * 12.0) % 360.0)
    return (s, ends[0]) if ends else None


def _day_with_most_overlap(month: LunarMonth, tithi: int, lat: float, lon: float, tz: str) -> date | None:
    win = tithi_window(month, tithi)
    if not win:
        return None
    best, best_overlap = None, 0.0
    for d in _days_of(month, tz):
        t0 = day_times(d, lat, lon, tz)
        overlap = min(win[1], t0["next_sunrise"]) - max(win[0], t0["sunrise"])
        if overlap > best_overlap:
            best, best_overlap = d, overlap
    return best


def _vishti_end(jd: float) -> float:
    """JD at which the Vishti (Bhadra) karana running at `jd` ends."""
    k = int(E.elongation(jd) / 6.0)
    target = ((k + 1) * 6.0) % 360.0
    ends = E.lunations(jd, jd + 1.0, target)
    return ends[0] if ends else jd


def find_holika_dahan(month: LunarMonth, lat: float, lon: float, tz: str) -> date | None:
    """Purnima at Pradosh; if Bhadra still runs past midnight that night, the next evening."""
    for d in _days_of(month, tz):
        pr = observe_points(d, "pradosh", lat, lon, tz)[0]
        if not _in_month(month, pr) or E.tithi_number(pr) != 15:
            continue
        if not is_vishti(pr):
            return d
        midnight_end = E.local_midnight_jd(d + timedelta(days=1), tz)
        return d if _vishti_end(pr) <= midnight_end else d + timedelta(days=1)
    return None


def find_raksha_bandhan(month: LunarMonth, lat: float, lon: float, tz: str) -> date | None:
    """Shravana Purnima in the afternoon without Bhadra; otherwise the Purnima morning that follows."""
    days = [d for d in _days_of(month, tz)]
    for d in days:
        pts = observe_points(d, "aparahna", lat, lon, tz)
        mid = pts[len(pts) // 2]
        if _in_month(month, mid) and E.tithi_number(mid) == 15 and not is_vishti(mid):
            return d
    for d in days:
        sr = observe_points(d, "sunrise", lat, lon, tz)[0]
        if _in_month(month, sr) and E.tithi_number(sr) == 15:
            return d
    return None


# ── Catalogue ─────────────────────────────────────────────────────────────────

# key, name, amanta masa, absolute tithi, observation time, note
LUNAR_FESTIVALS: list[tuple[str, str, str, int, str, str]] = [
    ("vasant_panchami", "Vasant Panchami", "Magha", 5, "madhyahna", "Worship of Goddess Saraswati; the start of spring."),
    ("ratha_saptami", "Ratha Saptami", "Magha", 7, "sunrise", "Sun worship."),
    ("maha_shivratri", "Maha Shivratri", "Magha", 29, "nishita", "The great night of Shiva, observed with fasting and night-long worship."),
    ("holi", "Holi (Rangwali)", "Phalguna", 16, "sunrise", "The festival of colours, the day after Holika Dahan."),  # date set from Holika Dahan
    ("ugadi", "Ugadi / Gudi Padwa (Hindu New Year)", "Chaitra", 1, "sunrise", "Chaitra Shukla Pratipada, the Hindu new year."),
    ("ram_navami", "Ram Navami", "Chaitra", 9, "madhyahna", "Birth of Lord Rama."),
    ("hanuman_jayanti", "Hanuman Jayanti", "Chaitra", 15, "sunrise", "Birth of Lord Hanuman."),
    ("akshaya_tritiya", "Akshaya Tritiya", "Vaishakha", 3, "madhyahna", "An enduringly auspicious day for new beginnings."),
    ("buddha_purnima", "Buddha Purnima", "Vaishakha", 15, "sunrise", "Birth of Gautama Buddha."),
    ("rath_yatra", "Jagannath Rath Yatra", "Ashadha", 2, "sunrise", "The chariot festival of Lord Jagannath at Puri."),
    ("guru_purnima", "Guru Purnima", "Ashadha", 15, "sunrise", "Honouring teachers and Veda Vyasa."),
    ("nag_panchami", "Nag Panchami", "Shravana", 5, "madhyahna", "Worship of serpent deities."),
    ("raksha_bandhan", "Raksha Bandhan", "Shravana", 15, "madhyahna", "The festival of the sibling bond."),
    ("janmashtami", "Krishna Janmashtami", "Shravana", 23, "nishita", "Birth of Lord Krishna, observed at midnight."),
    ("ganesh_chaturthi", "Ganesh Chaturthi", "Bhadrapada", 4, "madhyahna", "Birth of Lord Ganesha."),
    ("anant_chaturdashi", "Anant Chaturdashi", "Bhadrapada", 14, "sunrise", "Worship of Lord Vishnu; Ganesh Visarjan."),
    ("mahalaya", "Sarvapitri Amavasya (Mahalaya)", "Bhadrapada", 30, "madhyahna", "Offering to all ancestors; the end of Pitru Paksha."),
    ("navratri_start", "Sharad Navratri begins (Ghatasthapana)", "Ashwin", 1, "sunrise", "Nine nights of worshipping the Goddess begin."),
    ("durga_ashtami", "Durga Ashtami", "Ashwin", 8, "sunrise", "The eighth day of Navratri."),
    ("maha_navami", "Maha Navami", "Ashwin", 9, "sunrise", "The ninth day of Navratri."),
    ("dussehra", "Vijayadashami (Dussehra)", "Ashwin", 10, "aparahna", "Victory of good over evil."),
    ("sharad_purnima", "Sharad Purnima", "Ashwin", 15, "pradosh", "The harvest full moon."),
    ("karwa_chauth", "Karwa Chauth", "Ashwin", 19, "moonrise", "Fast observed for the wellbeing of spouses; broken on moonrise."),
    ("dhanteras", "Dhanteras", "Ashwin", 28, "pradosh", "The first day of Diwali; worship of wealth and Dhanvantari."),
    ("naraka_chaturdashi", "Naraka Chaturdashi (Choti Diwali)", "Ashwin", 29, "sunrise", "The day before Diwali."),
    ("diwali", "Diwali (Lakshmi Puja)", "Ashwin", 30, "pradosh", "The festival of lights; worship of Goddess Lakshmi."),
    ("govardhan_puja", "Govardhan Puja", "Kartik", 1, "sunrise", "The day after Diwali."),
    ("bhai_dooj", "Bhai Dooj", "Kartik", 2, "aparahna", "Sisters pray for their brothers."),
    ("chhath", "Chhath Puja (main day)", "Kartik", 6, "pradosh", "Worship of the Sun and Chhathi Maiya."),
    ("kartik_purnima", "Kartik Purnima (Dev Deepawali)", "Kartik", 15, "pradosh", "A sacred full moon for river baths and lamps."),
]

_EKADASHI = {
    ("Chaitra", "Shukla"): "Kamada", ("Chaitra", "Krishna"): "Papmochani",
    ("Vaishakha", "Shukla"): "Mohini", ("Vaishakha", "Krishna"): "Varuthini",
    ("Jyeshtha", "Shukla"): "Nirjala", ("Jyeshtha", "Krishna"): "Apara",
    ("Ashadha", "Shukla"): "Devshayani", ("Ashadha", "Krishna"): "Yogini",
    ("Shravana", "Shukla"): "Shravana Putrada", ("Shravana", "Krishna"): "Kamika",
    ("Bhadrapada", "Shukla"): "Parivartini", ("Bhadrapada", "Krishna"): "Aja",
    ("Ashwin", "Shukla"): "Papankusha", ("Ashwin", "Krishna"): "Indira",
    ("Kartik", "Shukla"): "Dev Uthani (Prabodhini)", ("Kartik", "Krishna"): "Rama",
    ("Margashirsha", "Shukla"): "Mokshada", ("Margashirsha", "Krishna"): "Utpanna",
    ("Pausha", "Shukla"): "Pausha Putrada", ("Pausha", "Krishna"): "Saphala",
    ("Magha", "Shukla"): "Jaya", ("Magha", "Krishna"): "Shattila",
    ("Phalguna", "Shukla"): "Amalaki", ("Phalguna", "Krishna"): "Vijaya",
}

# key, name, absolute tithi, observation time, note
MONTHLY_VRATAS: list[tuple[str, str, int, str, str]] = [
    ("ekadashi_shukla", "Ekadashi (Shukla)", 11, "sunrise", "Fast dedicated to Lord Vishnu."),
    ("ekadashi_krishna", "Ekadashi (Krishna)", 26, "sunrise", "Fast dedicated to Lord Vishnu."),
    ("pradosh_shukla", "Pradosh Vrat (Shukla)", 13, "pradosh", "Evening worship of Lord Shiva."),
    ("pradosh_krishna", "Pradosh Vrat (Krishna)", 28, "pradosh", "Evening worship of Lord Shiva."),
    ("vinayaka_chaturthi", "Vinayaka Chaturthi", 4, "madhyahna", "Worship of Lord Ganesha."),
    ("sankashti", "Sankashti Chaturthi", 19, "moonrise", "Ganesha fast broken after moonrise."),
    ("masik_shivratri", "Masik Shivratri", 29, "nishita", "Monthly night of Shiva."),
    ("purnima", "Purnima", 15, "pradosh", "Full moon; Satyanarayan puja and charity are customary."),
    ("amavasya", "Amavasya", 30, "madhyahna", "New moon; offerings to ancestors are customary."),
]
SANKRANTI_NAMES = ["Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
                   "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"]
_SANKRANTI_FEST = {0: "Mesha Sankranti (Baisakhi / Vishu / Puthandu)", 9: "Makar Sankranti (Pongal / Uttarayan)"}


def _event(d: date, key: str, name: str, kind: str, masa: str, tithi: int | None, note: str) -> dict:
    out = {"date": d.isoformat(), "weekday": _WEEKDAYS[d.weekday()], "key": key, "name": name,
           "type": kind, "masa": masa, "note": note}
    if tithi:
        paksha, tname = tithi_label(tithi)
        out["tithi"] = f"{paksha} {tname}"
    return out


def events_for_year(year: int, lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON, tz: str = DEFAULT_TZ) -> list[dict]:
    """Every festival, vrata and sankranti in a Gregorian year (location rounded to 0.1 degree, cached)."""
    return [dict(e) for e in _events_for_year(year, round(lat, 1), round(lon, 1), tz)]


@lru_cache(maxsize=32)
def _events_for_year(year: int, lat: float, lon: float, tz: str) -> tuple[dict, ...]:
    lo, hi = date(year, 1, 1), date(year, 12, 31)
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(ev: dict) -> None:
        d = date.fromisoformat(ev["date"])
        if lo <= d <= hi and (ev["key"], ev["date"]) not in seen:
            seen.add((ev["key"], ev["date"]))
            events.append(ev)

    for m in months_for_year(year):
        for key, name, masa, tithi, kind, note in LUNAR_FESTIVALS:
            if m.name == masa and not m.adhika:
                if key == "holi":
                    dahan = find_holika_dahan(m, lat, lon, tz)
                    if dahan:
                        add(_event(dahan, "holika_dahan", "Holika Dahan", "festival", masa, 15, "Bonfire on the eve of Holi."))
                        add(_event(dahan + timedelta(days=1), "holi", name, "festival", masa, 16, note))
                    continue
                d = find_raksha_bandhan(m, lat, lon, tz) if key == "raksha_bandhan" else                     find_tithi_day(m, tithi, kind, lat, lon, tz)
                if d:
                    add(_event(d, key, name, "festival", masa, tithi, note))
        for key, name, tithi, kind, note in MONTHLY_VRATAS:
            d = find_tithi_day(m, tithi, kind, lat, lon, tz)
            if not d:
                continue
            label = name
            if key.startswith("ekadashi"):
                paksha = "Shukla" if tithi <= 15 else "Krishna"
                purni = m.name if paksha == "Shukla" else MASA_NAMES[(MASA_NAMES.index(m.name) + 1) % 12]
                ek = _EKADASHI.get((purni, paksha))
                label = f"{ek} Ekadashi" if ek and not m.adhika else name
            elif key.startswith("pradosh"):
                label = f"{_WEEKDAYS[d.weekday()]} Pradosh Vrat" if d.weekday() in (0, 1, 5) else name
            add(_event(d, f"{key}", label + (" (Adhika masa)" if m.adhika else ""), "vrata", m.label, tithi, note))

    for ev in E.ingresses("Sun", E.to_jd(datetime(year, 1, 1, tzinfo=timezone.utc)) - 2,
                          E.to_jd(datetime(year, 12, 31, 23, 59, tzinfo=timezone.utc)) + 2):
        local = E.jd_to_local(ev["jd"], tz)
        si = ev["to_sign_index"]
        name = _SANKRANTI_FEST.get(si, f"{SANKRANTI_NAMES[si]} Sankranti")
        e = _event(local.date(), f"sankranti_{si}", name, "sankranti", "", None,
                   f"The Sun enters {SIGNS[si]} at {local.strftime('%H:%M')}.")
        e["time"] = local.strftime("%H:%M")
        add(e)

    events.sort(key=lambda e: (e["date"], e["type"]))
    return tuple(events)
