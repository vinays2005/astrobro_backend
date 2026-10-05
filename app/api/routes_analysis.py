"""Chart analysis APIs: Vimshottari Dasha, doshas and remedies."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.api.common import chart_from_birth, utc_now
from app.astrology import dasha as D
from app.astrology import doshas as DO
from app.astrology import remedies as R
from app.models.features import BirthOnlyRequest, DashaRequest, DoshaRequest
from app.security.auth import require_api_key

dasha_router = APIRouter(prefix="/api/dasha", tags=["dasha"], dependencies=[Depends(require_api_key)])
dosha_router = APIRouter(prefix="/api/dosha", tags=["dosha"], dependencies=[Depends(require_api_key)])
remedies_router = APIRouter(prefix="/api/remedies", tags=["remedies"], dependencies=[Depends(require_api_key)])


# ── Dasha ─────────────────────────────────────────────────────────────────────

@dasha_router.post("/timeline")
async def dasha_timeline(req: DashaRequest) -> dict:
    """Vimshottari timeline: Mahadashas with Antardashas, the running periods and what is coming."""
    chart = chart_from_birth(req.birth_data)
    asc = chart.ascendant["sign_index"]
    timeline = D.build_timeline(chart.planets["Moon"].longitude, chart.birth_datetime)
    now = utc_now().replace(tzinfo=None)
    horizon = now + timedelta(days=365.25 * req.years_ahead)

    def profile(lord: str) -> dict:
        return D.lord_profile(lord, chart.planets, chart.houses, asc)

    def with_text(p: dict, level: str) -> dict:
        d = D.period_dict(p, with_text=req.include_interpretation, profile=profile(p["lord"]), level=level)
        return d

    cur = D.period_at(timeline, now)
    current = None
    if cur:
        current = {"mahadasha": with_text(cur["maha"], "mahadasha")}
        if cur["antar"]:
            current["antardasha"] = with_text(cur["antar"], "antardasha")
        if cur["praty"]:
            current["pratyantardasha"] = with_text(cur["praty"], "pratyantardasha")

    mahadashas = []
    for maha in timeline:
        entry = with_text(maha, "mahadasha")
        entry["is_current"] = maha["start"] <= now < maha["end"]
        entry["balance_at_birth"] = maha["balance_at_birth"]
        if req.depth in ("antar", "praty"):
            entry["antardashas"] = []
            for a in maha["antardashas"]:
                ad = D.period_dict(a)
                ad["is_current"] = a["start"] <= now < a["end"]
                if req.depth == "praty" and a["end"] >= now and a["start"] <= horizon and len(
                        [x for x in entry["antardashas"] if "pratyantardashas" in x]) < 2:
                    ad["pratyantardashas"] = [D.period_dict(x) for x in D.pratyantardashas(maha["lord"], a["lord"], a["start"], a["end"])]
                entry["antardashas"].append(ad)
        mahadashas.append(entry)

    upcoming = []
    for maha in timeline:
        for a in maha["antardashas"]:
            if now < a["start"] <= horizon:
                upcoming.append({"mahadasha": maha["lord"], "antardasha": a["lord"], "starts": a["start"].date().isoformat(),
                                 "ends": a["end"].date().isoformat()})
    yogini = chart.yogini_dasha.get("current")
    return {
        "moon": {"sign": chart.planets["Moon"].sign, "nakshatra": chart.nakshatra_moon.name, "pada": chart.nakshatra_moon.pada},
        "current": current, "mahadashas": mahadashas, "upcoming_antardashas": upcoming[:15],
        "yogini_current": yogini,
        "note": "Vimshottari Dasha uses a 120-year cycle counted from the Moon's nakshatra at birth.",
    }


# ── Doshas ────────────────────────────────────────────────────────────────────

@dosha_router.post("/analyze")
async def dosha_analyze(req: DoshaRequest) -> dict:
    """Manglik, Kaal Sarp, Sade Sati, Pitru, Grahan, Guru Chandala, Angarak, Shrapit, Vish and Gand Mool."""
    chart = chart_from_birth(req.birth_data)
    result = DO.analyze(chart, utc_now())
    if req.include_remedies:
        keys = [d["remedy_key"] for d in result["doshas"] if d["present"]]
        result["remedies"] = R.dosha_remedies(keys)
        result["disclaimer"] = R.DISCLAIMER
    return result


# ── Remedies ──────────────────────────────────────────────────────────────────

@remedies_router.post("/personal")
async def personal_remedies(req: BirthOnlyRequest) -> dict:
    """Remedies chosen from your chart: strengthen weak benefics, pacify malefics, support the running dasha."""
    chart = chart_from_birth(req.birth_data)
    out = R.personal_remedies(chart, utc_now())
    doshas = DO.analyze(chart, utc_now())
    out["dosha_remedies"] = R.dosha_remedies([d["remedy_key"] for d in doshas["doshas"] if d["present"]])
    return out


@remedies_router.get("/planet/{planet}")
async def planet_remedies(planet: str) -> dict:
    rem = R.planet_remedy(planet.strip().title())
    if rem is None:
        raise HTTPException(status_code=404, detail="Unknown planet. Use Sun, Moon, Mars, Mercury, Jupiter, Venus, Saturn, Rahu or Ketu.")
    return {"planet": planet.strip().title(), **rem, "disclaimer": R.DISCLAIMER}


@remedies_router.get("/doshas")
async def dosha_remedy_list() -> dict:
    return {"doshas": R.dosha_remedies(list(R.DOSHA_REMEDIES)), "disclaimer": R.DISCLAIMER}
