from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from .config import settings
from .models import JobsResponse, JobDetails, Meta, ErrorResponse
from .scraper import AwwwardsScraper, ScrapeError

router = APIRouter()

@router.head("/jobs")
async def head_jobs():
    return Response(status_code=200)

@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "source_reachable": True
    }


@router.get("/jobs", response_model=JobsResponse, responses={400: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def get_jobs(
    page: int = Query(default=1, ge=1),
    include: str = Query(default="details", pattern="^(details|list)$"),
    category: Optional[str] = None,
    type: Optional[str] = Query(default=None, alias="type"),
    country: Optional[str] = None,
    remote: Optional[bool] = None,
    sort: Optional[str] = Query(default=None, pattern="^-?posted_at$"),
):
    scraper = AwwwardsScraper()
    try:
        if include == "list":
            data, meta = await scraper.list_only(page=page, category=category, type_=type, country=country, remote=remote)
        else:
            data, meta = await scraper.list_with_details(page=page, category=category, type_=type, country=country, remote=remote)

        # sortowanie po dacie (gdy mamy posted_at)
        if sort and data:
            reverse = sort.startswith("-")
            key = sort.lstrip("-")
            if key == "posted_at":
                data.sort(key=lambda x: x.get("posted_at") or "", reverse=reverse)

        return {
            "meta": {
                "source": settings.SOURCE_URL,
                "page": page,
                "has_next": bool(meta.get("has_next")),
                "next_page": meta.get("next_page"),
                "total_text": meta.get("total_text"),
            },
            "data": data
        }
    except ScrapeError as e:
        raise HTTPException(status_code=503, detail={"error": "source_unreachable", "message": str(e)})
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "scrape_failed", "message": str(e)})

@router.get("/jobs/{id}", response_model=JobDetails, responses={404: {"model": ErrorResponse}})
async def get_job_by_id(id: str):
    scraper = AwwwardsScraper()
    job_url = f"https://www.awwwards.com/jobs/{id}.html"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=scraper.timeout) as client:
            details = await scraper.job_details(client, job_url)
        if not details or not details.get("title"):
            raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Job not found: {id}"})
        return details
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": "scrape_failed", "message": str(e)})
