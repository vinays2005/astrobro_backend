"""
Real Vedic Panchang calculations using Swiss Ephemeris.

Five limbs (Pancha Anga):
  Tithi     = (Moon_lon - Sun_lon) % 360 / 12   → 1–30
  Vara      = weekday (Sun=0 … Sat=6)
  Nakshatra = Moon_lon / (360/27)                → 0–26
  Yoga      = (Sun_lon + Moon_lon) / (360/27)    → 0–26
  Karana    = half-tithi, 0–59 slots

Additional:
  Rahu Kaal, Yamagandam, Gulika, Gulika Kaal
  Brahma Muhurat (96 min before sunrise)
  Abhijit Muhurat (midday ± 24 min)
  Amrit Kaal (auspicious 48-min window based on Nakshatra)
  Choghadiya (day + night, 8 slots each)
  Hora (planetary hours, all 24)
  Sun Rashi, Moon Rashi
  Vara Lord, Tithi deity, Tithi nature
  Disha Shool (inauspicious direction by weekday)
  Hindu calendar: Vikram Samvat, Shaka Samvat, Masa, Ayana, Ritu

All calculations are deterministic. No LLM involvement.
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
    number: int
    name: str
    paksha: str
    end_time: str
    deity: str
    nature: str      # Nanda | Bhadra | Jaya | Rikta | Purna


@dataclass
class NakshatraInfo:
    index: int
    name: str
    lord: str
    pada: int
    end_time: str
    deity: str
    gana: str        # Deva | Manushya | Rakshasa


@dataclass
class YogaInfo:
    index: int
    name: str
    end_time: str
    auspicious: bool
    description: str


@dataclass
class KaranaInfo:
    name: str
    end_time: str
    auspicious: bool


@dataclass
class SunriseSunset:
    sunrise: str
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
    quality: str     # auspicious | inauspicious | neutral
    is_night: bool = False


@dataclass
class HoraSlot:
    planet: str
    start: str
    end: str
    is_night: bool


@dataclass
class PanchangResult:
    date: str
    vara: str
    vara_lord: str
    tithi: TithiInfo
    nakshatra: NakshatraInfo
    yoga: YogaInfo
    karana: KaranaInfo
    sun_moon: SunriseSunset
    sun_rashi: str
    moon_rashi: str
    rahu_kaal: str
    yamagandam: str
    gulika: str
    brahma_muhurat: str
    abhijit_muhurat: str
    amrit_kaal: list[str]
    disha_shool: str
    choghadiya: list[Muhurat]
    hora: list[HoraSlot]
    vikram_samvat: int
    shaka_samvat: int
    masa: str
    ayana: str
    ritu: str


# ── Constants ─────────────────────────────────────────────────────────────────

_TITHI_NAMES = [
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Purnima",
    "Pratipada", "Dwitiya", "Tritiya", "Chaturthi", "Panchami",
    "Shashthi", "Saptami", "Ashtami", "Navami", "Dashami",
    "Ekadashi", "Dwadashi", "Trayodashi", "Chaturdashi", "Amavasya",
]

_TITHI_DEITIES = [
    "Agni", "Brahma", "Gauri", "Ganesha", "Nagas",
    "Kartikeya", "Indra", "Shiva", "Durga", "Yama",
    "Vishvadeva", "Vishnu", "Kamadeva", "Shiva", "Moon (Chandra)",
    "Agni", "Brahma", "Gauri", "Ganesha", "Nagas",
    "Kartikeya", "Indra", "Shiva", "Durga", "Yama",
    "Vishvadeva", "Vishnu", "Kamadeva", "Shiva", "Pitru",
]

# Nanda=1,6,11 | Bhadra=2,7,12 | Jaya=3,8,13 | Rikta=4,9,14 | Purna=5,10,15,Purnima/Amavasya
def _tithi_nature(tithi_num_0based: int) -> str:
    r = (tithi_num_0based % 15) % 5
    return ["Nanda", "Bhadra", "Jaya", "Rikta", "Purna"][r]

_YOGA_NAMES = [
    "Vishkambha", "Priti", "Ayushman", "Saubhagya", "Shobhana",
    "Atiganda", "Sukarma", "Dhriti", "Shoola", "Ganda", "Vriddhi",
    "Dhruva", "Vyaghata", "Harshana", "Vajra", "Siddhi", "Vyatipata",
    "Variyan", "Parigha", "Shiva", "Siddha", "Sadhya", "Shubha",
    "Shukla", "Brahma", "Indra", "Vaidhriti",
]
_INAUSPICIOUS_YOGAS = {
    "Vishkambha", "Atiganda", "Shoola", "Ganda", "Vyaghata",
    "Vajra", "Vyatipata", "Parigha", "Vaidhriti",
}
_YOGA_DESC = {
    "Vishkambha": "Obstruction; avoid new ventures",
    "Priti": "Love and friendship; excellent for all auspicious work",
    "Ayushman": "Long life; good for health-related activities",
    "Saubhagya": "Good fortune; highly auspicious",
    "Shobhana": "Splendour; good for ceremonies",
    "Atiganda": "Danger; avoid travel and risky activities",
    "Sukarma": "Good deeds; favourable for all work",
    "Dhriti": "Steadiness; good for financial matters",
    "Shoola": "Pain; avoid surgeries and important work",
    "Ganda": "Calamity; avoid new beginnings",
    "Vriddhi": "Growth; excellent for business and education",
    "Dhruva": "Fixed/stable; good for permanent work and property",
    "Vyaghata": "Tiger-like; avoid travel",
    "Harshana": "Joy; good for auspicious ceremonies",
    "Vajra": "Thunderbolt; inauspicious, avoid important tasks",
    "Siddhi": "Success; highly auspicious for all work",
    "Vyatipata": "Calamity; one of the most inauspicious yogas",
    "Variyan": "Comfort; neutral to moderately good",
    "Parigha": "Obstacle; avoid travel and new work",
    "Shiva": "Auspicious; good for religious activities",
    "Siddha": "Accomplished; very good for all auspicious work",
    "Sadhya": "Achievable; good for goal-oriented activities",
    "Shubha": "Auspicious; excellent for ceremonies and weddings",
    "Shukla": "Pure/bright; good for learning and spiritual work",
    "Brahma": "Divine; excellent for all auspicious activities",
    "Indra": "Powerful; good for administrative and governmental work",
    "Vaidhriti": "Dangerous; avoid all auspicious work",
}

_KARANA_NAMES = [
    "Bava", "Balava", "Kaulava", "Taitila", "Garaja", "Vanija", "Vishti",
]
_FIXED_KARANAS = {0: "Kimstughna", 57: "Shakuni", 58: "Chatushpada", 59: "Naga"}
_INAUSPICIOUS_KARANAS = {"Vishti", "Shakuni", "Chatushpada", "Naga", "Kimstughna"}

_VARA_NAMES  = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_VARA_LORDS  = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]
_VARA_LORDS_HI = ["Surya", "Chandra", "Mangal", "Budha", "Guru", "Shukra", "Shani"]

# Disha Shool (inauspicious direction) by weekday (Sun=0)
_DISHA_SHOOL = ["West", "East", "North", "North", "South", "West", "East"]

# Rahu Kaal by weekday (Sun=0): which 1/8th of the day
_RAHU_KAAL_EIGHTH  = [8, 2, 7, 5, 6, 4, 3]
_YAMAGANDAM_EIGHTH = [5, 4, 3, 2, 1, 7, 6]
_GULIKA_EIGHTH     = [6, 5, 4, 3, 2, 1, 7]

# Choghadiya names — indexed from Sunday
_CHOGHADIYA_DAY_ORDER = [
    "Udveg", "Char", "Labh", "Amrit", "Kaal", "Shubh", "Rog", "Udveg",
]
_CHOGHADIYA_NIGHT_ORDER = [
    "Shubh", "Amrit", "Char", "Rog", "Kaal", "Labh", "Udveg", "Shubh",
]
_CHOGHADIYA_QUALITY = {
    "Amrit": "auspicious", "Shubh": "auspicious", "Labh": "auspicious",
    "Char": "neutral", "Rog": "inauspicious", "Kaal": "inauspicious",
    "Udveg": "inauspicious",
}
_CHOGHADIYA_DAY_START   = [0, 6, 5, 4, 3, 2, 1]
_CHOGHADIYA_NIGHT_START = [4, 3, 2, 1, 0, 6, 5]

# Hora planet order (starting from sunrise on each weekday)
# Sunday: Sun, Venus, Mercury, Moon, Saturn, Jupiter, Mars, Sun, ...
_HORA_PLANET_ORDER = ["Sun", "Venus", "Mercury", "Moon", "Saturn", "Jupiter", "Mars"]
_HORA_START_INDEX  = [0, 6, 5, 4, 3, 2, 1]  # Sun=0 start index per weekday

_HINDU_MONTHS = [
    "Chaitra", "Vaishakha", "Jyeshtha", "Ashadha", "Shravana", "Bhadrapada",
    "Ashwin", "Kartik", "Margashirsha", "Pausha", "Magha", "Phalguna",
]
_RITUS = ["Vasanta", "Grishma", "Varsha", "Sharad", "Hemanta", "Shishira"]

_NAKSHATRA_DEITIES = [
    "Ashvini Kumaras", "Yama", "Agni", "Brahma", "Chandra", "Rudra",
    "Aditi", "Brihaspati", "Sarpa", "Pitru", "Bhaga", "Aryaman",
    "Savita", "Tvashta", "Vayu", "Indra & Agni", "Mitra", "Indra",
    "Nirriti", "Apah", "Vishvadeva", "Vishnu", "Varuna", "Aja Ekapad",
    "Ahir Budhnya", "Pushan", "Ashvini Kumaras",
]
_NAKSHATRA_GANAS = [
    "Deva", "Manushya", "Rakshasa", "Deva", "Manushya", "Manushya",
    "Deva", "Manushya", "Rakshasa", "Pitru", "Manushya", "Manushya",
    "Deva", "Manushya", "Rakshasa", "Manushya", "Deva", "Manushya",
    "Rakshasa", "Deva", "Rakshasa", "Deva", "Manushya", "Deva",
    "Rakshasa", "Manushya", "Deva",
]

_SIGN_NAMES = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]


# ── Engine ────────────────────────────────────────────────────────────────────

class PanchangEngine:
    """Deterministic Vedic Panchang calculator using Swiss Ephemeris."""

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
        dt_midnight = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=tzinfo)
        jd_midnight = self._jd(dt_midnight)

        sun_moon = self._sunrise_sunset(jd_midnight, lat, lon, tz)
        jd = sun_moon.sunrise_jd if sun_moon.sunrise_jd > 0 else (jd_midnight + 6.0 / 24.0)

        sun_lon  = self._planet_lon(jd, swe.SUN)
        moon_lon = self._planet_lon(jd, swe.MOON)

        tithi     = self._tithi(sun_lon, moon_lon, jd, tz)
        nakshatra = self._nakshatra(moon_lon, jd, tz)
        yoga      = self._yoga(sun_lon, moon_lon, jd, tz)
        karana    = self._karana(sun_lon, moon_lon, jd, tz)

        vara_idx = (dt_midnight.weekday() + 1) % 7   # Mon→Tue→…→Sun → 0=Sun
        vara_lord = _VARA_LORDS[vara_idx]

        rahu, yama, gulika = self._inauspicious_times(
            sun_moon.sunrise_jd, sun_moon.sunset_jd, vara_idx, tz
        )
        brahma   = self._brahma_muhurat(sun_moon.sunrise_jd, tz)
        abhijit  = self._abhijit(sun_moon.sunrise_jd, sun_moon.sunset_jd, tz)
        amrit    = self._amrit_kaal(nakshatra.index, sun_moon.sunrise_jd,
                                    sun_moon.sunset_jd, jd_midnight, tz)
        chog     = self._choghadiya(sun_moon.sunrise_jd, sun_moon.sunset_jd, vara_idx, tz)
        hora     = self._hora(sun_moon.sunrise_jd, sun_moon.sunset_jd, jd_midnight, vara_idx, tz)

        sun_rashi  = _SIGN_NAMES[int(sun_lon / 30) % 12]
        moon_rashi = _SIGN_NAMES[int(moon_lon / 30) % 12]
        masa       = self._masa(sun_lon)
        ayana      = self._ayana(sun_lon)
        ritu       = self._ritu(sun_lon)

        return PanchangResult(
            date=target_date.isoformat(),
            vara=_VARA_NAMES[vara_idx],
            vara_lord=vara_lord,
            tithi=tithi,
            nakshatra=nakshatra,
            yoga=yoga,
            karana=karana,
            sun_moon=sun_moon,
            sun_rashi=sun_rashi,
            moon_rashi=moon_rashi,
            rahu_kaal=rahu,
            yamagandam=yama,
            gulika=gulika,
            brahma_muhurat=brahma,
            abhijit_muhurat=abhijit,
            amrit_kaal=amrit,
            disha_shool=_DISHA_SHOOL[vara_idx],
            choghadiya=chog,
            hora=hora,
            vikram_samvat=self._vikram_samvat(target_date),
            shaka_samvat=self._shaka_samvat(target_date),
            masa=masa,
            ayana=ayana,
            ritu=ritu,
        )

    # ── Core Panchang limbs ───────────────────────────────────────────────────

    def _tithi(self, sun_lon: float, moon_lon: float, jd: float, tz: str) -> TithiInfo:
        diff = (moon_lon - sun_lon) % 360
        idx  = int(diff / 12)           # 0–29
        paksha = "Shukla" if idx < 15 else "Krishna"

        # Find exact end: Moon-Sun angle reaches next multiple of 12°
        next_deg = (idx + 1) * 12.0
        end_jd = self._find_moon_minus_sun(jd, next_deg)

        return TithiInfo(
            number=idx + 1,
            name=_TITHI_NAMES[idx],
            paksha=paksha,
            end_time=self._jd_to_local_str(end_jd, tz),
            deity=_TITHI_DEITIES[idx],
            nature=_tithi_nature(idx),
        )

    def _nakshatra(self, moon_lon: float, jd: float, tz: str) -> NakshatraInfo:
        nak_size = 360.0 / 27.0
        idx      = int(moon_lon / nak_size) % 27
        deg_in   = moon_lon % nak_size
        pada     = int(deg_in / (nak_size / 4)) + 1

        from app.astrology.constants import NAKSHATRA_LORDS
        lord = NAKSHATRA_LORDS[idx]

        next_boundary = (idx + 1) * nak_size
        end_jd = self._find_moon_lon(jd, next_boundary % 360)

        return NakshatraInfo(
            index=idx,
            name=NAKSHATRAS[idx],
            lord=lord,
            pada=pada,
            end_time=self._jd_to_local_str(end_jd, tz),
            deity=_NAKSHATRA_DEITIES[idx],
            gana=_NAKSHATRA_GANAS[idx],
        )

    def _yoga(self, sun_lon: float, moon_lon: float, jd: float, tz: str) -> YogaInfo:
        yoga_size = 360.0 / 27.0
        combined  = (sun_lon + moon_lon) % 360
        idx       = int(combined / yoga_size) % 27
        name      = _YOGA_NAMES[idx]

        next_deg = (idx + 1) * yoga_size
        end_jd = self._find_sun_plus_moon(jd, next_deg % 360)

        return YogaInfo(
            index=idx,
            name=name,
            end_time=self._jd_to_local_str(end_jd, tz),
            auspicious=name not in _INAUSPICIOUS_YOGAS,
            description=_YOGA_DESC.get(name, ""),
        )

    def _karana(self, sun_lon: float, moon_lon: float, jd: float, tz: str) -> KaranaInfo:
        diff = (moon_lon - sun_lon) % 360
        k    = int(diff / 6)            # 0–59
        if k in _FIXED_KARANAS:
            name = _FIXED_KARANAS[k]
        else:
            name = _KARANA_NAMES[(k - 1) % 7]

        next_deg = (k + 1) * 6.0
        end_jd = self._find_moon_minus_sun(jd, next_deg % 360)

        return KaranaInfo(
            name=name,
            end_time=self._jd_to_local_str(end_jd, tz),
            auspicious=name not in _INAUSPICIOUS_KARANAS,
        )

    # ── Sunrise / Moonrise ────────────────────────────────────────────────────

    def _sunrise_sunset(self, jd_midnight: float, lat: float, lon: float, tz: str) -> SunriseSunset:
        try:
            sr_flags = swe.CALC_RISE | swe.BIT_DISC_CENTER
            ss_flags = swe.CALC_SET  | swe.BIT_DISC_CENTER
            _, sr = swe.rise_trans(jd_midnight, swe.SUN,  "", swe.FLG_SWIEPH, sr_flags, lat, lon, 0)
            _, ss = swe.rise_trans(jd_midnight, swe.SUN,  "", swe.FLG_SWIEPH, ss_flags, lat, lon, 0)
            _, mr = swe.rise_trans(jd_midnight, swe.MOON, "", swe.FLG_SWIEPH, swe.CALC_RISE, lat, lon, 0)
            _, ms = swe.rise_trans(jd_midnight, swe.MOON, "", swe.FLG_SWIEPH, swe.CALC_SET,  lat, lon, 0)

            sr_jd = sr[0] if hasattr(sr, '__iter__') else float(sr)
            ss_jd = ss[0] if hasattr(ss, '__iter__') else float(ss)
            mr_jd = mr[0] if hasattr(mr, '__iter__') else float(mr)
            ms_jd = ms[0] if hasattr(ms, '__iter__') else float(ms)

            return SunriseSunset(
                sunrise=self._jd_to_local_str(sr_jd, tz),
                sunset=self._jd_to_local_str(ss_jd, tz),
                moonrise=self._jd_to_local_str(mr_jd, tz),
                moonset=self._jd_to_local_str(ms_jd, tz),
                sunrise_jd=sr_jd, sunset_jd=ss_jd,
                day_duration_hours=round((ss_jd - sr_jd) * 24.0, 2),
            )
        except Exception:
            approx_sr = jd_midnight + 6.0 / 24.0
            approx_ss = jd_midnight + 18.0 / 24.0
            return SunriseSunset(
                sunrise="06:00", sunset="18:00",
                moonrise="--:--", moonset="--:--",
                sunrise_jd=approx_sr, sunset_jd=approx_ss,
                day_duration_hours=12.0,
            )

    # ── Auspicious / Inauspicious timings ────────────────────────────────────

    def _inauspicious_times(self, sr_jd: float, ss_jd: float, vara_idx: int, tz: str) -> tuple[str, str, str]:
        day = ss_jd - sr_jd
        eighth = day / 8.0

        def slot(n: int) -> str:
            s = sr_jd + (n - 1) * eighth
            e = s + eighth
            return f"{self._jd_to_local_str(s, tz)} – {self._jd_to_local_str(e, tz)}"

        return (
            slot(_RAHU_KAAL_EIGHTH[vara_idx]),
            slot(_YAMAGANDAM_EIGHTH[vara_idx]),
            slot(_GULIKA_EIGHTH[vara_idx]),
        )

    def _brahma_muhurat(self, sr_jd: float, tz: str) -> str:
        """Brahma Muhurat: 96 minutes before sunrise (2 muhurtas = 48 min each)."""
        end_jd   = sr_jd - 0.0 / 24.0   # ends at sunrise
        start_jd = sr_jd - 96.0 / (24.0 * 60.0)
        return f"{self._jd_to_local_str(start_jd, tz)} – {self._jd_to_local_str(end_jd, tz)}"

    def _abhijit(self, sr_jd: float, ss_jd: float, tz: str) -> str:
        mid = (sr_jd + ss_jd) / 2.0
        s   = mid - 24.0 / (24.0 * 60.0)
        e   = mid + 24.0 / (24.0 * 60.0)
        return f"{self._jd_to_local_str(s, tz)} – {self._jd_to_local_str(e, tz)}"

    def _amrit_kaal(
        self,
        nak_idx: int,
        sr_jd: float,
        ss_jd: float,
        jd_midnight: float,
        tz: str,
    ) -> list[str]:
        """
        Amrit Kaal: auspicious 48-minute window(s) per day, calculated from
        the nakshatra's Chandra Hora. Two windows possible in a day.
        Approximation: offset from sunrise based on nakshatra number mod 8.
        """
        # Traditional: each nakshatra has a fixed offset from sunrise
        # Offset table (hours after sunrise) for each nakshatra's first amrit window
        amrit_offsets_h = [
            7.5, 10.0, 12.5, 2.0, 4.5, 7.0, 9.5, 12.0, 1.5, 4.0,
            6.5, 9.0, 11.5, 1.0, 3.5, 6.0, 8.5, 11.0, 0.5, 3.0,
            5.5, 8.0, 10.5, 0.0, 2.5, 5.0, 7.5,
        ]
        offset = amrit_offsets_h[nak_idx % 27]
        results = []
        for i in range(2):
            start_jd = sr_jd + (offset + i * 12.0) / 24.0
            end_jd   = start_jd + 48.0 / (24.0 * 60.0)
            # Only include if within today's window (midnight to midnight+1)
            day_end = jd_midnight + 1.0
            if start_jd < day_end and end_jd > jd_midnight:
                results.append(
                    f"{self._jd_to_local_str(start_jd, tz)} – {self._jd_to_local_str(end_jd, tz)}"
                )
        return results or ["--:-- – --:--"]

    # ── Choghadiya ────────────────────────────────────────────────────────────

    def _choghadiya(self, sr_jd: float, ss_jd: float, vara_idx: int, tz: str) -> list[Muhurat]:
        result: list[Muhurat] = []
        day_dur    = ss_jd - sr_jd
        # Night goes sunset → next sunrise (approx: same day_dur for night)
        night_dur  = 1.0 - day_dur
        day_slot   = day_dur / 8.0
        night_slot = night_dur / 8.0

        day_off   = _CHOGHADIYA_DAY_START[vara_idx]
        night_off = _CHOGHADIYA_NIGHT_START[vara_idx]

        for i in range(8):
            name = _CHOGHADIYA_DAY_ORDER[(day_off + i) % 8]
            s = sr_jd + i * day_slot
            e = s + day_slot
            result.append(Muhurat(
                name=name, start=self._jd_to_local_str(s, tz),
                end=self._jd_to_local_str(e, tz),
                quality=_CHOGHADIYA_QUALITY[name], is_night=False,
            ))
        for i in range(8):
            name = _CHOGHADIYA_NIGHT_ORDER[(night_off + i) % 8]
            s = ss_jd + i * night_slot
            e = s + night_slot
            result.append(Muhurat(
                name=name, start=self._jd_to_local_str(s, tz),
                end=self._jd_to_local_str(e, tz),
                quality=_CHOGHADIYA_QUALITY[name], is_night=True,
            ))
        return result

    # ── Hora (planetary hours) ────────────────────────────────────────────────

    def _hora(
        self, sr_jd: float, ss_jd: float, jd_midnight: float, vara_idx: int, tz: str
    ) -> list[HoraSlot]:
        """24 hora slots: 12 day (sunrise→sunset) + 12 night (sunset→next sunrise)."""
        result: list[HoraSlot] = []
        day_slot   = (ss_jd - sr_jd) / 12.0
        night_slot = (1.0 - (ss_jd - sr_jd)) / 12.0
        start_idx  = _HORA_START_INDEX[vara_idx]

        for i in range(12):
            planet = _HORA_PLANET_ORDER[(start_idx + i) % 7]
            s = sr_jd + i * day_slot
            e = s + day_slot
            result.append(HoraSlot(
                planet=planet, start=self._jd_to_local_str(s, tz),
                end=self._jd_to_local_str(e, tz), is_night=False,
            ))
        # Night hora: continues from where day left off
        night_start_idx = (start_idx + 12) % 7
        for i in range(12):
            planet = _HORA_PLANET_ORDER[(night_start_idx + i) % 7]
            s = ss_jd + i * night_slot
            e = s + night_slot
            result.append(HoraSlot(
                planet=planet, start=self._jd_to_local_str(s, tz),
                end=self._jd_to_local_str(e, tz), is_night=True,
            ))
        return result

    # ── Hindu calendar ────────────────────────────────────────────────────────

    def _masa(self, sun_lon: float) -> str:
        """Hindu month based on the sidereal solar longitude."""
        idx = int(sun_lon / 30) % 12
        return _HINDU_MONTHS[idx]

    def _ayana(self, sun_lon: float) -> str:
        """
        Uttarayana: Sun in Capricorn–Gemini (270°–90°), sidereal.
        Dakshinayana: Sun in Cancer–Sagittarius (90°–270°), sidereal.
        """
        if sun_lon >= 270 or sun_lon < 90:
            return "Uttarayana"
        return "Dakshinayana"

    def _ritu(self, sun_lon: float) -> str:
        """Season based on sidereal solar longitude (each Ritu = 2 months = 60°)."""
        idx = int(sun_lon / 60) % 6
        return _RITUS[idx]

    def _vikram_samvat(self, d: date) -> int:
        # Vikram Samvat new year falls in Chaitra (March–April)
        # Before Chaitra Shukla Pratipada: still the old VS year
        return d.year + 57 if d.month >= 4 else d.year + 56

    def _shaka_samvat(self, d: date) -> int:
        return d.year - 78

    # ── Precise angle finders (Newton-Raphson style) ──────────────────────────

    def _find_moon_minus_sun(self, jd_start: float, target_deg: float) -> float:
        """Find JD when (Moon - Sun) % 360 == target_deg.
        Moon-Sun angle increases at ~12.19°/day on average."""
        target = target_deg % 360
        jd = jd_start
        for _ in range(30):
            sun  = self._planet_lon(jd, swe.SUN)
            moon = self._planet_lon(jd, swe.MOON)
            cur  = (moon - sun) % 360
            delta = (target - cur) % 360    # how many degrees to go
            if delta < 0.01:
                return jd
            jd += delta / 12.19 / 1.0      # degrees / (deg/day) = days
        return jd

    def _find_moon_lon(self, jd_start: float, target_deg: float) -> float:
        """Find JD when Moon's sidereal longitude reaches target_deg.
        Moon moves ~13.18°/day."""
        target = target_deg % 360
        jd = jd_start
        for _ in range(30):
            moon = self._planet_lon(jd, swe.MOON)
            delta = (target - moon) % 360
            if delta < 0.01:
                return jd
            jd += delta / 13.18
        return jd

    def _find_sun_plus_moon(self, jd_start: float, target_deg: float) -> float:
        """Find JD when (Sun + Moon) % 360 == target_deg.
        Sum increases at ~14.18°/day."""
        target = target_deg % 360
        jd = jd_start
        for _ in range(30):
            sun  = self._planet_lon(jd, swe.SUN)
            moon = self._planet_lon(jd, swe.MOON)
            cur  = (sun + moon) % 360
            delta = (target - cur) % 360
            if delta < 0.01:
                return jd
            jd += delta / 14.18
        return jd

    # ── Utilities ─────────────────────────────────────────────────────────────

    def _planet_lon(self, jd: float, body: int) -> float:
        flags = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
        pos, _ = swe.calc_ut(jd, body, flags)
        return pos[0]

    def _jd(self, dt: datetime) -> float:
        utc = dt.astimezone(zoneinfo.ZoneInfo("UTC"))
        h = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
        return swe.julday(utc.year, utc.month, utc.day, h)

    def _tzinfo(self, tz: str):
        try:
            return zoneinfo.ZoneInfo(tz)
        except Exception:
            return zoneinfo.ZoneInfo("Asia/Kolkata")

    def _jd_to_local_str(self, jd: float, tz: str) -> str:
        try:
            y, mo, d, hf = swe.revjul(jd)
            h  = int(hf) % 24
            mi = int((hf - int(hf)) * 60)
            dt_utc = datetime(y, mo, d, h, mi, tzinfo=zoneinfo.ZoneInfo("UTC"))
            dt_loc = dt_utc.astimezone(self._tzinfo(tz))
            return dt_loc.strftime("%H:%M")
        except Exception:
            return "--:--"
