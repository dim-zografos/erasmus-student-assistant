import time
import re
from typing import Any, Dict, Optional

from tqdm import tqdm

from ..core.models import AgreementCandidate, ErasmusAgreement, ScrapedDocument
from ..storage.database import (
    log_event,
    replace_document_chunks,
    save_agreement_candidate,
    save_content_ingestion_skip,
    save_erasmus_agreement,
    save_scraped_document,
    save_structured_extraction_log,
)
from ..utils import hash_values, json_loads_list
from .agreement_extractor import extract_agreements_with_gemini
from .chunker import chunk_text
from .fetcher import fetch_selected_source
from .normalizer import normalize_document_with_gemini
from .selected_sources import load_selected_sources
from .structured_sources import parse_structured_source, StructuredSourceDocument
from .text_extractors import extract_text
from .vector_store import rebuild_vector_store


AGREEMENT_CATEGORIES = {"agreements", "partner_universities"}


def ingest_selected_sources(
    conn,
    university_key: Optional[str] = None,
    base_url_id: Optional[int] = None,
    limit: Optional[int] = None,
    include_processed: bool = False,
    model: Optional[str] = None,
    rebuild_vectors: bool = True,
    delay_seconds: float = 0.0,
) -> Dict[str, int]:
    rows = load_selected_sources(
        conn,
        university_key=university_key,
        base_url_id=base_url_id,
        include_processed=include_processed,
        limit=limit,
    )
    stats = {"seen": len(rows), "documents": 0, "chunks": 0, "agreements": 0, "candidates": 0, "skipped": 0, "errors": 0}

    with tqdm(total=len(rows), desc="Ingesting selected URLs") as progress:
        for row in rows:
            try:
                result = ingest_one_selected_source(conn, row, model=model)
                for key in ("documents", "chunks", "agreements", "candidates"):
                    stats[key] += result.get(key, 0)
            except ValueError as exc:
                stats["skipped"] += 1
                reason = str(exc)
                save_content_ingestion_skip(conn, int(row["id"]), row["university_key"], row["url"], reason)
                log_event(conn, "content_ingestion", "skipped", reason, row["university_key"], row["url"])
            except RuntimeError as exc:
                stats["errors"] += 1
                log_event(conn, "content_ingestion", "error", str(exc), row["university_key"], row["url"])
                raise
            except Exception as exc:
                stats["skipped"] += 1
                reason = str(exc)
                save_content_ingestion_skip(conn, int(row["id"]), row["university_key"], row["url"], reason)
                log_event(conn, "content_ingestion", "skipped", reason, row["university_key"], row["url"])
            finally:
                progress.update(1)
            if delay_seconds > 0:
                time.sleep(delay_seconds)

    if rebuild_vectors:
        stats["vector_chunks"] = rebuild_vector_store(conn)
    return stats


def ingest_one_selected_source(conn, row, model: Optional[str] = None) -> Dict[str, int]:
    allowed_domains = json_loads_list(row["university_allowed_domains"])
    fetched = fetch_selected_source(row, allowed_domains)

    structured_document = parse_structured_source(row, fetched, AGREEMENT_CATEGORIES)
    if structured_document:
        return _store_structured_source_document(conn, row, structured_document)

    raw_text = extract_text(fetched.data, fetched.content_type, fetched.url)
    if not raw_text.strip():
        raise ValueError("No extractable text was found in the source.")

    normalized = normalize_document_with_gemini(
        raw_text=raw_text,
        source_url=row["url"],
        title=fetched.title or row["title"] or "",
        category=row["category"] or "",
        model=model,
    )
    cleaned_content = _clean_stored_content(normalized.get("cleaned_content") or "")
    if not bool(normalized.get("store_document", True)):
        raise ValueError(normalized.get("skip_reason") or "Gemini decided this source has no useful public Erasmus content.")
    if not cleaned_content:
        raise ValueError("Gemini decided to store the document but returned no cleaned content.")
    if _looks_like_access_or_placeholder_page(cleaned_content):
        raise ValueError("Gemini returned access-restricted or placeholder text instead of useful public content.")
    if _looks_like_generic_title_only_page(cleaned_content, normalized.get("title"), fetched.title, row["title"]):
        raise ValueError("The cleaned document only contains a generic page title, not useful Erasmus content.")

    document = ScrapedDocument(
        selected_url_id=int(row["id"]),
        university_key=row["university_key"],
        university_name=row["university_name"],
        source_url=row["url"],
        title=normalized.get("title") or fetched.title or row["title"] or "",
        category=row["category"] or "",
        cleaned_content=cleaned_content,
        document_type=normalized.get("document_type") or row["category"] or "",
        key_topics=[str(item) for item in normalized.get("key_topics", []) if str(item).strip()],
        contains_agreements=bool(normalized.get("contains_agreements")),
        contains_deadlines=bool(normalized.get("contains_deadlines")),
        contains_requirements=bool(normalized.get("contains_requirements")),
    )
    document_id, chunk_count = _save_document_and_chunks(conn, row, document)

    agreement_stats = _extract_and_save_agreements(
        conn,
        row,
        document_id,
        normalized,
        cleaned_content,
        raw_text,
        model,
    )
    log_event(conn, "content_ingestion", "ok", f"Stored document {document_id}", row["university_key"], row["url"])
    return {
        "documents": 1,
        "chunks": chunk_count,
        "agreements": agreement_stats["agreements"],
        "candidates": agreement_stats["candidates"],
    }


def _save_document_and_chunks(conn, row, document: ScrapedDocument) -> tuple[int, int]:
    document_id = save_scraped_document(conn, document)
    chunks = chunk_text(document.cleaned_content)
    replace_document_chunks(
        conn,
        document_id=document_id,
        selected_url_id=int(row["id"]),
        university_key=row["university_key"],
        university_name=row["university_name"],
        source_url=row["url"],
        category=document.category,
        chunks=chunks,
    )
    return document_id, len(chunks)


def _store_structured_source_document(conn, row, source_document: StructuredSourceDocument) -> Dict[str, int]:
    cleaned_content = _clean_stored_content(source_document.cleaned_content)
    document = ScrapedDocument(
        selected_url_id=int(row["id"]),
        university_key=row["university_key"],
        university_name=row["university_name"],
        source_url=row["url"],
        title=source_document.title,
        category=source_document.category,
        cleaned_content=cleaned_content,
        document_type=source_document.document_type,
        key_topics=source_document.key_topics,
        contains_agreements=source_document.contains_agreements,
        contains_deadlines=source_document.contains_deadlines,
        contains_requirements=source_document.contains_requirements,
    )
    document_id, chunk_count = _save_document_and_chunks(conn, row, document)
    agreement_stats = _save_agreement_items(
        conn,
        row,
        document_id,
        source_document.agreements,
        dedupe_scope=source_document.dedupe_scope,
    )

    save_structured_extraction_log(
        conn,
        document_id,
        row["url"],
        "ok",
        agreement_stats["agreements"],
        (
            "Parsed structured source and saved "
            f"{agreement_stats['agreements']} agreements and {agreement_stats['candidates']} candidates."
        ),
    )
    log_event(conn, "content_ingestion", "ok", f"Stored structured document {document_id}", row["university_key"], row["url"])
    return {
        "documents": 1,
        "chunks": chunk_count,
        "agreements": agreement_stats["agreements"],
        "candidates": agreement_stats["candidates"],
    }


def _extract_and_save_agreements(
    conn,
    row,
    document_id: int,
    normalized: Dict[str, Any],
    cleaned_content: str,
    extracted_text: str,
    model: Optional[str],
) -> Dict[str, int]:
    should_extract = bool(normalized.get("contains_agreements")) or (row["category"] or "") in AGREEMENT_CATEGORIES
    if not should_extract:
        save_structured_extraction_log(conn, document_id, row["url"], "skipped", 0, "Document does not appear to contain agreements.")
        return {"agreements": 0, "candidates": 0}

    extraction_source = extracted_text if (row["category"] or "") in AGREEMENT_CATEGORIES else cleaned_content

    agreements = extract_agreements_with_gemini(
        cleaned_content=extraction_source,
        source_url=row["url"],
        home_university_key=row["university_key"],
        home_university=row["university_name"],
        model=model,
    )

    agreement_stats = _save_agreement_items(conn, row, document_id, agreements, dedupe_scope="source")
    saved_agreements = agreement_stats["agreements"]
    saved_candidates = agreement_stats["candidates"]

    save_structured_extraction_log(
        conn,
        document_id,
        row["url"],
        "ok",
        saved_agreements,
        f"Saved {saved_agreements} agreements and {saved_candidates} candidates.",
    )
    return agreement_stats


def _save_agreement_items(
    conn,
    row,
    document_id: int,
    agreements: list[Dict[str, Any]],
    dedupe_scope: str,
) -> Dict[str, int]:
    saved_agreements = 0
    saved_candidates = 0
    seen_agreement_hashes: set[str] = set()
    for item in agreements:
        partner_university = _clean_field(item.get("partner_university"))
        if not partner_university:
            continue
        if _looks_staff_only(item):
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Rejected from agreements because it appears staff/teaching-only."))
            saved_candidates += 1
            continue
        if _looks_like_non_university_partner(item):
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Rejected from agreements because the partner is not clearly a university or higher education institution."))
            saved_candidates += 1
            continue
        if _looks_like_non_agreement_event(row, item):
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Rejected from agreements because it appears to be a mobility event, not a partner agreement."))
            saved_candidates += 1
            continue
        if _looks_like_student_exchange_story(row, item):
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Rejected from agreements because it appears to be a student exchange story, not a partner agreement."))
            saved_candidates += 1
            continue
        if _looks_like_non_erasmus_general_partnership(row, item):
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Rejected from agreements because it appears to be a general non-Erasmus partnership or exchange agreement."))
            saved_candidates += 1
            continue
        if _looks_like_alliance_partner_not_agreement(row, item):
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Rejected from agreements because it appears to be an alliance partner mention, not a confirmed Erasmus agreement row."))
            saved_candidates += 1
            continue
        confidence = _clean_field(item.get("confidence")).lower()
        if confidence in {"high", "medium"}:
            agreement = _agreement_from_item(row, document_id, item, confidence, dedupe_scope=dedupe_scope)
            if agreement.row_hash in seen_agreement_hashes:
                continue
            seen_agreement_hashes.add(agreement.row_hash)
            if save_erasmus_agreement(conn, agreement):
                saved_agreements += 1
        else:
            save_agreement_candidate(conn, _candidate_from_item(row, document_id, item, "Low confidence extraction."))
            saved_candidates += 1
    return {"agreements": saved_agreements, "candidates": saved_candidates}


def _agreement_from_item(
    row,
    document_id: int,
    item: Dict[str, Any],
    confidence: str,
    dedupe_scope: str = "source",
) -> ErasmusAgreement:
    department = _translate_greek_erasmus_terms(_clean_field(item.get("department")))
    partner_university = _clean_partner_university(item.get("partner_university"))
    partner_country = _clean_country(item.get("partner_country"))
    academic_year = _clean_field(item.get("academic_year"))
    hash_values_for_row = [
        row["university_key"],
        department,
        partner_university,
        partner_country,
        academic_year,
    ]
    if dedupe_scope == "source":
        hash_values_for_row.insert(0, row["url"])
    elif dedupe_scope != "university":
        raise ValueError(f"Unsupported agreement dedupe scope: {dedupe_scope}")
    return ErasmusAgreement(
        document_id=document_id,
        home_university_key=row["university_key"],
        home_university=row["university_name"],
        department=department,
        partner_university=partner_university,
        partner_country=partner_country,
        deadline=_clean_field(item.get("deadline")),
        academic_year=academic_year,
        source_url=row["url"],
        evidence_text=_clean_evidence_text(item.get("evidence_text")),
        confidence=confidence,
        row_hash=hash_values(hash_values_for_row),
    )


def _candidate_from_item(row, document_id: int, item: Dict[str, Any], reason: str) -> AgreementCandidate:
    return AgreementCandidate(
        document_id=document_id,
        home_university_key=row["university_key"],
        home_university=row["university_name"],
        department=_translate_greek_erasmus_terms(_clean_field(item.get("department"))),
        partner_university=_clean_partner_university(item.get("partner_university")),
        partner_country=_clean_country(item.get("partner_country")),
        deadline=_clean_field(item.get("deadline")),
        academic_year=_clean_field(item.get("academic_year")),
        source_url=row["url"],
        evidence_text=_clean_evidence_text(item.get("evidence_text")),
        confidence=_clean_field(item.get("confidence")).lower(),
        reason=reason,
    )


def _clean_field(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"unspecified", "unknown", "not provided", "n/a", "na", "none", "-"}:
        return ""
    return text


def _clean_partner_university(value: Any) -> str:
    text = _replace_greek_latin_homoglyphs(_clean_field(value))
    if not text:
        return ""
    text = re.sub(r"\(\s*Erasmus\s+code\s*:?\s*[^)]*\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*[A-Z]{1,3}\s+[A-Z0-9 -]*\d{2,}\s*\)", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" ,;-")


def _clean_country(value: Any) -> str:
    text = _replace_greek_latin_homoglyphs(_translate_greek_erasmus_terms(_clean_field(value)))
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text.strip())
    key = normalized.upper().replace(".", "")
    country_fixes = {
        "CZECH REBUBLIC": "Czech Republic",
        "CZECH REPUBLIC": "Czech Republic",
        "CZECHIA": "Czech Republic",
        "TURKIYE": "Turkey",
        "TÜRKIYE": "Turkey",
        "UNITED KINGDOM": "United Kingdom",
        "UK": "United Kingdom",
        "USA": "United States",
        "U S A": "United States",
    }
    if key in country_fixes:
        return country_fixes[key]
    if normalized.isupper():
        return normalized.title()
    return normalized


def _clean_evidence_text(value: Any) -> str:
    text = _clean_field(value)
    if not text:
        return ""
    text = _replace_greek_latin_homoglyphs(_translate_greek_erasmus_terms(text))
    parts = []
    for part in text.split(";"):
        normalized = part.strip().lower().rstrip(".")
        if any(placeholder in normalized for placeholder in ["unspecified", "unknown", "not provided", "n/a"]):
            continue
        parts.append(part.strip())
    return "; ".join(part for part in parts if part)


def _looks_staff_only(item: Dict[str, Any]) -> bool:
    text = " ".join(
        _clean_field(item.get(key)).lower()
        for key in ["department", "partner_university", "partner_country", "evidence_text"]
    )
    staff_terms = ["staff mobility", "teaching mobility", "teaching agreement", "faculty mobility", "academic staff"]
    student_terms = ["student", "students", "studies", "traineeship", "placement"]
    return any(term in text for term in staff_terms) and not any(term in text for term in student_terms)


def _looks_like_non_university_partner(item: Dict[str, Any]) -> bool:
    partner = _clean_partner_university(item.get("partner_university")).lower()
    evidence = _clean_evidence_text(item.get("evidence_text")).lower()
    text = f"{partner} {evidence}"
    non_university_terms = [
        "broadcasting corporation",
        "corporation",
        "company",
        "enterprise",
        "organisation",
        "organization",
    ]
    higher_ed_terms = [
        "university",
        "universita",
        "université",
        "universidad",
        "universiteit",
        "academy",
        "college",
        "institute",
        "school",
        "hochschule",
        "politecnico",
        "polytechnic",
    ]
    return any(term in text for term in non_university_terms) and not any(term in text for term in higher_ed_terms)


def _looks_like_non_agreement_event(row, item: Dict[str, Any]) -> bool:
    text = " ".join(
        _clean_field(value).lower()
        for value in [
            row["url"],
            row["title"],
            row["category"],
            item.get("evidence_text"),
        ]
    )
    event_terms = [
        "blended intensive programme",
        "blended intensive program",
        "bip",
        "participation in",
        "short-term mobility programme",
        "short-term mobility program",
    ]
    agreement_terms = ["bilateral", "inter-institutional", "agreement", "partner institutions"]
    return any(term in text for term in event_terms) and not any(term in text for term in agreement_terms)


def _looks_like_student_exchange_story(row, item: Dict[str, Any]) -> bool:
    text = " ".join(
        _clean_field(value).lower()
        for value in [
            row["title"],
            row["category"],
            item.get("partner_university"),
            item.get("evidence_text"),
        ]
    )
    story_terms = [
        "student exchange program",
        "exchange program",
        "student testimonial",
        "student reported",
        "participated in an exchange",
    ]
    agreement_terms = [
        "bilateral agreement",
        "inter-institutional agreement",
        "partner agreement",
        "agreement records",
        "partner universities list",
    ]
    return any(term in text for term in story_terms) and not any(term in text for term in agreement_terms)


def _looks_like_non_erasmus_general_partnership(row, item: Dict[str, Any]) -> bool:
    text = " ".join(
        _clean_field(value).lower()
        for value in [
            row["url"],
            row["title"],
            row["category"],
            item.get("partner_university"),
            item.get("evidence_text"),
        ]
    )
    erasmus_terms = [
        "erasmus",
        "erasmus+",
        "inter-institutional",
        "iia",
        "ka131",
        "ka171",
        "partner institutions",
    ]
    general_partnership_terms = [
        "partnerships-memberships",
        "partnerships memberships",
        "partnerships - memberships",
        "student and faculty exchange",
        "faculty exchange",
        "memorandum of understanding",
        "general cooperation",
    ]
    return any(term in text for term in general_partnership_terms) and not any(term in text for term in erasmus_terms)


def _looks_like_alliance_partner_not_agreement(row, item: Dict[str, Any]) -> bool:
    evidence = _clean_field(item.get("evidence_text")).lower()
    text = " ".join(
        _clean_field(value).lower()
        for value in [
            row["title"],
            row["category"],
            evidence,
        ]
    )
    alliance_terms = [
        "alliance partner",
        "alliance partners",
        "european university alliance",
        "artemis european university",
    ]
    confirmed_agreement_terms = [
        "bilateral agreement",
        "inter-institutional agreement with",
        "iia with",
        "agreement signed with",
        "valid agreement with",
    ]
    return any(term in text for term in alliance_terms) and not any(term in text for term in confirmed_agreement_terms)


def _looks_like_access_or_placeholder_page(text: str) -> bool:
    lowered = (text or "").lower()
    access_terms = [
        "you need to log in",
        "academic credentials",
        "login with your",
        "page not found",
        "access denied",
    ]
    return any(term in lowered for term in access_terms)


def _looks_like_generic_title_only_page(text: str, *titles: Any) -> bool:
    normalized_text = _normalize_for_title_match(text)
    if not normalized_text or len(normalized_text) > 120:
        return False
    important_short_terms = [
        "call for",
        "deadline",
        "application deadline",
        "results",
        "approved",
        "selected students",
        "academic year",
    ]
    if any(term in normalized_text for term in important_short_terms):
        return False

    title_matches = []
    for title in titles:
        normalized_title = _normalize_for_title_match(title)
        if not normalized_title:
            continue
        title_matches.append(normalized_title)
        if "|" in str(title):
            title_matches.append(_normalize_for_title_match(str(title).split("|", 1)[0]))

    generic_terms = ["erasmus", "guide", "home page", "mobility", "student mobility", "applications"]
    return any(normalized_text == candidate for candidate in title_matches) and any(
        term in normalized_text for term in generic_terms
    )


def _normalize_for_title_match(value: Any) -> str:
    text = _clean_field(value).lower()
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_stored_content(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    text = _translate_greek_course_code_letters(_translate_greek_erasmus_terms(text))
    return _replace_remaining_greek_markers(text).strip()


def _replace_remaining_greek_markers(text: str) -> str:
    if not text:
        return ""
    text = text.replace(
        "\u039a\u03b1\u03bd\u03bf\u03bd\u03b9\u03c3\u03bc\u03cc\u03c2 "
        "\u03a0\u03c1\u03b1\u03ba\u03c4\u03b9\u03ba\u03ae\u03c2 Erasmus",
        "Erasmus Traineeship Regulation",
    )
    omega = chr(0x03A9)
    dash_chars = "-" + chr(0x2013) + chr(0x2014)
    text = re.sub(rf"([A-Za-z])\s*[{re.escape(dash_chars)}]\s*{omega}", r"\1-Omega", text)
    text = re.sub(rf"([A-Za-z])\s+to\s+{omega}", r"\1 to Omega", text, flags=re.IGNORECASE)
    text = re.sub(r"[\u0391-\u03a9]+", lambda match: _transliterate_greek_code(match.group(0)), text)
    return text


def _transliterate_greek_code(value: str) -> str:
    replacements = {
        "\u0391": "A",
        "\u0392": "B",
        "\u0393": "G",
        "\u0394": "D",
        "\u0395": "E",
        "\u0396": "Z",
        "\u0397": "H",
        "\u0398": "TH",
        "\u0399": "I",
        "\u039a": "K",
        "\u039b": "L",
        "\u039c": "M",
        "\u039d": "N",
        "\u039e": "X",
        "\u039f": "O",
        "\u03a0": "P",
        "\u03a1": "R",
        "\u03a3": "S",
        "\u03a4": "T",
        "\u03a5": "Y",
        "\u03a6": "F",
        "\u03a7": "CH",
        "\u03a8": "PS",
        "\u03a9": "Omega",
    }
    return "".join(replacements.get(char, char) for char in value)


def _translate_greek_course_code_letters(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "Θ": "TH",
        "Σ": "S",
    }
    for greek, latin in replacements.items():
        text = text.replace(greek, latin)
    return text


def _translate_greek_erasmus_terms(text: str) -> str:
    replacements = {
        "Πίνακας Συνεργαζομένων Πανεπιστημίων": "List of Partner Universities",
        "Πίνακας Sυνεργαζομένων Πανεπιστημίων": "List of Partner Universities",
        "Διαδικασία Επιλογής Φοιτητών": "Student Selection Process",
        "Κριτήρια επιλογής": "Selection Criteria",
        "Θέσεις Πρακτικής Άσκησης": "Traineeship Offers",
        "THέσεις Πρακτικής Άσκησης": "Traineeship Offers",
        "Μετά την επιστροφή": "After return",
        "ΑΡΜΕΝΙΑ": "Armenia",
        "Αζερμπαϊτζάν": "Azerbaijan",
        "Αίγυπτος": "Egypt",
        "Αλγερία": "Algeria",
        "Αργεντινή": "Argentina",
        "Αρμενία": "Armenia",
        "Αυστραλία": "Australia",
        "Τμήμα Διοικητικής Επιστήμης και Τεχνολογίας": "Department of Management Science and Technology",
        "Τμήμα Λογιστικής και Χρηματοοικονομικής": "Department of Accounting and Finance",
        "Τμήμα Οργάνωσης και Διοίκησης Επιχειρήσεων": "Department of Business Administration",
        "Τμήμα Στατιστικής και Ασφαλιστικής Επιστήμης": "Department of Statistics and Insurance Science",
        "Τμήμα Οικονομικών Επιστημών": "Department of Economics",
        "Τμήμα Διεθνών και Ευρωπαϊκών Οικονομικών Σπουδών": "Department of International and European Economic Studies",
        "Τμήμα Μηχανολόγων Μηχανικών": "Department of Mechanical Engineering",
        "Παιδαγωγικό Τμήμα Δημοτικής Εκπαίδευσης": "Department of Primary Education",
        "Παιδαγωγικό Τμήμα Νηπιαγωγών": "Department of Early Childhood Education",
        "Τμήμα Ψυχολογίας": "Department of Psychology",
        "Τμήμα Μαιευτικής": "Department of Midwifery",
        "Τμήμα Εργοθεραπείας": "Department of Occupational Therapy",
        "Τμήμα Ηλεκτρολόγων Μηχανικών και Μηχανικών Πληροφορικής": "Department of Electrical and Computer Engineering",
        "Τμήμα Πληροφορικής": "Department of Informatics",
        "Τμήμα Γεωπονίας": "Department of Agriculture",
        "Τμήμα Χημικών Μηχανικών": "Department of Chemical Engineering",
        "Τμήμα Μηχανικών Ορυκτών Πόρων": "Department of Mineral Resources Engineering",
        "ΤΜΗΜΑ ΗΛΕΚΤΡΟΛΟΓΩΝ ΚΑΙ ΗΛΕΚΤΡΟΝΙΚΩΝ ΜΗΧΑΝΙΚΩΝ": "Department of Electrical and Electronic Engineering",
        "ΗΛΕΚΤΡΟΛΟΓΩΝ ΚΑΙ ΗΛΕΚΤΡΟΝΙΚΩΝ ΜΗΧΑΝΙΚΩΝ": "Electrical and Electronic Engineering",
        "ΤΜΗΜΑ ΝΟΣΗΛΕΥΤΙΚΗΣ": "Department of Nursing",
        "ΤΜΗΜΑ ΜΗΧΑΝΟΛΟΓΙΑΣ": "Department of Mechanical Engineering",
        "ΣΥΝΤΗΡΗΣΗ ΑΡΧΑΙΟΤΗΤΩΝ ΚΑΙ ΕΡΓΩΝ ΤΕΧΝΗΣ": "Conservation of Antiquities and Works of Art",
        "ΣΥΝΤΗΡΗΣΗ ΑΡΧΑΙΟΤΗΤΩΝ": "Conservation of Antiquities",
        "ΜΗΧΑΝΙΚΩΝ ΤΟΠΟΓΡΑΦΙΑΣ ΚΑΙ ΓΕΩΠΛΗΡΟΦΟΡΙΚΗΣ": "Surveying and Geoinformatics Engineering",
        "ΜΗΧΑΝΙΚΩΝ ΠΛΗΡΟΦΟΡΙΚΗΣ ΚΑΙ ΥΠΟΛΟΓΙΣΤΩΝ": "Informatics and Computer Engineering",
        "ΠΛΗΡΟΦΟΡΙΚΗΣ ΚΑΙ ΥΠΟΛΟΓΙΣΤΩΝ": "Informatics and Computer Engineering",
        "ΕΣΩΤΕΡΙΚΗ ΑΡΧΙΤΕΚΤΟΝΙΚΗ ΚΑΙ": "Interior Architecture and",
        "ΕΣΩΤΕΡΙΚΗ ΑΡΧΙΤΕΚΤΟΝΙΚΗ": "Interior Architecture",
        "ΕΠΙΣΤΗΜΗ ΚΑΙ ΤΕΧΝΟΛΟΓΙΑ ΤΡΟΦΙΜΩΝ": "Food Science and Technology",
        "ΔΙΟΙΚΗΣΗ ΕΠΙΧΕΙΡΗΣΕΩΝ": "Business Administration",
        "ΜΗΧΑΝΟΛΟΓΙΑ": "Mechanical Engineering",
        "ΜΗΧΑΝΙΚΩΝ": "Engineering",
        "Διάρκεια σύμβασης": "Agreement duration",
        "Καταληκτικές ημερομηνίες υποβολή αιτήσεων": "Application deadlines",
        "Χειμερινό Εξάμηνο": "Fall semester",
        "Χειμερινό εξάμηνο": "Fall semester",
        "Εαρινό Εξάμηνο": "Spring semester",
        "Εαρινό εξάμηνο": "Spring semester",
        "Εξερχόμενοι φοιτητές": "Outgoing students",
        "Μετακινήσεις φοιτητών": "Student mobilities",
        "Προπτυχιακό": "Undergraduate",
        "φοιτητές": "students",
        "φοιτητή": "student",
        "μήνες": "months",
        "έως": "until",
        " ή ": " or ",
        "Αλβανία": "Albania",
        "Αυστρία": "Austria",
        "Βέλγιο": "Belgium",
        "Βουλγαρία": "Bulgaria",
        "Γαλλία": "France",
        "Γερμανία": "Germany",
        "ΓΕΩΡΓΙΑ": "Georgia",
        "Γεωργία": "Georgia",
        "Ηνωμένα Αραβικά Εμιράτα": "United Arab Emirates",
        "ΗΠΑ": "United States",
        "Δανία": "Denmark",
        "Ελβετία": "Switzerland",
        "Εσθονία": "Estonia",
        "Ηνωμένο Βασίλειο": "United Kingdom",
        "Ιρλανδία": "Ireland",
        "Ισλανδία": "Iceland",
        "Ισπανία": "Spain",
        "Ισραήλ": "Israel",
        "Ιταλία": "Italy",
        "ΙΑΠΩΝΙΑ": "Japan",
        "ΙΝΔΙΑ": "India",
        "Ινδία": "India",
        "Ιορδανία": "Jordan",
        "Καζακστάν": "Kazakhstan",
        "Καναδάς": "Canada",
        "Κόσοβο": "Kosovo",
        "Κόστα Ρίκα": "Costa Rica",
        "Κροατία": "Croatia",
        "Κύπρος": "Cyprus",
        "ΚΙΝΑ": "China",
        "Κίνα": "China",
        "Λετονία": "Latvia",
        "Λευκορωσία": "Belarus",
        "Λίβανος": "Lebanon",
        "Λιθουανία": "Lithuania",
        "Μάλτα": "Malta",
        "Μαρόκο": "Morocco",
        "Μαδαγασκάρη": "Madagascar",
        "Μαυρίκιος": "Mauritius",
        "Μαυροβούνιο": "Montenegro",
        "ΜΑΛΑΙΣΙΑ": "Malaysia",
        "ΜΕΞΙΚΟ": "Mexico",
        "Μεξικό": "Mexico",
        "ΜΟΛΔΑΒΙΑ": "Moldova",
        "Μολδαβία": "Moldova",
        "Νέα Ζηλανδία": "New Zealand",
        "Νότια Αφρική": "South Africa",
        "Νορβηγία": "Norway",
        "Ολλανδία": "Netherlands",
        "ΟΥΚΡΑΝΙΑ": "Ukraine",
        "Ουκρανία": "Ukraine",
        "Ουγγαρία": "Hungary",
        "Πολωνία": "Poland",
        "Πορτογαλία": "Portugal",
        "Ρουμανία": "Romania",
        "Ρωσία": "Russia",
        "Σερβία": "Serbia",
        "Σρι Λάνκα": "Sri Lanka",
        "Σλοβακία": "Slovakia",
        "Σλοβενία": "Slovenia",
        "Σουηδία": "Sweden",
        "Τουρκία": "Turkey",
        "ΤΑΙΒΑΝ": "Taiwan",
        "Φιλιππίνες": "Philippines",
        "Τσεχία": "Czech Republic",
        "Τσεχική Δημοκρατία": "Czech Republic",
        "Φινλανδία": "Finland",
        "Βόρεια Μακεδονία": "North Macedonia",
        "Βιετνάμ": "Vietnam",
        "Βοσνία και Ερζεγοβίνη": "Bosnia and Herzegovina",
        "Βραζιλία": "Brazil",
        "Χιλή": "Chile",
    }
    for greek, english in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        text = text.replace(greek, english)
    return text


def _translate_greek_country_words(text: str) -> str:
    return _translate_greek_erasmus_terms(text)


def _replace_greek_latin_homoglyphs(text: str) -> str:
    if not text:
        return ""
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
            "ν": "v",
            "ο": "o",
            "ρ": "p",
            "τ": "t",
            "υ": "u",
            "χ": "x",
        }
    )
    return text.translate(replacements)
