from dataclasses import dataclass, field
from typing import List


@dataclass
class UniversityConfig:
    key: str
    name: str
    country: str
    city: str
    base_erasmus_url: str
    allowed_domains: List[str]
    enabled: bool = True


@dataclass
class BaseUrl:
    university_key: str
    base_url: str
    allowed_domains: List[str] = field(default_factory=list)
    enabled: bool = True
    id: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class DiscoveredUrl:
    university_key: str
    url: str
    base_url_id: int = 0
    title: str = ""
    content_type: str = ""
    depth: int = 0
    discovered_from: str = ""
    matched_keywords: str = ""
    url_score: int = 0
    status: str = "discovered"
    discovered_at: str = ""


@dataclass
class UrlClassification:
    university_key: str
    url: str
    base_url_id: int = 0
    title: str = ""
    snippet: str = ""
    selected: bool = False
    category: str = "irrelevant"
    relevance_score: int = 0
    reason: str = ""
    expected_data: List[str] = field(default_factory=list)
    priority: str = "low"
    classified_at: str = ""


@dataclass
class SelectedUrl:
    university_key: str
    url: str
    base_url_id: int = 0
    title: str = ""
    content_type: str = ""
    category: str = ""
    relevance_score: int = 0
    reason: str = ""
    expected_data: List[str] = field(default_factory=list)
    priority: str = "low"
    status: str = "approved"
    selected_at: str = ""
    id: int = 0


@dataclass
class ScrapedDocument:
    university_key: str
    university_name: str
    source_url: str
    selected_url_id: int = 0
    title: str = ""
    category: str = ""
    cleaned_content: str = ""
    document_type: str = ""
    key_topics: List[str] = field(default_factory=list)
    contains_agreements: bool = False
    contains_deadlines: bool = False
    contains_requirements: bool = False
    scraped_at: str = ""
    content_hash: str = ""
    id: int = 0


@dataclass
class ErasmusAgreement:
    document_id: int
    home_university_key: str
    home_university: str
    partner_university: str
    source_url: str
    department: str = ""
    partner_country: str = ""
    deadline: str = ""
    academic_year: str = ""
    evidence_text: str = ""
    confidence: str = ""
    extracted_at: str = ""
    row_hash: str = ""
    id: int = 0


@dataclass
class AgreementCandidate:
    document_id: int
    home_university_key: str
    home_university: str
    partner_university: str
    source_url: str
    department: str = ""
    partner_country: str = ""
    deadline: str = ""
    academic_year: str = ""
    evidence_text: str = ""
    confidence: str = ""
    reason: str = ""
    extracted_at: str = ""
    id: int = 0


@dataclass
class PipelineLog:
    step: str
    university_key: str = ""
    url: str = ""
    status: str = ""
    message: str = ""
    created_at: str = ""
