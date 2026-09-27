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
        }

    def _detect_yogas(
        self,
        planets: dict[str, PlanetaryPosition],
        houses: list[HouseInfo],
        asc: dict[str, object],
    ) -> list[dict[str, object]]:
        yogas: list[dict[str, object]] = []

        # Gajakesari: Jupiter in kendra from Moon
        if "Jupiter" in planets and "Moon" in planets:
            jup_sign = int(planets["Jupiter"].longitude / 30) % 12
            moon_sign = int(planets["Moon"].longitude / 30) % 12
            diff = (jup_sign - moon_sign) % 12
            if diff in (0, 3, 6, 9):
                yogas.append({
                    "name": "Gajakesari Yoga",
                    "description": "Jupiter in kendra from Moon — wisdom, reputation, fame",
                    "strength": 0.7,
                    "planets": ["Jupiter", "Moon"],
                })

        # Budhaditya: Sun + Mercury conjunct
        if "Sun" in planets and "Mercury" in planets:
            sun_sign = int(planets["Sun"].longitude / 30)
            merc_sign = int(planets["Mercury"].longitude / 30)
            if sun_sign == merc_sign:
                yogas.append({
                    "name": "Budhaditya Yoga",
                    "description": "Sun and Mercury in same sign — sharp intellect, clear communication",
                    "strength": 0.65,
                    "planets": ["Sun", "Mercury"],
                })

        # Hamsa (Jupiter in own/exalted kendra)
        if "Jupiter" in planets:
            jup = planets["Jupiter"]
            if jup.dignity in ("own", "exalted", "moolatrikona") and jup.house in (1, 4, 7, 10):
                yogas.append({
                    "name": "Hamsa Yoga",
                    "description": "Jupiter exalted/own in kendra — divine grace, righteousness",
                    "strength": 0.85,
                    "planets": ["Jupiter"],
                })

        # Malavya (Venus in own/exalted kendra)
        if "Venus" in planets:
            ven = planets["Venus"]
            if ven.dignity in ("own", "exalted", "moolatrikona") and ven.house in (1, 4, 7, 10):
                yogas.append({
                    "name": "Malavya Yoga",
                    "description": "Venus exalted/own in kendra — beauty, luxury, arts",
                    "strength": 0.8,
                    "planets": ["Venus"],
                })

        # Raja Yoga (simplified): kendra lord + trikona lord
        kendra_lords = {houses[i - 1].lord for i in (1, 4, 7, 10)}
        trikona_lords = {houses[i - 1].lord for i in (1, 5, 9)}
        raja_candidates = kendra_lords & trikona_lords
        for candidate in raja_candidates:
            for p in planets.values():
                if p.name == candidate and p.house in (1, 4, 5, 7, 9, 10):
                    yogas.append({
                        "name": f"Raja Yoga ({candidate})",
                        "description": f"{candidate} rules both kendra and trikona — power, authority",
                        "strength": 0.75,
                        "planets": [candidate],
                    })
                    break

        return yogas
