from typing import Optional
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "awwwards-jobs-scraper",
        "version": "0.1.0",
        "source_reachable": True
    }

@router.get("/jobs")
async def get_jobs(
    page: int = Query(default=1, ge=1),
    include: str = Query(default="details", pattern="^(details|list)$"),
    category: Optional[str] = None,
    type: Optional[str] = Query(default=None, alias="type"),
    country: Optional[str] = None,
    remote: Optional[bool] = None,
    sort: Optional[str] = Query(default=None, pattern="^-?posted_at$"),
):
    # Tymczasowy stub – w Kroku 4 podłączymy scraper
    return {
        "meta": {
            "source": "https://www.awwwards.com/jobs/",
            "page": page,
            "has_next": False,
            "next_page": None,
            "total_text": None
        },
        "data": []
    }

@router.get("/jobs/{id}")
async def get_job_by_id(id: str):
    # Tymczasowy stub – w Kroku 4 podłączymy scraper
    raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"Job not found: {id}"})
