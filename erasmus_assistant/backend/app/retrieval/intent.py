from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass
class Intent:
    name: str
    university_keys: List[str]
    partner_country: str = ""


def detect_intent(question: str, universities: List[Dict[str, Any]], countries: Iterable[str]) -> Intent:
    text = question.lower()
    university_keys = _match_universities(text, universities)
    country = _match_country(text, countries)

    agreement_terms = [
        "agreement", "agreements", "partner", "partners", "partner university",
        "where can i go", "which universities", "country can i go", "bilateral",
    ]
    deadline_terms = ["deadline", "deadlines", "apply by", "until when", "application date"]
    requirement_terms = ["requirement", "requirements", "documents", "eligibility", "criteria", "how to apply"]

    if any(term in text for term in agreement_terms) or country:
        return Intent("agreements", university_keys=university_keys, partner_country=country)
    if any(term in text for term in deadline_terms):
        return Intent("deadlines", university_keys=university_keys, partner_country=country)
    if any(term in text for term in requirement_terms):
        return Intent("requirements", university_keys=university_keys, partner_country=country)
    return Intent("general", university_keys=university_keys, partner_country=country)


def _match_universities(text: str, universities: List[Dict[str, Any]]) -> List[str]:
    matches: List[str] = []
    aliases = {
        "uth": ["uth", "thessaly", "university of thessaly"],
        "uoa": ["uoa", "athens university", "kapodistrian", "national and kapodistrian"],
        "ntua": ["ntua", "technical university of athens", "polytechnic athens"],
        "auth": ["auth", "aristotle", "thessaloniki"],
        "aueb": ["aueb", "economics and business"],
        "unipi": ["unipi", "piraeus"],
        "uom": ["uom", "university of macedonia"],
        "upatras": ["upatras", "patras"],
        "uoi": ["uoi", "ioannina"],
        "duth": ["duth", "democritus", "thrace"],
    }
    for uni in universities:
        key = str(uni.get("key", "")).lower()
        name = str(uni.get("name", "")).lower()
        candidates = [key, name] + aliases.get(key, [])
        if any(candidate and candidate in text for candidate in candidates):
            matches.append(key)
    return matches


def _match_country(text: str, countries: Iterable[str]) -> str:
    countries_sorted = sorted([country for country in countries if country], key=len, reverse=True)
    for country in countries_sorted:
        if country.lower() in text:
            return country
    return ""
