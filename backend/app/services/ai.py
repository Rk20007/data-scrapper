"""OpenAI-powered classification, extraction and email writing (structured outputs)."""

import logging
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.config import settings
from app.services.extraction import truncate

log = logging.getLogger(__name__)

ProjectType = Literal["factory", "warehouse", "peb", "civil", "construction", "expansion", "epc", "industrial_park", "other"]
Stage = Literal[
    "announced", "planning", "land_acquired", "approved", "tendering", "under_construction", "completed", "unknown"
]


class AIError(Exception):
    pass


# ---------------------------------------------------------------- schemas
# Structured-output schemas: every field is required (nullable where optional), no defaults.


class MentionedPerson(BaseModel):
    name: str
    title: str | None
    email: str | None


class ProjectClassification(BaseModel):
    is_relevant: bool
    is_current: bool
    reason: str
    opportunity_kind: Literal["private_project", "tender", "none"]
    company_name: str | None
    company_website: str | None
    project_title: str | None
    project_type: ProjectType
    stage: Stage
    location_text: str | None
    cluster: str | None
    investment_inr_crore: float | None
    area_sqft: float | None
    expected_timeline: str | None
    announcement_date: str | None
    tender_ref: str | None
    tender_authority: str | None
    tender_closing_date: str | None
    tender_value_inr: float | None
    key_facts: list[str]
    confidence: float
    people_mentioned: list[MentionedPerson]


class CompanyAssessment(BaseModel):
    industry: str | None
    size_tier: Literal["large", "mid", "small", "unknown"]
    employee_estimate: int | None
    is_quality: bool
    reason: str


class DiscoveredCompany(BaseModel):
    name: str
    website: str | None
    cluster: str | None
    industry: str | None
    evidence: str


class DiscoveredCompanies(BaseModel):
    companies: list[DiscoveredCompany]


class ExtractedPerson(BaseModel):
    name: str
    title: str
    email: str | None
    phone: str | None


class ExtractedPeople(BaseModel):
    people: list[ExtractedPerson]


class GeneratedEmail(BaseModel):
    subject: str
    body: str
    facts_referenced: list[str]


class ReplyClassification(BaseModel):
    classification: Literal["interested", "question", "not_interested", "unsubscribe", "out_of_office", "bounce", "other"]
    summary: str


# ---------------------------------------------------------------- prompts

CLASSIFY_SYSTEM = """You are an analyst for an industrial construction contractor (PEB, civil, factory and warehouse \
construction, EPC) operating ONLY in these Rajasthan industrial clusters: {clusters} (Khairthal-Tijara / Alwar / \
Kotputli-Behror districts, incl. Chopanki, Pathredi, Kahrani, Ghiloth, Shahjahanpur, Majrakath, Sotanala).

Decide whether the document reveals a construction opportunity there:
- New factory/plant/unit, warehouse/logistics park, PEB shed, civil works, capacity expansion, EPC package, \
industrial park infrastructure, land allotment with intent to build, or a public tender for such works.

Rules (strict):
- Use ONLY facts stated in the document. Never guess figures, names, dates or locations. Use null when not stated.
- is_relevant = true only if the opportunity is located in (or explicitly planned for) one of the clusters above \
AND involves physical construction/expansion work a contractor could bid for.
- is_current = true only if the work is still upcoming or ongoing as of {today}: not completed/inaugurated, \
not cancelled, and the source information is not stale (announcements older than ~18 months with no newer \
progress are NOT current). Tenders are current only if the closing date has not passed (or is not stated and the \
notice looks recent).
- cluster must be exactly one of {clusters} or null.
- opportunity_kind: "tender" for a public procurement notice (RIICO, PWD, NIC e-proc, CPPP etc.), \
"private_project" for a company's own project, "none" otherwise.
- key_facts: 1-6 short factual statements copied or closely paraphrased from the document (these will be shown as \
evidence and used in outreach emails, so they must be verifiable from the text).
- investment_inr_crore: convert only explicit amounts (e.g. "Rs 500 crore" -> 500; "$10 million" -> null unless INR given).
- people_mentioned: only people named in the text with their stated designation (and email only if printed).
- confidence: 0.0-1.0, how sure you are about relevance + currency given the evidence quality.
- Dates as YYYY-MM-DD when determinable, else null."""

ASSESS_SYSTEM = """You assess whether an industrial company is a worthwhile B2B prospect for an industrial \
construction contractor. "Quality" means an established manufacturer / logistics operator / MNC / listed or \
large-group company with real facilities (typically 100+ employees or significant turnover), not a trader, \
broker, directory listing, or tiny workshop. Use only the provided text; if unclear, use size_tier "unknown" and \
is_quality false."""

DISCOVER_SYSTEM = """Extract industrial companies (manufacturers, warehouses/logistics operators, industrial \
developers) that operate or plan facilities in {clusters}. Exclude directories, news publishers, government \
bodies, real-estate brokers, job portals and construction contractors. Only include companies named in the text. \
Website only if explicitly present. cluster must be one of {clusters} or null."""

PEOPLE_SYSTEM = """Extract people named on this company web page together with their exact job title as printed. \
Include only people whose title is shown. Include an email/phone only if it is printed next to that person. \
Never infer or construct email addresses."""

EMAIL_SYSTEM = """You write short, professional, personalised B2B cold emails for an Indian industrial \
construction company. Hard rules:
- Use ONLY the facts in PROJECT_FACTS and SENDER. Never invent numbers, dates, names, clients, certifications, \
or claims. Do not exaggerate. If a fact is not provided, do not mention it.
- Refer to the project the way the source describes it; mention the source type naturally (e.g. "I read that…").
- 90-150 words, plain text, no markdown, no emojis, no attachments mentioned, no fake urgency.
- One clear, low-friction call to action (a short call or site visit discussion).
- Greeting: use the contact's name if given, otherwise address the role/team.
- Do NOT include a signature or unsubscribe text; it is appended automatically.
- Subject: specific, under 70 characters, no clickbait, no ALL CAPS."""

FOLLOWUP_SYSTEM = EMAIL_SYSTEM + """
This is follow-up #{step}. Keep it to 40-80 words, polite, reference the earlier email briefly, add no new claims. \
For the final follow-up, say you will not follow up further. The subject must be "Re: " + the original subject."""

REPLY_SYSTEM = """Classify a reply to a B2B outreach email.
- interested: wants to talk/meet/receive a quote or details.
- question: asks something without clear interest/decline.
- not_interested: declines, already has a vendor, no requirement.
- unsubscribe: asks to stop emailing / remove from list.
- out_of_office: auto-reply / away notice.
- bounce: delivery failure notification.
- other: anything else.
Summarise in one sentence."""


# ---------------------------------------------------------------- service


class AIService:
    def __init__(self):
        self._client = None
        if settings.openai_api_key:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.openai_api_key, timeout=90, max_retries=3)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _parse(self, system: str, user: str, schema: type[BaseModel], temperature: float = 0.1):
        if not self._client:
            raise AIError("OpenAI is not configured")
        try:
            resp = self._client.chat.completions.parse(
                model=settings.openai_model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format=schema,
                temperature=temperature,
            )
        except Exception as exc:  # network / API errors
            raise AIError(str(exc)) from exc
        msg = resp.choices[0].message
        if msg.refusal or msg.parsed is None:
            raise AIError(f"Model refused or returned no parse: {msg.refusal}")
        return msg.parsed

    @staticmethod
    def _clusters() -> str:
        return ", ".join(settings.target_clusters)

    def classify_document(
        self, *, title: str, url: str, text: str, published_at: str | None, source_kind: str, company_hint: str | None
    ) -> ProjectClassification:
        system = CLASSIFY_SYSTEM.format(clusters=self._clusters(), today=date.today().isoformat())
        user = (
            f"SOURCE_KIND: {source_kind}\nURL: {url}\nPUBLISHED: {published_at or 'unknown'}\n"
            f"COMPANY_HINT: {company_hint or 'none'}\nTITLE: {title}\n\nDOCUMENT:\n"
            f"{truncate(text, settings.openai_max_input_chars)}"
        )
        result = self._parse(system, user, ProjectClassification)
        if result.cluster not in settings.target_clusters:
            result.cluster = None
        result.confidence = max(0.0, min(1.0, result.confidence))
        return result

    def assess_company(self, name: str, text: str) -> CompanyAssessment:
        user = f"COMPANY: {name}\n\nPUBLIC INFORMATION:\n{truncate(text, 8000)}"
        return self._parse(ASSESS_SYSTEM, user, CompanyAssessment)

    def discover_companies(self, text: str) -> list[DiscoveredCompany]:
        system = DISCOVER_SYSTEM.format(clusters=self._clusters())
        result = self._parse(system, truncate(text, settings.openai_max_input_chars), DiscoveredCompanies)
        for c in result.companies:
            if c.cluster not in settings.target_clusters:
                c.cluster = None
        return result.companies

    def extract_people(self, company: str, text: str) -> list[ExtractedPerson]:
        user = f"COMPANY: {company}\n\nPAGE TEXT:\n{truncate(text, 10000)}"
        people = self._parse(PEOPLE_SYSTEM, user, ExtractedPeople).people
        low = text.lower()
        for p in people:  # enforce: email must be printed verbatim on the page
            if p.email and p.email.lower() not in low:
                p.email = None
        return people

    def write_email(self, *, facts: dict, sender: dict, contact: dict, followup_step: int = 0,
                    original_subject: str | None = None) -> GeneratedEmail:
        system = FOLLOWUP_SYSTEM.format(step=followup_step) if followup_step else EMAIL_SYSTEM
        user = (
            f"PROJECT_FACTS:\n{_fmt(facts)}\n\nCONTACT:\n{_fmt(contact)}\n\nSENDER:\n{_fmt(sender)}"
            + (f"\n\nORIGINAL_SUBJECT: {original_subject}" if original_subject else "")
        )
        return self._parse(system, user, GeneratedEmail, temperature=0.4)

    def classify_reply(self, subject: str, body: str) -> ReplyClassification:
        return self._parse(REPLY_SYSTEM, f"SUBJECT: {subject}\n\nBODY:\n{truncate(body, 4000)}", ReplyClassification)


def _fmt(d: dict) -> str:
    lines = []
    for k, v in d.items():
        if v in (None, "", []):
            continue
        if isinstance(v, list):
            v = "; ".join(str(x) for x in v)
        lines.append(f"- {k}: {v}")
    return "\n".join(lines) or "- (none)"


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def unsupported_numbers(text: str, *allowed_sources: str) -> list[str]:
    """Numbers in `text` that do not appear in any allowed source — a hallucination guard for emails."""
    pool = " ".join(allowed_sources).replace(",", "")
    bad = []
    for n in _NUM_RE.findall(text):
        plain = n.replace(",", "").rstrip(".")
        if len(plain) == 1:  # tiny numbers ("2 minutes", "1 call") are harmless
            continue
        if plain not in pool:
            bad.append(n)
    return bad


_ai: AIService | None = None


def get_ai() -> AIService:
    global _ai
    if _ai is None:
        _ai = AIService()
    return _ai
