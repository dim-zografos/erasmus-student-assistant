from dataclasses import dataclass
import re
from io import BytesIO
from typing import Any, Dict, List


@dataclass
class SpreadsheetAgreementResult:
    cleaned_content: str
    agreements: List[Dict[str, str]]


COUNTRY_TRANSLATIONS = {
    "ΑΛΒΑΝΙΑ": "Albania",
    "ΑΥΣΤΡΙΑ": "Austria",
    "ΒΕΛΓΙΟ": "Belgium",
    "ΒΟΥΛΓΑΡΙΑ": "Bulgaria",
    "ΓΑΛΛΙΑ": "France",
    "ΓΕΡΜΑΝΙΑ": "Germany",
    "ΔΑΝΙΑ": "Denmark",
    "ΕΛΒΕΤΙΑ": "Switzerland",
    "ΕΣΘΟΝΙΑ": "Estonia",
    "ΗΝΩΜΕΝΟ ΒΑΣΙΛΕΙΟ": "United Kingdom",
    "ΙΡΛΑΝΔΙΑ": "Ireland",
    "ΙΣΛΑΝΔΙΑ": "Iceland",
    "ΙΣΠΑΝΙΑ": "Spain",
    "ΙΤΑΛΙΑ": "Italy",
    "ΚΡΟΑΤΙΑ": "Croatia",
    "ΚΥΠΡΟΣ": "Cyprus",
    "ΛΕΤΟΝΙΑ": "Latvia",
    "ΛΙΘΟΥΑΝΙΑ": "Lithuania",
    "ΜΑΛΤΑ": "Malta",
    "ΝΟΡΒΗΓΙΑ": "Norway",
    "ΟΛΛΑΝΔΙΑ": "Netherlands",
    "ΟΥΓΓΑΡΙΑ": "Hungary",
    "ΠΟΛΩΝΙΑ": "Poland",
    "ΠΟΡΤΟΓΑΛΙΑ": "Portugal",
    "ΡΟΥΜΑΝΙΑ": "Romania",
    "ΣΕΡΒΙΑ": "Serbia",
    "ΣΛΟΒΑΚΙΑ": "Slovakia",
    "ΣΛΟΒΕΝΙΑ": "Slovenia",
    "ΣΟΥΗΔΙΑ": "Sweden",
    "ΣΟΥΗΔΗΑ": "Sweden",
    "ΤΟΥΡΚΙΑ": "Turkey",
    "ΤΣΕΧΙΑ": "Czech Republic",
    "ΤΣΕΧΙΚΗ ΔΗΜΟΚΡΑΤΙΑ": "Czech Republic",
    "ΦΙΝΛΑΝΔΙΑ": "Finland",
    "ΦΙΛΑΝΔΙΑ": "Finland",
    "ΒΟΡΕΙΑ ΜΑΚΕΔΟΝΙΑ": "North Macedonia",
    "ΔΗΜΟΚΡΑΤΙΑ ΤΗΣ ΒΟΡΕΙΑΣ ΜΑΚΕΔΟΝΙΑΣ": "North Macedonia",
}


DEPARTMENT_TRANSLATIONS = {
    "Τμήμα Επιστήμης Φυτικής Παραγωγής": "Department of Plant Production Science",
    "Τμήμα Επιστήμης Ζωικής Παραγωγής": "Department of Animal Production Science",
    "Τμήμα Αξιοποίησης Φυσικών Πόρων και Γεωργικής Μηχανικής": "Department of Natural Resources Management and Agricultural Engineering",
    "Τμήμα Επιστήμης Τροφίμων και Διατροφής του Ανθρώπου": "Department of Food Science and Human Nutrition",
    "Τμήμα Βιοτεχνολογίας": "Department of Biotechnology",
    "Τμήμα Αγροτικής Οικονομίας και Ανάπτυξης": "Department of Agricultural Economics and Rural Development",
    "Τμήμα Δασολογίας και Διαχείρισης Φυσικού Περιβάλλοντος": "Department of Forestry and Natural Environment Management",
    "Τμήμα Περιφερειακής & Οικονομικής Ανάπτυξης": "Department of Regional and Economic Development",
    "Τμήμα Διοίκησης Γεωργικών Επιχειρήσεων και Συστημάτων Εφοδιασμού": "Department of Business Administration of Food and Agricultural Enterprises",
}


LEVEL_TRANSLATIONS = {
    "Π": "Undergraduate",
    "P": "Undergraduate",
    "Μ": "Postgraduate",
    "M": "Postgraduate",
    "Δ": "Doctoral",
    "D": "Doctoral",
}


GREEK_TERM_TRANSLATIONS = {
    "πρώην": "former",
    "ΠΡΩΗΝ": "former",
    "έτος": "year",
    "Έτος": "Year",
    "ΕΤΟΣ": "year",
    "με": "with",
    "Με": "With",
    "ΜΕ": "with",
}


def extract_legacy_xls_agreements(data: bytes, source_title: str = "") -> SpreadsheetAgreementResult | None:
    try:
        import pandas as pd
    except ImportError:
        return None

    try:
        sheets = pd.read_excel(BytesIO(data), sheet_name=None, header=None, dtype=str, engine="xlrd")
    except Exception:
        return None

    agreements: List[Dict[str, str]] = []
    for sheet_name, frame in sheets.items():
        if frame.empty:
            continue
        frame = frame.fillna("").astype(str)
        department = _find_department(frame) or _clean_text(sheet_name)
        academic_year = _find_academic_year(frame) or _find_academic_year(source_title)
        header_index, columns = _find_header(frame)
        if header_index is None:
            continue

        for _, row in frame.iloc[header_index + 1 :].iterrows():
            item = _agreement_from_row(row.tolist(), columns, department, academic_year)
            if item:
                agreements.append(item)

    agreements = _dedupe_agreements(agreements)
    if not agreements:
        return None

    lines = [
        "Erasmus+ bilateral agreement spreadsheet.",
        "The source is a legacy Excel file parsed into structured student mobility agreement rows.",
        f"Records found: {len(agreements)}.",
        "",
        "Agreement rows:",
    ]
    for item in agreements:
        lines.append(
            "- "
            f"Department: {item['department']}; "
            f"Partner university: {item['partner_university']}; "
            f"Country: {item['partner_country']}; "
            f"Academic year: {item['academic_year']}; "
            f"{item['evidence_text']}"
        )

    return SpreadsheetAgreementResult(cleaned_content="\n".join(lines), agreements=agreements)


def _find_header(frame) -> tuple[int | None, Dict[str, int]]:
    for index, row in frame.iterrows():
        values = [_clean_text(value) for value in row.tolist()]
        joined = " ".join(values).upper()
        if ("ΠΑΝΕΠΙΣΤΗΜΙΟ" not in joined and "UNIVERSITY" not in joined) or (
            "ΧΩΡΑ" not in joined and "COUNTRY" not in joined
        ):
            continue

        columns: Dict[str, int] = {}
        for position, value in enumerate(values):
            key = _column_key(value)
            if key and key not in columns:
                columns[key] = position
        if "partner_university" in columns and "partner_country" in columns:
            return int(index), columns
    return None, {}


def _agreement_from_row(values: List[Any], columns: Dict[str, int], department: str, fallback_year: str) -> Dict[str, str] | None:
    partner = _clean_partner(_cell(values, columns.get("partner_university")))
    country = _translate_country(_cell(values, columns.get("partner_country")))
    if not partner or not country:
        return None
    if _looks_like_header_or_total(partner) or _looks_like_header_or_total(country):
        return None

    student_places = _cell(values, columns.get("student_places"))
    months = _cell(values, columns.get("months"))
    staff_places = _cell(values, columns.get("staff_places"))
    if not student_places and not months and staff_places:
        return None

    erasmus_code = _clean_evidence_value(_cell(values, columns.get("erasmus_code")))
    academic_year = _normalize_year(_cell(values, columns.get("academic_year")) or fallback_year)
    direction = _clean_evidence_value(_cell(values, columns.get("direction")))
    field = _clean_evidence_value(_cell(values, columns.get("field")))
    level = _translate_levels(_cell(values, columns.get("level")))
    url = _cell(values, columns.get("url"))

    evidence_parts = []
    if erasmus_code:
        evidence_parts.append(f"Erasmus code: {erasmus_code}")
    if academic_year:
        evidence_parts.append(f"academic years: {academic_year}")
    if direction:
        evidence_parts.append(f"mobility direction: {direction}")
    if field:
        evidence_parts.append(f"subject area: {field}")
    if level:
        evidence_parts.append(f"study level: {level}")
    if student_places:
        evidence_parts.append(f"student places: {student_places}")
    if months:
        evidence_parts.append(f"student mobility duration/months: {months}")
    if url:
        evidence_parts.append(f"partner information URL: {url}")

    return {
        "department": _translate_department(department),
        "partner_university": partner,
        "partner_country": country,
        "academic_year": academic_year,
        "deadline": "",
        "confidence": "high",
        "evidence_text": "; ".join(evidence_parts),
    }


def _column_key(value: str) -> str:
    text = _clean_text(value).upper()
    if text in {"ΧΩΡΑ", "COUNTRY"}:
        return "partner_country"
    if "ΚΩΔΙΚΟΣ" in text or "ERASMUS CODE" in text:
        return "erasmus_code"
    if "ΠΑΝΕΠΙΣΤΗΜΙΟ" in text or "UNIVERSITY" in text or "INSTITUTION" in text:
        return "partner_university"
    if "ΑΚΑΔ" in text or "YEAR" in text:
        return "academic_year"
    if "ΑΠΟ" in text or "FROM" in text or "DIRECTION" in text:
        return "direction"
    if "ΤΟΜΕΑΣ" in text or "FIELD" in text or "SUBJECT" in text:
        return "field"
    if "ΕΠΙΠΕΔΟ" in text or "LEVEL" in text:
        return "level"
    if "ΘΕΣΕΙΣ" in text or "PLACES" in text:
        return "student_places"
    if "ΜΗΝΕΣ" in text or "MONTH" in text:
        return "months"
    if text in {"ΔΕΠ", "STAFF"} or "TEACH" in text:
        return "staff_places"
    if "ΙΣΤΟΣΕΛΙΔΑ" in text or "WEBSITE" in text or "URL" in text:
        return "url"
    return ""


def _find_department(frame) -> str:
    for _, row in frame.head(20).iterrows():
        for value in row.tolist():
            text = _clean_text(value)
            if text.startswith("Τμήμα ") or text.startswith("Department "):
                return text
    return ""


def _find_academic_year(value: Any) -> str:
    text = " ".join(
        _clean_text(item)
        for item in (value.values.flatten().tolist() if hasattr(value, "values") else [value])
    )
    match = re.search(r"20\d{2}\s*[-/]\s*(?:20)?\d{2}", text)
    return _normalize_year(match.group(0)) if match else ""


def _cell(values: List[Any], index: int | None) -> str:
    if index is None or index >= len(values):
        return ""
    return _clean_text(values[index])


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "" if text.lower() == "nan" else text
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_partner(value: str) -> str:
    text = _clean_text(value).strip(" ,;")
    text = _replace_known_greek_terms(text)
    text = _replace_greek_homoglyphs(text)
    text = re.sub(r"\([^)]*[\u0370-\u03ff][^)]*\)", "", text)
    text = re.sub(r"[\u0370-\u03ff]+", "", text)
    text = re.sub(r"\(\s*[A-Z]{1,3}\s+[A-Z0-9 -]*\d{2,}\s*\)", "", text)
    return re.sub(r"\s+", " ", text).strip(" ,;")


def _clean_evidence_value(value: str) -> str:
    return _replace_greek_homoglyphs(_replace_known_greek_terms(_clean_text(value)))


def _translate_country(value: str) -> str:
    text = _clean_text(value).upper()
    text = text.replace("Ά", "Α").replace("Έ", "Ε").replace("Ί", "Ι").replace("Ό", "Ο").replace("Ύ", "Υ").replace("Ή", "Η").replace("Ώ", "Ω")
    return COUNTRY_TRANSLATIONS.get(text, _title_if_upper(_clean_text(value)))


def _translate_department(value: str) -> str:
    text = _clean_text(value)
    return DEPARTMENT_TRANSLATIONS.get(text, text if not _contains_greek(text) else "")


def _translate_levels(value: str) -> str:
    text = _replace_known_greek_terms(_clean_text(value))
    if not text:
        return ""
    text = re.sub(r"[\u0370-\u03ff]+", "", text)
    parts = [part.strip() for part in re.split(r"[,/]+", text) if part.strip()]
    translated = []
    for part in parts:
        translated.append(LEVEL_TRANSLATIONS.get(part, part))
    return ", ".join(dict.fromkeys(translated))


def _normalize_year(value: str) -> str:
    text = _clean_text(value)
    return re.sub(r"\s+", "", text)


def _title_if_upper(value: str) -> str:
    text = _clean_text(value)
    return text.title() if text.isupper() else text


def _looks_like_header_or_total(value: str) -> bool:
    text = _clean_text(value).upper()
    return text in {"ΧΩΡΑ", "COUNTRY", "ΠΑΝΕΠΙΣΤΗΜΙΟ", "UNIVERSITY", "TOTAL", "ΣΥΝΟΛΟ"}


def _contains_greek(value: str) -> bool:
    return any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff" for char in value)


def _replace_greek_homoglyphs(value: str) -> str:
    replacements = str.maketrans(
        {
            "Α": "A",
            "Β": "B",
            "Ε": "E",
            "Ζ": "Z",
            "Η": "H",
            "Ι": "I",
            "Κ": "K",
            "Μ": "M",
            "Ν": "N",
            "Ο": "O",
            "Ρ": "P",
            "Τ": "T",
            "Υ": "Y",
            "Χ": "X",
            "α": "a",
            "β": "b",
            "ε": "e",
            "η": "n",
            "ι": "i",
            "κ": "k",
            "μ": "m",
            "ν": "v",
            "ο": "o",
            "ρ": "p",
            "τ": "t",
            "υ": "u",
            "χ": "x",
        }
    )
    return value.translate(replacements)


def _replace_known_greek_terms(value: str) -> str:
    text = value
    for greek, english in GREEK_TERM_TRANSLATIONS.items():
        text = text.replace(greek, english)
    return text


def _dedupe_agreements(agreements: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    unique = []
    for item in agreements:
        key = (
            item.get("department", ""),
            item.get("partner_university", "").lower(),
            item.get("partner_country", "").lower(),
            item.get("academic_year", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
