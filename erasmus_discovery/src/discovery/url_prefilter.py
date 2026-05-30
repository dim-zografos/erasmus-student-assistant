from typing import List, Tuple
from urllib.parse import unquote, urlparse

from ..storage.database import get_discovered_urls, log_event, update_discovered_prefilter


ERASMUS_KEYWORDS = [
    "erasmus",
    "erasmus+",
    "mobility",
    "outgoing",
    "incoming",
    "studies",
    "student mobility",
    "student exchange",
    "exchange students",
    "study abroad",
    "mobility for studies",
    "mobility for traineeships",
    "partner universities",
    "partner institutions",
    "host universities",
    "host institution",
    "partners",
    "agreements",
    "bilateral",
    "bilateral agreements",
    "inter-institutional",
    "interinstitutional",
    "inter-institutional agreements",
    "learning agreement",
    "online learning agreement",
    "ola",
    "deadline",
    "application",
    "application form",
    "application procedure",
    "call for applications",
    "open call",
    "traineeship",
    "placement",
    "internship",
    "grant",
    "scholarship",
    "funding",
    "nomination",
    "selection results",
    "eligible students",
    "academic coordinator",
    "departmental coordinator",
    "ects",
    "transcript of records",
    "international office",
    "international relations office",
    "ερασμος",
    "έρασμος",
    "erasmus plus",
    "κινητικότητα",
    "κινητικότητας",
    "κινητικοτητα",
    "σπουδές",
    "σπουδων",
    "σπουδών",
    "φοιτητές",
    "φοιτητων",
    "φοιτητών",
    "εξερχόμενοι",
    "εισερχόμενοι",
    "συνεργαζόμενα",
    "ιδρύματα",
    "πανεπιστήμια υποδοχής",
    "ιδρύματα υποδοχής",
    "συμφωνίες",
    "συμφωνια",
    "συμφωνία",
    "διμερείς",
    "διμερείς συμφωνίες",
    "προκήρυξη",
    "προκηρυξη",
    "προκηρύξεις",
    "αιτήσεις",
    "αίτηση",
    "αιτηση",
    "προθεσμία",
    "προθεσμιες",
    "προθεσμίες",
    "πρακτική",
    "πρακτικη",
    "πρακτική άσκηση",
    "δικαιολογητικά",
    "δικαιολογητικα",
    "επιχορήγηση",
    "επιχορηγηση",
    "υποτροφία",
    "υποτροφια",
    "αποτελέσματα επιλογής",
    "ακαδημαϊκός συντονιστής",
    "τμηματικός συντονιστής",
    "πιστωτικές μονάδες",
    "αναλυτική βαθμολογία",
    "γραφείο διεθνών σχέσεων",
]


def score_url(url: str, title: str = "") -> Tuple[int, List[str]]:
    parsed = urlparse(url)
    # The configured Erasmus sites often have "erasmus" in the hostname.
    # Scoring only path/query/title avoids making every URL a candidate.
    url_text = f"{parsed.path} {parsed.query}"
    haystack = unquote(f"{url_text} {title}").lower().replace("-", " ").replace("_", " ")
    matched: List[str] = []
    score = 0

    if parsed.path in {"", "/"} and "erasmus" in parsed.netloc.lower():
        matched.append("erasmus")
        score += 30

    for keyword in ERASMUS_KEYWORDS:
        key = keyword.lower()
        if key in haystack:
            matched.append(keyword)
            if key in {"erasmus", "erasmus+", "ερασμος", "έρασμος"}:
                score += 30
            elif "agreement" in key or "partner" in key or "συμφων" in key or "ιδρύματα" in key:
                score += 25
            else:
                score += 15

    return min(score, 100), matched


def prefilter_urls(conn, university_key: str = "", min_score: int = 10) -> None:
    rows = get_discovered_urls(conn, university_key or None)
    candidates = 0
    ignored = 0

    for row in rows:
        score, matched = score_url(row["url"], row["title"] or "")
        status = "candidate" if score >= min_score else "ignored"
        update_discovered_prefilter(conn, row["url"], ", ".join(matched), score, status)
        if status == "candidate":
            candidates += 1
        else:
            ignored += 1

    log_event(
        conn,
        "prefilter",
        "ok",
        f"Marked {candidates} candidate URLs and {ignored} ignored URLs",
        university_key,
    )
