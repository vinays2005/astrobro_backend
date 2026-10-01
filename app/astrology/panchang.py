"""
Real Vedic Panchang calculations using Swiss Ephemeris.

All five limbs (Pancha + Anga):
  Tithi   = (Moon_lon - Sun_lon) % 360 / 12   → 1–30
  Vara    = weekday (Sun=0 … Sat=6)
  Nakshatra = Moon_lon / (360/27)              → 0–26
  Yoga    = (Sun_lon + Moon_lon) / (360/27)    → 0–26
  Karana  = half-tithi                         → 0–10 (11 karanas, 7 movable + 4 fixed)

Plus: Rahu Kaal, Yamagandam, Gulika, Choghadiya, Abhijit Muhurat, sunrise/sunset.

Calculations are deterministic. No LLM involvement.
"""
from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field
from datetime import datetime, timedelta, date

import swisseph as swe

from app.astrology.constants import NAKSHATRAS, SIGNS


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TithiInfo:
    number: int          # 1–30 (15 Shukla + 15 Krishna)
    name: str
    paksha: str          # Shukla | Krishna
    end_time: str        # "HH:MM"


@dataclass
class NakshatraInfo:
    index: int           # 0–26
    name: str
    lord: str
    pada: int            # 1–4
    end_time: str


@dataclass
class YogaInfo:
    index: int
    name: str
    end_time: str
    auspicious: bool


@dataclass
class KaranaInfo:
    name: str
    end_time: str


@dataclass
class SunriseSunset:
    sunrise: str         # "HH:MM"
    sunset: str
    moonrise: str
    moonset: str
    sunrise_jd: float
    sunset_jd: float
    day_duration_hours: float


@dataclass
class Muhurat:
    name: str
    start: str
    end: str
    quality: str         # auspicious | inauspicious | neutral


@dataclass
class PanchangResult:
    date: str
    vara: str            # weekday name
    tithi: TithiInfo
    nakshatra: NakshatraInfo
    yoga: YogaInfo
    karana: KaranaInfo
    sun_moon: SunriseSunset
    rahu_kaal: str
    yamagandam: str
    gulika: str
    abhijit_muhurat: str
    choghadiya: list[Muhurat]
    vikram_samvat: int
    shaka_samvat: int
    masa: str
    ayana: str
    ritu: str


# ── Constants ─────────────────────────────────────────────────────────────────

_TITHI_NAMES = [
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi",
    "Purnima",  # 15 Shukla
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi",
    "Amavasya",  # 15 Krishna
]

_YOGA_NAMES = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana",
    "Atiganda", "Sukarma", "Dhriti", "Shoola", "Ganda", "Vriddhi",
    "Dhruva", "Vyaghata", "Harshana", "Vajra", "Siddhi", "Vyatipata",
    "Variyan", "Parigha", "Shiva", "Siddha", "Sadhya", "Shubha",
    "Shukla", "Brahma", "Indra", "Vaidhriti",
]
# Inauspicious yogas (avoid for auspicious work)
_INAUSPICIOUS_YOGAS = {"Vishkambha", "Atiganda", "Shoola", "Ganda", "Vyaghata",
                       "Vajra", "Vyatipata", "Parigha", "Vaidhriti"}

_KARANA_NAMES = [
    "Bava", "Balava", "Kaulava", "Taitila", "Garaja", "Vanija", "Vishti",
    "Shakuni", "Chatushpada", "Naga", "Kimstughna",
]

_VARA_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_VARA_LORDS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

# Rahu Kaal and Yamagandam by weekday (relative to day start in eighths)
# Index = weekday (Sun=0 … Sat=6)
_RAHU_KAAL_EIGHTH  = [8, 2, 7, 5, 6, 4, 3]   # which eighth of the day
_YAMAGANDAM_EIGHTH = [5, 4, 3, 2, 1, 7, 6]
_GULIKA_EIGHTH     = [6, 5, 4, 3, 2, 1, 7]

_CHOGHADIYA_DAY_ORDER = [
    "Udveg", "Char", "Labh", "Amrit", "Kaal", "Shubh", "Rog", "Udveg",
]  # First slot for Sunday; for other weekdays rotate by vara
_CHOGHADIYA_NIGHT_ORDER = [
    "Shubh", "Amrit", "Char", "Rog", "Kaal", "Labh", "Udveg", "Shubh",
]
_CHOGHADIYA_QUALITY = {
    "Amrit": "auspicious", "Shubh": "auspicious", "Labh": "auspicious",
    "Char": "neutral", "Rog": "inauspicious", "Kaal": "inauspicious",
    "Udveg": "inauspicious",
}
# Choghadiya day-start offset per weekday (0=Sun … 6=Sat)
_CHOGHADIYA_DAY_START = [0, 6, 5, 4, 3, 2, 1]
_CHOGHADIYA_NIGHT_START = [4, 3, 2, 1, 0, 6, 5]

_HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana", "Bhadra",
    "Ashwin", "Kartik", "Margashirsha", "Pausha", "Magha", "Phalguna",
]
_RITUS = ["Vasanta", "Grishma", "Varsha", "Sharad", "Hemanta", "Shishira"]


# ── Engine ────────────────────────────────────────────────────────────────────

class PanchangEngine:
    """Deterministic Vedic Panchang calculator."""

    def __init__(self, ayanamsa: str = "LAHIRI") -> None:
        _AYANAMSA_MAP = {
            "LAHIRI": swe.SIDM_LAHIRI,
            "KRISHNAMURTI": swe.SIDM_KRISHNAMURTI,
            "RAMAN": swe.SIDM_RAMAN,
        }
        swe.set_sid_mode(_AYANAMSA_MAP.get(ayanamsa, swe.SIDM_LAHIRI))

    def calculate(
        self,
        target_date: date,
        lat: float,
        lon: float,
        tz: str = "Asia/Kolkata",
    ) -> PanchangResult:
        tzinfo = self._tzinfo(tz)
        # Julian day for midnight of the target date in local time
        dt_midnight = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tzinfo)
        dt_noon = datetime(target_date.year, target_date.month, target_date.day, 12, 0, 0, tzinfo=tzinfo)
        jd_midnight = self._jd(dt_midnight)
        jd_noon = self._jd(dt_noon)

        sun_moon = self._sunrise_sunset(jd_midnight, lat, lon, tz)

        # Use sunrise JD for all Panchang calculations (traditional)
        jd = sun_moon.sunrise_jd if sun_moon.sunrise_jd > 0 else jd_noon

        sun_lon = self._planet_lon(jd, swe.SUN)
        moon_lon = self._planet_lon(jd, swe.MOON)

        tithi = self._tithi(sun_lon, moon_lon, jd)
        nakshatra = self._nakshatra(moon_lon, jd)
        yoga = self._yoga(sun_lon, moon_lon, jd)
        karana = self._karana(sun_lon, moon_lon, jd)
        vara_idx = dt_midnight.weekday()  # Mon=0 in Python; adjust to Sun=0
        vara_idx = (dt_midnight.weekday() + 1) % 7  # Sun=0 … Sat=6

        rahu, yama, gulika = self._inauspicious_times(
            sun_moon.sunrise_jd, sun_moon.sunset_jd, vara_idx, tz
        )
        abhijit = self._abhijit(sun_moon.sunrise_jd, sun_moon.sunset_jd, tz)
        choghadiya = self._choghadiya(sun_moon.sunrise_jd, sun_moon.sunset_jd, vara_idx, tz)

        return PanchangResult(
            date=target_date.isoformat(),
            vara=_VARA_NAMES[vara_idx],
            tithi=tithi,
            nakshatra=nakshatra,
            yoga=yoga,
            karana=karana,
            sun_moon=sun_moon,
            rahu_kaal=rahu,
            yamagandam=yama,
            gulika=gulika,
            abhijit_muhurat=abhijit,
            choghadiya=choghadiya,
            vikram_samvat=self._vikram_samvat(target_date),
            shaka_samvat=self._shaka_samvat(target_date),
            masa=_HINDU_MONTHS[int(moon_lon / 30) % 12],
            ayana="Uttarayana" if 1 <= target_date.month <= 6 else "Dakshinayana",
            ritu=_RITUS[((target_date.month - 1) // 2) % 6],
        )

    # ── Core Panchang limbs ───────────────────────────────────

    def _tithi(self, sun_lon: float, moon_lon: float, jd: float) -> TithiInfo:
        diff = (moon_lon - sun_lon) % 360
        tithi_num = int(diff / 12)   # 0–29
        paksha = "Shukla" if tithi_num < 15 else "Krishna"
        display_num = tithi_num + 1  # 1-based

        # Calculate end time: when does diff hit next multiple of 12°?
        next_boundary = (tithi_num + 1) * 12.0
        end_jd = self._find_moon_sun_angle(jd, next_boundary)
        return TithiInfo(
            number=display_num,
            name=_TITHI_NAMES[tithi_num],
            paksha=paksha,
            end_time=self._jd_to_time_str(end_jd),
        )

    def _nakshatra(self, moon_lon: float, jd: float) -> NakshatraInfo:
        nak_size = 360.0 / 27.0
        idx = int(moon_lon / nak_size) % 27
        deg_in_nak = moon_lon % nak_size
        pada = int(deg_in_nak / (nak_size / 4)) + 1
        from app.astrology.constants import NAKSHATRA_LORDS
        lord = NAKSHATRA_LORDS[idx]

        # End time: when Moon reaches next nakshatra boundary
        next_boundary = (idx + 1) * nak_size
        end_jd = self._find_moon_angle(jd, next_boundary % 360)
        return NakshatraInfo(
            index=idx, name=NAKSHATRAS[idx], lord=lord, pada=pada,
            end_time=self._jd_to_time_str(end_jd),
        )

    def _yoga(self, sun_lon: float, moon_lon: float, jd: float) -> YogaInfo:
        yoga_size = 360.0 / 27.0
        combined = (sun_lon + moon_lon) % 360
        idx = int(combined / yoga_size) % 27
        name = _YOGA_NAMES[idx]

        next_boundary = (idx + 1) * yoga_size
        end_jd = self._find_sun_moon_sum(jd, next_boundary % 360)
        return YogaInfo(
            index=idx, name=name,
            end_time=self._jd_to_time_str(end_jd),
            auspicious=name not in _INAUSPICIOUS_YOGAS,
        )

    def _karana(self, sun_lon: float, moon_lon: float, jd: float) -> KaranaInfo:
        diff = (moon_lon - sun_lon) % 360
        karana_num = int(diff / 6)   # 0–59 (but cycles differ)
        # Fixed karanas: 0=Kimstughna, 57=Shakuni, 58=Chatushpada, 59=Naga
        fixed_map = {0: "Kimstughna", 57: "Shakuni", 58: "Chatushpada", 59: "Naga"}
        if karana_num in fixed_map:
            name = fixed_map[karana_num]
        else:
            movable_idx = (karana_num - 1) % 7
            name = _KARANA_NAMES[movable_idx]

        next_boundary = (karana_num + 1) * 6.0
        end_jd = self._find_moon_sun_angle(jd, next_boundary % 360)
        return KaranaInfo(name=name, end_time=self._jd_to_time_str(end_jd))

    # ── Sunrise / sunset ──────────────────────────────────────

    def _sunrise_sunset(
        self, jd_midnight: float, lat: float, lon: float, tz: str
    ) -> SunriseSunset:
        try:
            # swe.rise_trans returns (flag, JD) for sunrise/sunset
            sr_flags = swe.CALC_RISE | swe.BIT_DISC_CENTER
            ss_flags = swe.CALC_SET | swe.BIT_DISC_CENTER
            _, sr_jd = swe.rise_trans(jd_midnight, swe.SUN, "", swe.FLG_SWIEPH, sr_flags, lat, lon, 0)
            _, ss_jd = swe.rise_trans(jd_midnight, swe.SUN, "", swe.FLG_SWIEPH, ss_flags, lat, lon, 0)
            _, mr_jd = swe.rise_trans(jd_midnight, swe.MOON, "", swe.FLG_SWIEPH, swe.CALC_RISE, lat, lon, 0)
            _, ms_jd = swe.rise_trans(jd_midnight, swe.MOON, "", swe.FLG_SWIEPH, swe.CALC_SET, lat, lon, 0)

            sr_jd = sr_jd[0] if hasattr(sr_jd, '__iter__') else float(sr_jd)
            ss_jd = ss_jd[0] if hasattr(ss_jd, '__iter__') else float(ss_jd)
            mr_jd = mr_jd[0] if hasattr(mr_jd, '__iter__') else float(mr_jd)
            ms_jd = ms_jd[0] if hasattr(ms_jd, '__iter__') else float(ms_jd)

            day_hours = (ss_jd - sr_jd) * 24.0
            return SunriseSunset(
                sunrise=self._jd_to_local_str(sr_jd, tz),
                sunset=self._jd_to_local_str(ss_jd, tz),
                moonrise=self._jd_to_local_str(mr_jd, tz),
                moonset=self._jd_to_local_str(ms_jd, tz),
                sunrise_jd=sr_jd,
                sunset_jd=ss_jd,
                day_duration_hours=day_hours,
            )
        except Exception:
            # Fallback to approximate values
            approx_sr = jd_midnight + 6.0 / 24.0
            approx_ss = jd_midnight + 18.0 / 24.0
            return SunriseSunset(
                sunrise="06:00", sunset="18:00",
                moonrise="--:--", moonset="--:--",
                sunrise_jd=approx_sr, sunset_jd=approx_ss,
                day_duration_hours=12.0,
            )

    # ── Inauspicious timings ──────────────────────────────────

    def _inauspicious_times(
        self, sr_jd: float, ss_jd: float, vara_idx: int, tz: str
    ) -> tuple[str, str, str]:
        day_duration = ss_jd - sr_jd   # in days
        eighth = day_duration / 8.0

        def time_slot(eighth_num: int) -> str:
            start_jd = sr_jd + (eighth_num - 1) * eighth
            end_jd = start_jd + eighth
            return f"{self._jd_to_local_str(start_jd, tz)} – {self._jd_to_local_str(end_jd, tz)}"

        return (
            time_slot(_RAHU_KAAL_EIGHTH[vara_idx]),
            time_slot(_YAMAGANDAM_EIGHTH[vara_idx]),
            time_slot(_GULIKA_EIGHTH[vara_idx]),
        )

    def _abhijit(self, sr_jd: float, ss_jd: float, tz: str) -> str:
        # Abhijit = middle of day ± 24 minutes
        midday_jd = (sr_jd + ss_jd) / 2.0
        start_jd = midday_jd - 24.0 / (24 * 60)
        end_jd   = midday_jd + 24.0 / (24 * 60)
        return f"{self._jd_to_local_str(start_jd, tz)} – {self._jd_to_local_str(end_jd, tz)}"

    def _choghadiya(
        self, sr_jd: float, ss_jd: float, vara_idx: int, tz: str
    ) -> list[Muhurat]:
        result: list[Muhurat] = []
        day_duration = ss_jd - sr_jd
        night_duration = 1.0 - day_duration   # days
        day_slot = day_duration / 8.0
        night_slot = night_duration / 8.0

        day_offset = _CHOGHADIYA_DAY_START[vara_idx]
        night_offset = _CHOGHADIYA_NIGHT_START[vara_idx]

        for i in range(8):
            name = _CHOGHADIYA_DAY_ORDER[(day_offset + i) % 8]
            start_jd = sr_jd + i * day_slot
            end_jd = start_jd + day_slot
            result.append(Muhurat(
                name=name,
                start=self._jd_to_local_str(start_jd, tz),
                end=self._jd_to_local_str(end_jd, tz),
                quality=_CHOGHADIYA_QUALITY[name],
            ))
        for i in range(8):
            name = _CHOGHADIYA_NIGHT_ORDER[(night_offset + i) % 8]
            start_jd = ss_jd + i * night_slot
            end_jd = start_jd + night_slot
            result.append(Muhurat(
                name=f"{name} (Night)",
                start=self._jd_to_local_str(start_jd, tz),
                end=self._jd_to_local_str(end_jd, tz),
                quality=_CHOGHADIYA_QUALITY[name],
            ))
        return result

    # ── Hindu calendar ────────────────────────────────────────

    def _vikram_samvat(self, d: date) -> int:
        # Vikram Samvat is approx Gregorian year + 56 or 57
        return d.year + 57 if d.month <= 3 else d.year + 56

    def _shaka_samvat(self, d: date) -> int:
        return d.year - 78

    # ── Iteration helpers ─────────────────────────────────────

    def _find_moon_sun_angle(self, jd_start: float, target_angle: float) -> float:
        """Find JD when (Moon - Sun) % 360 reaches target_angle."""
        step = 0.5 / 24  # 30-min steps
        jd = jd_start
        for _ in range(200):
            sun = self._planet_lon(jd, swe.SUN)
            moon = self._planet_lon(jd, swe.MOON)
            diff = (moon - sun) % 360
            if abs(diff - target_angle % 360) < 0.5:
                return jd
            if diff < target_angle % 360:
                jd += step
            else:
                jd += step
        return jd_start + 1.0

    def _find_moon_angle(self, jd_start: float, target_lon: float) -> float:
        step = 0.5 / 24
        jd = jd_start
        for _ in range(100):
            moon = self._planet_lon(jd, swe.MOON)
            if abs(moon - target_lon) < 0.5:
                return jd
            jd += step
        return jd_start + 1.0

    def _find_sun_moon_sum(self, jd_start: float, target_sum: float) -> float:
        step = 0.5 / 24
        jd = jd_start
        for _ in range(200):
            sun = self._planet_lon(jd, swe.SUN)
            moon = self._planet_lon(jd, swe.MOON)
            total = (sun + moon) % 360
            if abs(total - target_sum) < 0.5:
                return jd
            jd += step
        return jd_start + 1.0

    # ── Utility ───────────────────────────────────────────────

    def _planet_lon(self, jd: float, body: int) -> float:
        flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
        pos, _ = swe.calc_ut(jd, body, flags)
        return pos[0]

    def _jd(self, dt: datetime) -> float:
        dt_utc = dt.astimezone(zoneinfo.ZoneInfo("UTC"))
        hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
        return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)

    def _tzinfo(self, tz: str):
        try:
            return zoneinfo.ZoneInfo(tz)
        except Exception:
            return zoneinfo.ZoneInfo("Asia/Kolkata")

    def _jd_to_local_str(self, jd: float, tz: str) -> str:
        """Convert Julian day to local time string HH:MM."""
        try:
            # JD to UTC datetime
            year, month, day, hour_frac = swe.revjul(jd)
            hour = int(hour_frac)
            minute = int((hour_frac - hour) * 60)
            dt_utc = datetime(year, month, day, hour, minute, tzinfo=zoneinfo.ZoneInfo("UTC"))
            dt_local = dt_utc.astimezone(self._tzinfo(tz))
            return dt_local.strftime("%H:%M")
        except Exception:
            return "--:--"

    def _jd_to_time_str(self, jd: float) -> str:
        """Convert Julian day to UTC time string HH:MM (approximate end times)."""
        try:
            year, month, day, hour_frac = swe.revjul(jd)
            hour = int(hour_frac) % 24
            minute = int((hour_frac - int(hour_frac)) * 60)
            return f"{hour:02d}:{minute:02d}"
        except Exception:
            return "--:--"
