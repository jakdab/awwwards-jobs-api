from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Iterable
import asyncio
import re
import json

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import settings

JOBS_BASE = "https://www.awwwards.com/jobs/"

class ScrapeError(Exception):
    pass

class AwwwardsScraper:
    def __init__(self, base_url: str | None = None, timeout: float | None = None, concurrency: int = 5):
        self.base_url = (base_url or settings.SOURCE_URL).rstrip("/") + "/"
        self.timeout = timeout or settings.REQUEST_TIMEOUT
        self._sem = asyncio.Semaphore(concurrency)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.6, min=0.6, max=4),
        retry=retry_if_exception_type(httpx.HTTPError),
    )
    async def _get_text(self, client: httpx.AsyncClient, url: str) -> str:
        async with self._sem:
            r = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; AwwwardsJobsBot/0.1; +https://example.com/bot)"
            })
            r.raise_for_status()
            return r.text

    def _full_url(self, href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return "https://www.awwwards.com" + href
        return JOBS_BASE + href

    def _slug_from_url(self, url: str) -> str:
        # https://www.awwwards.com/jobs/ux-strategist-lewiston.html -> ux-strategist-lewiston
        m = re.search(r"/jobs/([^/?#]+)\.html", url)
        return m.group(1) if m else url.rstrip("/").split("/")[-1]

    # ---------- LIST PAGE ----------
    async def list_page(self, page: int = 1, **filters) -> Tuple[str, Dict[str, Any]]:
        # Na MVP wspieramy tylko page (filtry dołożymy później).
        url = self.base_url if page == 1 else f"{self.base_url}?page={page}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            html = await self._get_text(client, url)

        soup = BeautifulSoup(html, "html.parser")

        # has_next / next_page
        has_next, next_page = False, None
        # typowa paginacja – link z tekstem "Next" lub rel="next"
        next_a = soup.find("a", string=re.compile(r"^\s*Next\s*$", re.I)) or soup.find("a", rel="next")
        if next_a and next_a.get("href"):
            has_next = True
            # spróbuj wyciągnąć numer ze ścieżki
            m = re.search(r"[?&]page=(\d+)", next_a["href"])
            next_page = int(m.group(1)) if m else page + 1

        # "X job opportunities waiting." (jeśli dostępne)
        total_text = None
        total_el = soup.find(string=re.compile(r"job opportunities", re.I))
        if total_el:
            total_text = total_el.strip()

        meta = {
            "has_next": has_next,
            "next_page": next_page,
            "total_text": total_text,
        }
        return html, meta

    def _extract_job_urls_from_list(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # heurystyka: wszystkie linki do /jobs/*.html
            if re.search(r"/jobs/[^/]+\.html(\?.*)?$", href):
                full = self._full_url(href)
                urls.append(full)
        # dedupe zachowując kolejność
        seen = set()
        uniq = []
        for u in urls:
            if u not in seen:
                uniq.append(u)
                seen.add(u)
        return uniq

    # ---------- DETAILS PAGE ----------
    def _first_json(self, s: str) -> Optional[dict]:
        try:
            data = json.loads(s)
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                # weź pierwszy słownik
                for item in data:
                    if isinstance(item, dict):
                        return item
        except Exception:
            return None
        return None

    def _pick_jobposting(self, scripts: Iterable[str]) -> Optional[dict]:
        for s in scripts:
            data = self._first_json(s)
            if not isinstance(data, dict):
                continue
            # Bezpośrednio JobPosting
            if data.get("@type") == "JobPosting":
                return data
            # Albo w grafie
            graph = data.get("@graph")
            if isinstance(graph, list):
                for node in graph:
                    if isinstance(node, dict) and node.get("@type") == "JobPosting":
                        return node
        return None

    def _clean_text(self, x: Optional[str]) -> Optional[str]:
        if x is None:
            return None
        return re.sub(r"\s+", " ", str(x)).strip() or None

    def _norm_date(self, d: Optional[str]) -> Optional[str]:
        # jeśli datePosted w ISO, to utnij do YYYY-MM-DD
        if not d:
            return None
        m = re.match(r"(\d{4}-\d{2}-\d{2})", d)
        if m:
            return m.group(1)
        return d  # zostaw jak jest, jeśli nie rozpoznajemy

    async def job_details(self, client: httpx.AsyncClient, job_url: str) -> Dict[str, Any]:
        html = await self._get_text(client, job_url)
        soup = BeautifulSoup(html, "html.parser")

        # 1) JSON-LD JobPosting – najpewniejsze
        ld_scripts = [tag.get_text(strip=False) for tag in soup.find_all("script", type="application/ld+json")]
        job = self._pick_jobposting(ld_scripts) or {}

        title = self._clean_text(job.get("title")) or self._clean_text((soup.find("h1") or {}).get_text() if soup.find("h1") else None)
        org = job.get("hiringOrganization") or {}
        company_name = self._clean_text(org.get("name"))
        company_website = self._clean_text(org.get("sameAs") or org.get("url"))

        apply_url = self._clean_text(job.get("hiringOrganization", {}).get("url") or job.get("applicationContact") or job.get("url"))
        # Jeżeli nie ma w JSON-LD, spróbuj anchor z tekstem "More info" lub "Apply"
        if not apply_url:
            anchor = soup.find("a", string=re.compile(r"(More info|Apply)", re.I))
            if anchor and anchor.get("href"):
                apply_url = self._full_url(anchor["href"])

        # Lokalizacja / kraj
        country = None
        location_label = None
        remote = None
        loc = job.get("jobLocation")
        if isinstance(loc, list) and loc:
            loc = loc[0]
        if isinstance(loc, dict):
            addr = loc.get("address", {})
            country = self._clean_text(addr.get("addressCountry"))
            city = self._clean_text(addr.get("addressLocality"))
            location_label = city or self._clean_text(loc.get("name"))
        # dodatkowa heurystyka na "REMOTE"
        if job.get("applicantLocationRequirements") or (location_label and "remote" in location_label.lower()):
            remote = True
        if location_label and location_label.upper() == "REMOTE":
            remote = True

        employment_type = self._clean_text(job.get("employmentType"))
        category = self._clean_text(job.get("occupationalCategory"))  # może być None; Awwwards często ma "Design"/"Programming" w UI
        posted_at = self._norm_date(self._clean_text(job.get("datePosted")))
        # opis (zwykle HTML w JSON-LD)
        description_html = job.get("description")
        if description_html and isinstance(description_html, str):
            description_html = description_html.strip()
        # plain text fallback
        description_text = None
        if description_html:
            # usuń znaczniki w prosty sposób
            description_text = BeautifulSoup(description_html, "html.parser").get_text(separator=" ").strip()
        else:
            # fallback: główna treść strony (ostrożnie)
            article = soup.find("article") or soup.find("div", class_=re.compile(r"(job|content)", re.I))
            if article:
                description_text = article.get_text(separator=" ").strip()

        item = {
            "id": self._slug_from_url(job_url),
            "title": title or "",
            "company_name": company_name,
            "company_website": company_website,
            "category": category,
            "country": country,
            "employment_type": employment_type,
            "location_label": location_label,
            "remote": remote,
            "awwwards_url": job_url,
            "apply_url": apply_url,
            "posted_at": posted_at,
            "posted_at_relative": None,  # względna data zwykle jest tylko na liście – opcjonalnie dołożymy później
            "description_text": description_text,
            "description_html": description_html,
        }
        return item

    async def list_with_details(self, page: int = 1, **filters) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        html, meta = await self.list_page(page=page, **filters)
        job_urls = self._extract_job_urls_from_list(html)
        if not job_urls:
            return [], meta

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            results = await asyncio.gather(*[self.job_details(client, url) for url in job_urls], return_exceptions=True)

        data: List[Dict[str, Any]] = []
        for res in results:
            if isinstance(res, Exception):
                # Pomijamy pojedyncze błędy (np. jedna strona padła), reszta przejdzie
                continue
            data.append(res)
        return data, meta

    async def list_only(self, page: int = 1, **filters) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Opcjonalnie: same dane z listy (bez wejścia w szczegóły).
        Na razie zwracamy tylko URL-e i tytuł jeśli da się pewnie wyciągnąć.
        """
        html, meta = await self.list_page(page=page, **filters)
        urls = self._extract_job_urls_from_list(html)
        items = []
        soup = BeautifulSoup(html, "html.parser")
        href_to_title: Dict[str, str] = {}
        for a in soup.find_all("a", href=True):
            if re.search(r"/jobs/[^/]+\.html(\?.*)?$", a["href"]):
                href_to_title[self._full_url(a["href"])] = a.get_text(strip=True)
        for u in urls:
            items.append({
                "id": self._slug_from_url(u),
                "title": href_to_title.get(u) or "",
                "awwwards_url": u,
            })
        return items, meta
