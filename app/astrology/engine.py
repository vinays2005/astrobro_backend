"""
Deterministic Vedic astrology engine using Swiss Ephemeris (pyswisseph).

CRITICAL: This module only calculates. The LLM NEVER touches this output
directly — it reasons over the structured data produced here.
"""
from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import swisseph as swe

from app.astrology.constants import (
    COMBUSTION_ORBS,
    DASHA_SEQUENCE,
    DASHA_YEARS,
    DEBILITATION,
    EXALTATION,
    MOOLATRIKONA,
    NAKSHATRA_LORDS,
    NAKSHATRAS,
    NATURAL_ENEMIES,
    NATURAL_FRIENDS,
    SIGN_LORDS,
    SIGNS,
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PlanetaryPosition:
    name: str
    longitude: float        # sidereal 0–360
    sign: str
    sign_degree: float      # 0–30 within sign
    house: int              # 1–12
    nakshatra: str
    nakshatra_pada: int     # 1–4
    nakshatra_lord: str
    retrograde: bool
    combust: bool
    dignity: str            # exalted | debilitated | moolatrikona | own | friendly | neutral | enemy
    dignity_score: float    # -1.0 … 1.0


@dataclass
class HouseInfo:
    number: int
    sign: str
    lord: str
    occupants: list[str] = field(default_factory=list)


@dataclass
class DashaPeriod:
    lord: str
    level: str              # mahadasha | antardasha
    start: datetime
    end: datetime
    duration_years: float


@dataclass
class NakshatraInfo:
    name: str
    pada: int
    lord: str
    index: int


@dataclass
class NavamshaPosition:
    planet: str
    sign: str
    sign_index: int
    dignity: str


@dataclass
class Chart:
    """Complete natal chart — the single source of astrological truth."""
    birth_datetime: datetime
    latitude: float
    longitude: float
    timezone: str
    julian_day: float
    ayanamsa_value: float
    ascendant: dict[str, object]
    planets: dict[str, PlanetaryPosition]
    houses: list[HouseInfo]
    nakshatra_moon: NakshatraInfo
    yogas: list[dict[str, object]]
    dasha_sequence: list[DashaPeriod]
    current_dasha: dict[str, object]
    # Extended fields (added in v2)
    doshas: dict[str, object] = field(default_factory=dict)
    navamsha: dict[str, NavamshaPosition] = field(default_factory=dict)
    d10: dict[str, NavamshaPosition] = field(default_factory=dict)
    aspects: dict[str, list[str]] = field(default_factory=dict)
    functional_nature: dict[str, str] = field(default_factory=dict)


# ── Engine ────────────────────────────────────────────────────────────────────

class AstrologyEngine:
    """
    Pure-calculation engine. Every method is deterministic.

    Usage:
        engine = AstrologyEngine()
        chart = engine.calculate_chart(
            dt=datetime(1990, 8, 15, 14, 30),
            lat=19.0760, lon=72.8777, tz="Asia/Kolkata"
        )
    """

    _BODY_MAP: dict[str, int] = {
        "Sun": swe.SUN, "Moon": swe.MOON, "Mars": swe.MARS,
        "Mercury": swe.MERCURY, "Jupiter": swe.JUPITER,
        "Venus": swe.VENUS, "Saturn": swe.SATURN,
        "Rahu": swe.TRUE_NODE,
    }

    def __init__(self, ayanamsa: str = "LAHIRI") -> None:
        self.ayanamsa = ayanamsa
        _AYANAMSA_MAP = {
            "LAHIRI": swe.SIDM_LAHIRI,
            "KRISHNAMURTI": swe.SIDM_KRISHNAMURTI,
            "RAMAN": swe.SIDM_RAMAN,
        }
        swe.set_sid_mode(_AYANAMSA_MAP.get(ayanamsa, swe.SIDM_LAHIRI))

    # ── Public API ────────────────────────────────────────────

    def calculate_chart(
        self,
        dt: datetime,
        lat: float,
        lon: float,
        tz: str = "UTC",
    ) -> Chart:
        """Full natal chart. Use this as the ONLY source of chart data."""
        jd = self._to_julian_day(dt, tz)
        ayanamsa_val = swe.get_ayanamsa_ut(jd)
        asc = self._calculate_ascendant(jd, lat, lon)
        planets = self._calculate_planets(jd, asc["sign_index"])  # type: ignore[arg-type]
        houses = self._calculate_houses(asc["sign_index"], planets)  # type: ignore[arg-type]
        moon_nak = self._nakshatra_info(planets["Moon"].longitude)
        yogas = self._detect_yogas(planets, houses, asc)
        dasha_seq = self._calculate_vimshottari(planets["Moon"].longitude, dt)
        current = self._current_dasha(dasha_seq, datetime.utcnow())

        doshas = self._detect_doshas(planets, houses)
        navamsha = self._calculate_divisional(planets, 9)
        d10 = self._calculate_divisional(planets, 10)
        aspects = self._special_aspects(planets)
        func_nature = self._functional_nature(asc["sign_index"])  # type: ignore[arg-type]

        return Chart(
            birth_datetime=dt,
            latitude=lat,
            longitude=lon,
            timezone=tz,
            julian_day=jd,
            ayanamsa_value=ayanamsa_val,
            ascendant=asc,
            planets=planets,
            houses=houses,
            nakshatra_moon=moon_nak,
            yogas=yogas,
            dasha_sequence=dasha_seq,
            current_dasha=current,
            doshas=doshas,
            navamsha=navamsha,
            d10=d10,
            aspects=aspects,
            functional_nature=func_nature,
        )

    def calculate_transits(self, jd: float, natal_chart: Chart) -> dict[str, PlanetaryPosition]:
        """Transit planetary positions at a given Julian day."""
        return self._calculate_planets(jd, natal_chart.ascendant["sign_index"])  # type: ignore[arg-type]

    # ── Internal ──────────────────────────────────────────────

    def _to_julian_day(self, dt: datetime, tz: str) -> float:
        try:
            tzinfo = zoneinfo.ZoneInfo(tz)
        except Exception:
            tzinfo = zoneinfo.ZoneInfo("UTC")
        dt_utc = dt.replace(tzinfo=tzinfo).astimezone(zoneinfo.ZoneInfo("UTC"))
        hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
        return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)

    def _calculate_ascendant(self, jd: float, lat: float, lon: float) -> dict[str, object]:
        _cusps, ascmc = swe.houses_ex(jd, lat, lon, b"W", swe.FLG_SIDEREAL)
        asc_lon: float = ascmc[0]
        sign_idx = int(asc_lon / 30) % 12
        nak = self._nakshatra_info(asc_lon)
        return {
            "longitude": asc_lon,
            "sign": SIGNS[sign_idx],
            "sign_index": sign_idx,
            "degree": round(asc_lon % 30, 4),
            "nakshatra": nak.name,
            "lord": SIGN_LORDS[sign_idx],
        }

    def _calculate_planets(
        self, jd: float, asc_sign_idx: int
    ) -> dict[str, PlanetaryPosition]:
        flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL | swe.FLG_SPEED
        result: dict[str, PlanetaryPosition] = {}

        for name, body in self._BODY_MAP.items():
            try:
                pos, _ = swe.calc_ut(jd, body, flags)
            except Exception:
                continue  # skip if ephemeris data missing; caller sees absent key
            lon: float = pos[0]
            speed: float = pos[3]
            sign_idx = int(lon / 30) % 12
            house = self._house_from_sign(sign_idx, asc_sign_idx)
            nak = self._nakshatra_info(lon)
            retrograde = speed < 0 and name not in ("Sun", "Moon")
            dignity, dignity_score = self._dignity(name, sign_idx, lon)
            combust = self._is_combust(name, lon, result)

            result[name] = PlanetaryPosition(
                name=name,
                longitude=lon,
                sign=SIGNS[sign_idx],
                sign_degree=round(lon % 30, 4),
                house=house,
                nakshatra=nak.name,
                nakshatra_pada=nak.pada,
                nakshatra_lord=nak.lord,
                retrograde=retrograde,
                combust=combust,
                dignity=dignity,
                dignity_score=dignity_score,
            )

        # Ketu = Rahu + 180°
        if "Rahu" in result:
            rahu = result["Rahu"]
            ketu_lon = (rahu.longitude + 180.0) % 360.0
            sign_idx = int(ketu_lon / 30) % 12
            nak = self._nakshatra_info(ketu_lon)
            result["Ketu"] = PlanetaryPosition(
                name="Ketu",
                longitude=ketu_lon,
                sign=SIGNS[sign_idx],
                sign_degree=round(ketu_lon % 30, 4),
                house=self._house_from_sign(sign_idx, asc_sign_idx),
                nakshatra=nak.name,
                nakshatra_pada=nak.pada,
                nakshatra_lord=nak.lord,
                retrograde=True,
                combust=False,
                dignity="neutral",
                dignity_score=0.0,
            )

        return result

    def _calculate_houses(
        self, asc_sign_idx: int, planets: dict[str, PlanetaryPosition]
    ) -> list[HouseInfo]:
        houses: list[HouseInfo] = []
        for i in range(12):
            sign_idx = (asc_sign_idx + i) % 12
            occupants = [p.name for p in planets.values() if p.house == i + 1]
            houses.append(HouseInfo(
                number=i + 1,
                sign=SIGNS[sign_idx],
                lord=SIGN_LORDS[sign_idx],
                occupants=occupants,
            ))
        return houses

    def _house_from_sign(self, sign_idx: int, asc_sign_idx: int) -> int:
        return ((sign_idx - asc_sign_idx) % 12) + 1

    def _nakshatra_info(self, longitude: float) -> NakshatraInfo:
        nak_size = 360.0 / 27.0
        idx = int(longitude / nak_size) % 27
        degree_in_nak = longitude % nak_size
        pada = int(degree_in_nak / (nak_size / 4)) + 1
        return NakshatraInfo(
            name=NAKSHATRAS[idx],
            pada=pada,
            lord=NAKSHATRA_LORDS[idx],
            index=idx,
        )

    def _dignity(self, name: str, sign_idx: int, lon: float) -> tuple[str, float]:
        if name in EXALTATION and EXALTATION[name]["sign"] == sign_idx:
            return "exalted", 1.0
        if name in DEBILITATION and DEBILITATION[name]["sign"] == sign_idx:
            return "debilitated", -1.0
        if name in MOOLATRIKONA:
            mt = MOOLATRIKONA[name]
            deg = lon % 30
            if mt["sign"] == sign_idx and mt["start"] <= deg <= mt["end"]:
                return "moolatrikona", 0.8
        if SIGN_LORDS[sign_idx] == name:
            return "own", 0.6
        sign_lord = SIGN_LORDS[sign_idx]
        return self._relationship(name, sign_lord), 0.0

    def _relationship(self, planet: str, sign_lord: str) -> str:
        if planet == sign_lord:
            return "own"
        if sign_lord in NATURAL_FRIENDS.get(planet, []):
            return "friendly"
        if sign_lord in NATURAL_ENEMIES.get(planet, []):
            return "enemy"
        return "neutral"

    def _is_combust(
        self, name: str, lon: float, existing: dict[str, PlanetaryPosition]
    ) -> bool:
        if name in ("Sun", "Rahu", "Ketu"):
            return False
        if "Sun" not in existing:
            return False
        sun_lon = existing["Sun"].longitude
        diff = abs(lon - sun_lon) % 360
        if diff > 180:
            diff = 360 - diff
        orb = COMBUSTION_ORBS.get(name, 0.0)
        return diff <= orb

    def _calculate_vimshottari(
        self, moon_lon: float, birth_dt: datetime
    ) -> list[DashaPeriod]:
        nak_size = 360.0 / 27.0
        nak_idx = int(moon_lon / nak_size) % 27
        lord_idx = nak_idx % 9
        fraction_elapsed = (moon_lon % nak_size) / nak_size

        periods: list[DashaPeriod] = []
        current = birth_dt

        # Balance of first mahadasha
        first_lord = DASHA_SEQUENCE[lord_idx]
        first_years = DASHA_YEARS[first_lord] * (1 - fraction_elapsed)
        end = current + timedelta(days=first_years * 365.25)
        periods.append(DashaPeriod(
            lord=first_lord, level="mahadasha",
            start=current, end=end,
            duration_years=round(first_years, 4),
        ))
        current = end

        for i in range(1, 9):
            lord = DASHA_SEQUENCE[(lord_idx + i) % 9]
            years = DASHA_YEARS[lord]
            end = current + timedelta(days=years * 365.25)
            periods.append(DashaPeriod(
                lord=lord, level="mahadasha",
                start=current, end=end,
                duration_years=float(years),
            ))
            current = end

        return periods

    def _current_dasha(
        self, periods: list[DashaPeriod], target: datetime
    ) -> dict[str, object]:
        current_md: DashaPeriod | None = None
        for p in periods:
            if p.start <= target <= p.end:
                current_md = p
                break

        if current_md is None:
            return {"mahadasha": None, "antardasha": None}

        # Antardasha within mahadasha
        md_days = (current_md.end - current_md.start).days
        elapsed_ratio = (target - current_md.start).days / md_days
        md_lord_idx = DASHA_SEQUENCE.index(current_md.lord)
        ad_lord: str | None = None
        ad_start: datetime | None = None
        ad_end: datetime | None = None
        cumulative = 0.0

        for i in range(9):
            lord = DASHA_SEQUENCE[(md_lord_idx + i) % 9]
            frac = DASHA_YEARS[lord] / 120.0
            if cumulative <= elapsed_ratio < cumulative + frac:
                ad_lord = lord
                ad_start = current_md.start + timedelta(days=cumulative * md_days)
                ad_end = ad_start + timedelta(days=frac * md_days)
                break
            cumulative += frac

        # Pratyantardasha within antardasha
        pd_lord: str | None = None
        pd_start: datetime | None = None
        pd_end: datetime | None = None
        if ad_lord is not None and ad_start is not None and ad_end is not None:
            ad_days = (ad_end - ad_start).days
            elapsed_ad = (target - ad_start).days
            ad_lord_idx = DASHA_SEQUENCE.index(ad_lord)
            cumulative_pd = 0.0
            for i in range(9):
                lord_pd = DASHA_SEQUENCE[(ad_lord_idx + i) % 9]
                frac_pd = DASHA_YEARS[lord_pd] / 120.0
                if cumulative_pd * ad_days <= elapsed_ad < (cumulative_pd + frac_pd) * ad_days:
                    pd_lord = lord_pd
                    pd_start = ad_start + timedelta(days=cumulative_pd * ad_days)
                    pd_end = ad_start + timedelta(days=(cumulative_pd + frac_pd) * ad_days)
                    break
                cumulative_pd += frac_pd

        return {
            "mahadasha": {
                "lord": current_md.lord,
                "start": current_md.start.isoformat(),
                "end": current_md.end.isoformat(),
            },
            "antardasha": {
                "lord": ad_lord,
                "start": ad_start.isoformat() if ad_start is not None else None,
                "end": ad_end.isoformat() if ad_end is not None else None,
            } if ad_lord is not None else None,
            "pratyantardasha": {
                "lord": pd_lord,
                "start": pd_start.isoformat() if pd_start is not None else None,
                "end": pd_end.isoformat() if pd_end is not None else None,
            } if pd_lord is not None else None,
        }

    def _detect_yogas(
        self,
        planets: dict[str, PlanetaryPosition],
        houses: list[HouseInfo],
        asc: dict[str, object],
    ) -> list[dict[str, object]]:
        yogas: list[dict[str, object]] = []

        def sign_of(p: str) -> int:
            return int(planets[p].longitude / 30) % 12

        # ── Gajakesari: Jupiter in kendra from Moon ───────────────
        if "Jupiter" in planets and "Moon" in planets:
            diff = (sign_of("Jupiter") - sign_of("Moon")) % 12
            if diff in (0, 3, 6, 9):
                yogas.append({"name": "Gajakesari Yoga",
                    "description": "Jupiter in kendra from Moon — wisdom, reputation, fame",
                    "strength": 0.7, "planets": ["Jupiter", "Moon"]})

        # ── Budhaditya: Sun + Mercury conjunct ────────────────────
        if "Sun" in planets and "Mercury" in planets:
            if sign_of("Sun") == sign_of("Mercury"):
                yogas.append({"name": "Budhaditya Yoga",
                    "description": "Sun and Mercury in same sign — sharp intellect, clear communication",
                    "strength": 0.65, "planets": ["Sun", "Mercury"]})

        # ── Pancha Mahapurusha (5 great-man yogas) ────────────────
        for planet, yoga_name, desc in [
            ("Jupiter", "Hamsa Yoga", "Jupiter exalted/own in kendra — grace, wisdom, dharma"),
            ("Venus",   "Malavya Yoga", "Venus exalted/own in kendra — beauty, luxury, arts"),
            ("Mars",    "Ruchaka Yoga", "Mars exalted/own in kendra — courage, leadership, military"),
            ("Mercury", "Bhadra Yoga",  "Mercury exalted/own in kendra — intelligence, business, eloquence"),
            ("Saturn",  "Sasha Yoga",   "Saturn exalted/own in kendra — discipline, longevity, authority"),
        ]:
            if planet in planets:
                p = planets[planet]
                if p.dignity in ("own", "exalted", "moolatrikona") and p.house in (1, 4, 7, 10):
                    yogas.append({"name": yoga_name, "description": desc,
                        "strength": 0.85, "planets": [planet]})

        # ── Viparita Raja Yoga: dusthana lord in dusthana ─────────
        dusthana = {6, 8, 12}
        for h in dusthana:
            lord = houses[h - 1].lord
            if lord in planets and planets[lord].house in dusthana and planets[lord].house != h:
                yogas.append({"name": "Viparita Raja Yoga",
                    "description": f"{lord} (lord of {h}H) in another dusthana — victory through adversity",
                    "strength": 0.7, "planets": [lord]})
                break

        # ── Neechabhanga Raja Yoga: debilitated planet cancelled ──
        for pname, ppos in planets.items():
            if ppos.dignity == "debilitated":
                # Cancellation: lord of sign occupied by debilitated planet is in kendra from Lagna/Moon
                deb_sign_lord = SIGN_LORDS[int(ppos.longitude / 30) % 12]
                if deb_sign_lord in planets and planets[deb_sign_lord].house in (1, 4, 7, 10):
                    yogas.append({"name": "Neechabhanga Raja Yoga",
                        "description": f"{pname} debilitation cancelled by {deb_sign_lord} in kendra — rise after struggle",
                        "strength": 0.75, "planets": [pname, deb_sign_lord]})

        # ── Dhana Yoga: 2nd + 11th lords conjunct or exchange ─────
        lord2 = houses[1].lord
        lord11 = houses[10].lord
        if lord2 in planets and lord11 in planets:
            if sign_of(lord2) == sign_of(lord11):
                yogas.append({"name": "Dhana Yoga",
                    "description": "2nd and 11th lords conjunct — wealth accumulation, prosperity",
                    "strength": 0.7, "planets": [lord2, lord11]})
            # Exchange: lord2 in 11th house and lord11 in 2nd house
            elif planets[lord2].house == 11 and planets[lord11].house == 2:
                yogas.append({"name": "Dhana Yoga (Exchange)",
                    "description": "2nd and 11th lords in exchange (Parivartana) — strong wealth yoga",
                    "strength": 0.8, "planets": [lord2, lord11]})

        # ── Saraswati Yoga: Jupiter + Venus + Mercury in kendra/trikona ──
        if all(p in planets for p in ("Jupiter", "Venus", "Mercury")):
            good_houses = {1, 2, 4, 5, 7, 9, 10}
            if all(planets[p].house in good_houses for p in ("Jupiter", "Venus", "Mercury")):
                yogas.append({"name": "Saraswati Yoga",
                    "description": "Jupiter, Venus, Mercury in kendra/trikona — brilliance, arts, scholarship",
                    "strength": 0.8, "planets": ["Jupiter", "Venus", "Mercury"]})

        # ── Kemadruma Yoga: Moon with no planets in adjacent signs ─
        if "Moon" in planets:
            moon_sign = sign_of("Moon")
            prev_sign = (moon_sign - 1) % 12
            next_sign = (moon_sign + 1) % 12
            planet_signs = {sign_of(p) for p in planets if p not in ("Moon", "Rahu", "Ketu")}
            if moon_sign not in planet_signs and prev_sign not in planet_signs and next_sign not in planet_signs:
                yogas.append({"name": "Kemadruma Yoga",
                    "description": "Moon isolated — emotional struggles, instability; strong chart may cancel",
                    "strength": 0.4, "planets": ["Moon"]})

        # ── Chandra Adhi Yoga: benefics in 6/7/8 from Moon ────────
        if "Moon" in planets:
            moon_h = planets["Moon"].house
            benefic_positions = [sign_of(p) for p in ("Jupiter", "Venus", "Mercury") if p in planets]
            adhi_positions = []
            for bp in ("Jupiter", "Venus", "Mercury"):
                if bp in planets:
                    rel_house = (planets[bp].house - moon_h) % 12 + 1
                    if rel_house in (6, 7, 8):
                        adhi_positions.append(bp)
            if len(adhi_positions) >= 2:
                yogas.append({"name": "Chandra Adhi Yoga",
                    "description": f"Benefics ({', '.join(adhi_positions)}) in 6/7/8 from Moon — ministership, leadership",
                    "strength": 0.75, "planets": adhi_positions})

        # ── Sunapha/Anapha: planet in 2nd/12th from Moon ──────────
        if "Moon" in planets:
            moon_sign = sign_of("Moon")
            for pname in ("Mars", "Mercury", "Jupiter", "Venus", "Saturn"):
                if pname not in planets:
                    continue
                ps = sign_of(pname)
                if (ps - moon_sign) % 12 == 1:
                    yogas.append({"name": f"Sunapha Yoga ({pname})",
                        "description": f"{pname} in 2nd from Moon — wealth, good reputation",
                        "strength": 0.6, "planets": ["Moon", pname]})
                elif (moon_sign - ps) % 12 == 1:
                    yogas.append({"name": f"Anapha Yoga ({pname})",
                        "description": f"{pname} in 12th from Moon — renunciation, health, generosity",
                        "strength": 0.6, "planets": ["Moon", pname]})

        # ── Dharma-Karmadhipati Yoga: 9th + 10th lords conjunct ───
        lord9 = houses[8].lord
        lord10 = houses[9].lord
        if lord9 != lord10 and lord9 in planets and lord10 in planets:
            if sign_of(lord9) == sign_of(lord10):
                yogas.append({"name": "Dharma-Karmadhipati Yoga",
                    "description": "9th and 10th lords conjunct — career aligned with dharma, recognition",
                    "strength": 0.8, "planets": [lord9, lord10]})

        # ── Lakshmi Yoga: 9th lord exalted/own in kendra/trikona ──
        lord9 = houses[8].lord
        if lord9 in planets:
            p9 = planets[lord9]
            if p9.dignity in ("own", "exalted", "moolatrikona") and p9.house in (1, 4, 5, 7, 9, 10):
                yogas.append({"name": "Lakshmi Yoga",
                    "description": "9th lord strong in kendra/trikona — prosperity, luck, goddess's grace",
                    "strength": 0.8, "planets": [lord9]})

        # ── Raja Yoga: kendra + trikona lord mutual relationship ──
        kendra_lords = {houses[i - 1].lord for i in (1, 4, 7, 10)}
        trikona_lords = {houses[i - 1].lord for i in (1, 5, 9)}
        raja_candidates = kendra_lords & trikona_lords
        for candidate in raja_candidates:
            if candidate in planets and planets[candidate].house in (1, 4, 5, 7, 9, 10):
                yogas.append({"name": f"Raja Yoga ({candidate})",
                    "description": f"{candidate} rules both kendra and trikona — power, authority, status",
                    "strength": 0.75, "planets": [candidate]})
                break
        # Also: kendra lord + trikona lord in mutual conjunction
        for kl in kendra_lords:
            for tl in trikona_lords:
                if kl != tl and kl in planets and tl in planets:
                    if sign_of(kl) == sign_of(tl):
                        yogas.append({"name": f"Raja Yoga ({kl}-{tl} conjunction)",
                            "description": f"{kl} (kendra lord) conjunct {tl} (trikona lord) — raja yoga from conjunction",
                            "strength": 0.7, "planets": [kl, tl]})

        # Deduplicate by name (keep highest strength)
        seen: dict[str, dict[str, object]] = {}
        for y in yogas:
            name = str(y["name"])
            if name not in seen or float(y["strength"]) > float(seen[name]["strength"]):  # type: ignore[arg-type]
                seen[name] = y
        return list(seen.values())

    # ── Dosha detection ───────────────────────────────────────

    def _detect_doshas(
        self,
        planets: dict[str, PlanetaryPosition],
        houses: list[HouseInfo],
    ) -> dict[str, object]:
        doshas: dict[str, object] = {}

        # Manglik Dosha
        if "Mars" in planets:
            mars_house = planets["Mars"].house
            is_manglik = mars_house in (1, 2, 4, 7, 8, 12)
            doshas["manglik"] = {
                "present": is_manglik,
                "mars_house": mars_house,
                "description": (
                    f"Mars in {mars_house}H — Manglik Dosha present. "
                    "Delay in marriage, possible conflicts; matching chart recommended."
                ) if is_manglik else "No Manglik Dosha — Mars not in 1/2/4/7/8/12.",
                "severity": "high" if mars_house in (7, 8) else "moderate" if is_manglik else "none",
            }

        # Kalsarpa Dosha
        if "Rahu" in planets and "Ketu" in planets:
            rahu_lon = planets["Rahu"].longitude
            ketu_lon = planets["Ketu"].longitude
            seven_planets = [p for p in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn")
                             if p in planets]
            # Clockwise from Rahu to Ketu
            def in_rahu_ketu_arc(lon: float) -> bool:
                arc = (ketu_lon - rahu_lon) % 360
                diff = (lon - rahu_lon) % 360
                return diff < arc

            all_in_arc = all(in_rahu_ketu_arc(planets[p].longitude) for p in seven_planets)
            all_outside = all(not in_rahu_ketu_arc(planets[p].longitude) for p in seven_planets)
            has_kalsarpa = all_in_arc or all_outside
            in_count = sum(1 for p in seven_planets if in_rahu_ketu_arc(planets[p].longitude))
            partial = not has_kalsarpa and (in_count >= 5)

            doshas["kalsarpa"] = {
                "present": has_kalsarpa,
                "partial": partial,
                "rahu_house": planets["Rahu"].house,
                "ketu_house": planets["Ketu"].house,
                "description": (
                    f"Kalsarpa Dosha — all planets between Rahu ({planets['Rahu'].sign}) "
                    f"and Ketu ({planets['Ketu'].sign}). Obstacles, delays, spiritual intensity."
                ) if has_kalsarpa else (
                    f"Partial Kalsarpa ({in_count}/7 planets in Rahu-Ketu arc)."
                ) if partial else "No Kalsarpa Dosha.",
            }

        # Sade Sati (based on current transit Saturn vs natal Moon)
        if "Saturn" in planets and "Moon" in planets:
            natal_moon_sign = int(planets["Moon"].longitude / 30) % 12
            # Get current transit Saturn position
            current_jd = swe.julday(
                datetime.utcnow().year, datetime.utcnow().month,
                datetime.utcnow().day, datetime.utcnow().hour + datetime.utcnow().minute / 60.0
            )
            try:
                flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
                sat_pos, _ = swe.calc_ut(current_jd, swe.SATURN, flags)
                transit_saturn_sign = int(sat_pos[0] / 30) % 12
                offset = (transit_saturn_sign - natal_moon_sign) % 12
                in_sade_sati = offset in (11, 0, 1)
                phase = {11: "rising", 0: "peak", 1: "setting"}.get(offset, "none")
                doshas["sade_sati"] = {
                    "present": in_sade_sati,
                    "phase": phase,
                    "natal_moon_sign": SIGNS[natal_moon_sign],
                    "transit_saturn_sign": SIGNS[transit_saturn_sign],
                    "description": (
                        f"Sade Sati — {phase.capitalize()} phase. Saturn transiting "
                        f"{SIGNS[transit_saturn_sign]} over natal Moon in {SIGNS[natal_moon_sign]}. "
                        "7.5 years of Saturn influence — testing, discipline, transformation."
                    ) if in_sade_sati else (
                        f"No Sade Sati. Saturn in {SIGNS[transit_saturn_sign]}, "
                        f"natal Moon in {SIGNS[natal_moon_sign]}."
                    ),
                }
            except Exception:
                doshas["sade_sati"] = {"present": False, "phase": "unknown"}

        return doshas

    # ── Divisional charts (D9 Navamsha, D10 Dashamsha) ───────

    def _calculate_divisional(
        self, planets: dict[str, PlanetaryPosition], division: int
    ) -> dict[str, NavamshaPosition]:
        result: dict[str, NavamshaPosition] = {}

        # Navamsha (D9): starting sign by triplicity element
        D9_START = {0: 0, 1: 9, 2: 6, 3: 3,   # Aries/Taurus/Gemini/Cancer...
                    4: 0, 5: 9, 6: 6, 7: 3,
                    8: 0, 9: 9, 10: 6, 11: 3}
        # D10: odd signs start from own sign; even signs start from 9th from it
        D10_START = {i: i if i % 2 == 0 else (i + 8) % 12 for i in range(12)}

        for pname, ppos in planets.items():
            lon = ppos.longitude
            sign_idx = int(lon / 30) % 12
            deg_in_sign = lon % 30
            within = int(deg_in_sign / (30.0 / division))

            if division == 9:
                start = D9_START[sign_idx]
                div_sign = (start + within) % 12
            elif division == 10:
                start = D10_START[sign_idx]
                div_sign = (start + within) % 12
            else:
                div_sign = (sign_idx * division + within) % 12

            dignity, _ = self._dignity(pname, div_sign, div_sign * 30.0)
            result[pname] = NavamshaPosition(
                planet=pname,
                sign=SIGNS[div_sign],
                sign_index=div_sign,
                dignity=dignity,
            )
        return result

    # ── Special planetary aspects (Drishti) ──────────────────

    def _special_aspects(
        self, planets: dict[str, PlanetaryPosition]
    ) -> dict[str, list[str]]:
        """Returns {planet: [list of houses it aspects]}."""
        special: dict[str, list[int]] = {
            "Mars":    [4, 7, 8],   # 4th, 7th, 8th from itself
            "Jupiter": [5, 7, 9],
            "Saturn":  [3, 7, 10],
        }
        result: dict[str, list[str]] = {}
        for pname, ppos in planets.items():
            aspected_houses: list[str] = []
            base_house = ppos.house
            aspect_offsets = special.get(pname, [7])
            for offset in aspect_offsets:
                aspected = ((base_house - 1 + offset - 1) % 12) + 1
                aspected_houses.append(str(aspected))
            result[pname] = aspected_houses
        return result

    # ── Functional nature by lagna ────────────────────────────

    def _functional_nature(self, asc_sign_idx: int) -> dict[str, str]:
        """Classify each planet as benefic/malefic/yogakaraka/neutral for this lagna."""
        # House rulership: planet rules house whose sign_index matches
        # Trikona: 1, 5, 9 → sign indices: asc, asc+4, asc+8
        trikona = {(asc_sign_idx + i) % 12 for i in (0, 4, 8)}
        kendra  = {(asc_sign_idx + i) % 12 for i in (0, 3, 6, 9)}
        dusthana = {(asc_sign_idx + i) % 12 for i in (2, 5, 7, 11)}

        result: dict[str, str] = {}
        for planet in ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"):
            ruled_signs: list[int] = [i for i, lord in enumerate(SIGN_LORDS) if lord == planet]
            is_trikona = any(s in trikona for s in ruled_signs)
            is_kendra  = any(s in kendra for s in ruled_signs)
            is_dusthana = any(s in dusthana for s in ruled_signs)

            if is_trikona and is_kendra:
                result[planet] = "yogakaraka"
            elif is_trikona:
                result[planet] = "benefic"
            elif is_dusthana and not is_trikona and not is_kendra:
                result[planet] = "malefic"
            elif is_kendra and not is_trikona:
                result[planet] = "neutral"
            else:
                result[planet] = "neutral"

        result["Rahu"] = "malefic"
        result["Ketu"] = "malefic"
        return result
