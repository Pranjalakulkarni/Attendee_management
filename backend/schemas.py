"""
schemas.py
Pydantic models used for request validation and response shaping.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List


class AttendeeCreate(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    age: Optional[int] = Field(default=None, ge=0, le=120)
    gender: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    ticket_type: Optional[str] = "General"
    source: Optional[str] = "web_form"


class AttendeeUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    ticket_type: Optional[str] = None
    status: Optional[str] = None


class AttendeeOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    ticket_type: str
    source: str
    status: str
    registered_at: str
    checked_in: bool = False
    checkin_time: Optional[str] = None


class CheckinRequest(BaseModel):
    location: Optional[str] = "Main Entrance"
    method: Optional[str] = "manual"


class CheckinLookup(BaseModel):
    email: EmailStr
    location: Optional[str] = "Main Entrance"
    method: Optional[str] = "kiosk"


class BulkImportRecord(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    ticket_type: Optional[str] = "General"


class BulkImportRequest(BaseModel):
    source: str = "api_partner"
    records: List[BulkImportRecord]


class ImportResult(BaseModel):
    source: str
    received: int
    inserted: int
    duplicates: int
    errors: List[str] = []


# ==============================================================================
# Milestone 2: Venue & Speaker Operations
# ==============================================================================

class VenueCreate(BaseModel):
    name: str = Field(..., min_length=1)
    capacity: int = Field(..., gt=0)
    floor: Optional[str] = None
    amenities: Optional[List[str]] = []
    status: Optional[str] = "available"
    notes: Optional[str] = None


class VenueUpdate(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    floor: Optional[str] = None
    amenities: Optional[List[str]] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class VenueOut(BaseModel):
    id: int
    name: str
    capacity: int
    floor: Optional[str] = None
    amenities: List[str] = []
    status: str
    notes: Optional[str] = None


class SpeakerCreate(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    company: Optional[str] = None
    bio: Optional[str] = None
    expertise: Optional[List[str]] = []
    rating: Optional[float] = Field(default=4.5, ge=0, le=5)
    status: Optional[str] = "confirmed"


class SpeakerUpdate(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    bio: Optional[str] = None
    expertise: Optional[List[str]] = None
    rating: Optional[float] = None
    status: Optional[str] = None


class SpeakerOut(BaseModel):
    id: int
    name: str
    email: str
    company: Optional[str] = None
    bio: Optional[str] = None
    expertise: List[str] = []
    rating: float
    status: str
    upcoming_sessions: int = 0


class AvailabilityWindow(BaseModel):
    start_time: str
    end_time: str


class AvailabilityOut(AvailabilityWindow):
    id: int
    speaker_id: int


class SessionCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    track: Optional[str] = "General"
    start_time: str
    end_time: str
    expected_attendance: Optional[int] = Field(default=0, ge=0)
    required_amenities: Optional[List[str]] = []
    speaker_id: Optional[int] = None
    venue_id: Optional[int] = None
    preferred_topic: Optional[str] = None   # used by the Speaker Agent when speaker_id is omitted
    auto_assign: Optional[bool] = True      # let the Venue/Speaker Agents fill in gaps


class SessionUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    track: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    expected_attendance: Optional[int] = None
    required_amenities: Optional[List[str]] = None
    speaker_id: Optional[int] = None
    venue_id: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class SessionOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    track: str
    speaker_id: Optional[int] = None
    speaker_name: Optional[str] = None
    venue_id: Optional[int] = None
    venue_name: Optional[str] = None
    start_time: str
    end_time: str
    expected_attendance: int
    required_amenities: List[str] = []
    status: str
    notes: Optional[str] = None
    created_at: str
    assignment_notes: List[str] = []


# ==============================================================================
# Milestone 3: Sponsorship & Incident Management
# ==============================================================================

class SponsorCreate(BaseModel):
    name: str = Field(..., min_length=1)
    tier: Optional[str] = "Bronze"   # Platinum | Gold | Silver | Bronze
    industry: Optional[str] = None   # e.g. Technology, Finance, Healthcare - used for prospect search
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contract_value: Optional[float] = Field(default=0, ge=0)
    status: Optional[str] = "prospect"   # prospect | pending | confirmed | cancelled
    notes: Optional[str] = None


class SponsorUpdate(BaseModel):
    name: Optional[str] = None
    tier: Optional[str] = None
    industry: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    contract_value: Optional[float] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class SponsorOut(BaseModel):
    id: int
    name: str
    tier: str
    industry: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contract_value: float
    status: str
    notes: Optional[str] = None
    approached_at: Optional[str] = None
    created_at: str
    deliverables_total: int = 0
    deliverables_completed: int = 0
    engagement_totals: dict = {}


class SponsorApproachOut(BaseModel):
    sponsor: SponsorOut
    subject: str
    body: str


class DeliverableCreate(BaseModel):
    description: str = Field(..., min_length=1)
    status: Optional[str] = "pending"
    due_date: Optional[str] = None


class DeliverableUpdate(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None


class DeliverableOut(BaseModel):
    id: int
    sponsor_id: int
    description: str
    status: str
    due_date: Optional[str] = None


class EngagementLogCreate(BaseModel):
    metric_type: str = Field(..., pattern="^(booth_visits|leads|social_mentions|impressions)$")
    value: int = Field(..., gt=0)


class EngagementLogOut(BaseModel):
    id: int
    sponsor_id: int
    metric_type: str
    value: int
    logged_at: str


class IncidentCreate(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    category: Optional[str] = "Other"   # Medical | Security | Technical | Logistics | Other
    severity: Optional[str] = "low"      # low | medium | high | critical
    location: Optional[str] = None
    reported_by: Optional[str] = None
    assigned_to: Optional[str] = None


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None


class IncidentOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    category: str
    severity: str
    location: Optional[str] = None
    status: str
    reported_by: Optional[str] = None
    assigned_to: Optional[str] = None
    created_at: str
    updated_at: str
    resolved_at: Optional[str] = None
    open_minutes: Optional[int] = None
    auto_escalated: bool = False
