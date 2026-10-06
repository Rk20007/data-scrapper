"""Public business-contact discovery.

Sources: the company's own website (contact/about/team/leadership pages) and public
search-result snippets. Email addresses are only stored when they are *published*;
we never guess or construct personal addresses."""

import logging
import re
from functools import lru_cache
from urllib.parse import urljoin, urlsplit

import dns.exception
import dns.resolver
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company, Contact, RoleCategory, utcnow
from app.services.ai import AIError, get_ai
from app.services.extraction import extract_page, registered_domain
from app.services.http import Fetcher, FetchError
from app.services.search import get_search_provider

log = logging.getLogger(__name__)

ROLE_PATTERNS: list[tuple[RoleCategory, re.Pattern]] = [
    (RoleCategory.PROJECT_HEAD, re.compile(r"project|projects|capex|expansion", re.I)),
    (RoleCategory.PURCHASE, re.compile(r"purchas|procure|sourcing|supply chain|buyer|materials|scm|commercial", re.I)),
    (RoleCategory.CIVIL_ENGINEERING, re.compile(r"civil|engineering|maintenance|infrastructure|facilit|estate|admin", re.I)),
    (RoleCategory.PLANT_HEAD, re.compile(r"plant|factory|works manager|unit head|site head|operations|manufacturing", re.I)),
    (RoleCategory.MANAGEMENT, re.compile(r"director|ceo|chief|managing|founder|president|chairman|owner|partner|\bcoo\b|\bcfo\b", re.I)),
]

MAILBOX_ROLES = {
    RoleCategory.PROJECT_HEAD: ("project", "projects", "capex"),
    RoleCategory.PURCHASE: ("purchase", "purchases", "procurement", "sourcing", "vendor", "vendors", "scm", "materials"),
    RoleCategory.CIVIL_ENGINEERING: ("civil", "engineering", "maintenance", "admin", "facility", "facilities"),
    RoleCategory.PLANT_HEAD: ("plant", "works", "factory"),
}
# Mailboxes that are the wrong audience for a contractor's pitch.
EXCLUDED_MAILBOXES = re.compile(
    r"^(hr|careers?|jobs|recruit\w*|resume|cv|sales|export|marketing|support|service|customercare|care|"
    r"grievance|complaints?|investor\w*|ir|cs|secretarial|noreply|no-reply|donotreply|webmaster|privacy|legal)\b",
    re.I,
)

CONTACT_PAGE_HINTS = ("contact", "about", "team", "leadership", "management", "board", "people", "reach-us", "locations")
CONTACT_PATHS = ("/contact", "/contact-us", "/contactus", "/about", "/about-us", "/leadership", "/management", "/team")

# Outreach priority: who should hear about a construction requirement first.
ROLE_PRIORITY = [
    RoleCategory.PROJECT_HEAD,
    RoleCategory.PURCHASE,
    RoleCategory.CIVIL_ENGINEERING,
    RoleCategory.PLANT_HEAD,
    RoleCategory.MANAGEMENT,
    RoleCategory.GENERIC,
    RoleCategory.OTHER,
]


def classify_role(title: str | None, email: str | None = None) -> str:
    if title:
        for role, pattern in ROLE_PATTERNS:
            if pattern.search(title):
                return role
    if email:
        local = email.split("@")[0].lower()
        for role, boxes in MAILBOX_ROLES.items():
            if any(local == b or local.startswith(b) for b in boxes):
                return role
        return RoleCategory.GENERIC if not title else RoleCategory.OTHER
    return RoleCategory.OTHER


def is_outreach_mailbox(email: str) -> bool:
    return not EXCLUDED_MAILBOXES.match(email.split("@")[0])


@lru_cache(maxsize=2048)
def _mx_ok(domain: str) -> bool | None:
    try:
        dns.resolver.resolve(domain, "MX", lifetime=8)
        return True
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        try:
            dns.resolver.resolve(domain, "A", lifetime=8)  # implicit MX
            return True
        except dns.exception.DNSException:
            return False
    except dns.exception.DNSException:
        return None  # resolver trouble: unknown, not invalid


def check_email_domain(email: str | None) -> str:
    if not email or "@" not in email:
        return "invalid"
    ok = _mx_ok(email.split("@", 1)[1].lower())
    return "mx_ok" if ok else ("invalid" if ok is False else "unknown")


def pick_best_contact(company: Company, is_suppressed) -> Contact | None:
    candidates = [
        c
        for c in company.contacts
        if c.email
        and not c.do_not_contact
        and c.email_status not in ("invalid", "bounced")
        and is_outreach_mailbox(c.email)
        and not is_suppressed(c.email)
    ]
    if not candidates:
        return None

    def key(c: Contact):
        named = 0 if (c.name and not c.is_generic) else 1
        try:
            rank = ROLE_PRIORITY.index(RoleCategory(c.role_category))
        except ValueError:
            rank = len(ROLE_PRIORITY)
        return (rank, named, -c.confidence)

    return sorted(candidates, key=key)[0]


def _candidate_pages(fetcher: Fetcher, website: str) -> list[str]:
    pages = [website]
    try:
        home = fetcher.get(website)
        ex = extract_page(home.text, str(home.url))
        host = urlsplit(str(home.url)).netloc
        for href, text in ex.links:
            if urlsplit(href).netloc != host:
                continue
            blob = f"{href} {text}".lower()
            if any(h in blob for h in CONTACT_PAGE_HINTS) and href not in pages:
                pages.append(href)
    except FetchError as exc:
        log.info("Homepage fetch failed for %s: %s", website, exc)
    for path in CONTACT_PATHS:
        url = urljoin(website, path)
        if url not in pages:
            pages.append(url)
    return pages[: settings.crawler_max_pages_per_site + 2]


def enrich_company_contacts(db: Session, fetcher: Fetcher, company: Company) -> int:
    """Discover public contacts for a company. Returns number of contacts added/updated."""
    from app.services.entities import add_named_contact

    ai = get_ai()
    touched = 0
    company_domain = company.domain

    if company.website:
        seen_texts: set[int] = set()
        for url in _candidate_pages(fetcher, company.website):
            try:
                resp = fetcher.get(url, retries=0)
            except FetchError:
                continue
            if "html" not in resp.headers.get("content-type", "html"):
                continue
            ex = extract_page(resp.text, str(resp.url))
            if hash(ex.text) in seen_texts:
                continue
            seen_texts.add(hash(ex.text))

            for email in ex.emails:
                dom = registered_domain(email)
                # only addresses on the company's own domain (avoid agency/web-designer emails)
                if company_domain and dom != company_domain:
                    continue
                if add_named_contact(db, company, None, None, email, str(resp.url)):
                    touched += 1

            people_page = any(h in str(resp.url).lower() for h in ("team", "leadership", "management", "board", "about", "people"))
            if ai.enabled and people_page and len(ex.text) > 200:
                try:
                    for p in ai.extract_people(company.name, ex.text)[:25]:
                        if add_named_contact(db, company, p.name, p.title, p.email, str(resp.url), phone=p.phone):
                            touched += 1
                except AIError as exc:
                    log.warning("People extraction failed for %s: %s", company.name, exc)

    # Public search snippets for decision makers (names/titles only — no emails invented).
    provider = get_search_provider(fetcher)
    if ai.enabled and provider.name != "none":
        where = company.cluster or " OR ".join(settings.target_clusters)
        query = (
            f'"{company.name}" ("plant head" OR "project head" OR "head projects" OR "purchase head" OR '
            f'"procurement head" OR "civil" OR "general manager") {where}'
        )
        try:
            results = provider.search(query, num=10)
        except FetchError as exc:
            log.warning("Contact search failed: %s", exc)
            results = []
        if results:
            text = "\n\n".join(f"[{i}] {r.title}\n{r.snippet}\nURL: {r.url}" for i, r in enumerate(results))
            try:
                people = ai.extract_people(company.name, text)
            except AIError:
                people = []
            for p in people[:10]:
                src = next((r.url for r in results if p.name.lower() in f"{r.title} {r.snippet}".lower()), None)
                if not src:
                    continue  # require the name to be visible in a specific result
                profile = src if "linkedin.com/in/" in src else None
                if add_named_contact(db, company, p.name, p.title, None, src, profile_url=profile):
                    touched += 1

    company.last_enriched_at = utcnow()
    db.flush()
    return touched
