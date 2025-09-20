from typing import List, Optional, Literal
from pydantic import BaseModel, HttpUrl

class Meta(BaseModel):
    source: HttpUrl
    page: int
    has_next: bool
    next_page: Optional[int] = None
    total_text: Optional[str] = None

class JobBase(BaseModel):
    id: str
    title: str
    company_name: Optional[str] = None
    company_website: Optional[HttpUrl] = None
    category: Optional[str] = None
    country: Optional[str] = None
    employment_type: Optional[str] = None
    location_label: Optional[str] = None
    remote: Optional[bool] = None
    awwwards_url: HttpUrl
    posted_at: Optional[str] = None
    posted_at_relative: Optional[str] = None

class JobDetails(JobBase):
    apply_url: Optional[HttpUrl] = None
    description_text: Optional[str] = None
    description_html: Optional[str] = None

class JobsResponse(BaseModel):
    meta: Meta
    data: List[JobDetails]

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    app: str
    version: str
    source_reachable: bool

class ErrorResponse(BaseModel):
    error: str
    message: str
