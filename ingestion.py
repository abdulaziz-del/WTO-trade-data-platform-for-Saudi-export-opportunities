"""
Data Ingestion API Endpoints
Triggers and monitors WTO data pipeline runs.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_role
from app.models.user import User
from app.services.wto_connectors.wto_api_client import WTOAPIClient
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post("/run/notifications")
async def ingest_notifications(
    background_tasks: BackgroundTasks,
    days_back: int = 30,
    domain_ids: Optional[str] = "1,2",   # "1"=TBT, "2"=SPS, "1,2"=both
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """
    Trigger ingestion of TBT/SPS notifications from ePing.
    Runs in background; returns job_id for status polling.
    """
    domains = [int(d) for d in domain_ids.split(",")]
    background_tasks.add_task(_ingest_notifications_task, days_back, domains, db)
    return {"status": "queued", "source": "ePing", "days_back": days_back}


@router.post("/run/qrs")
async def ingest_qrs(
    background_tasks: BackgroundTasks,
    member_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """Trigger ingestion of quantitative restrictions data."""
    background_tasks.add_task(_ingest_qrs_task, member_code, db)
    return {"status": "queued", "source": "QRS"}


@router.post("/run/timeseries")
async def ingest_timeseries(
    background_tasks: BackgroundTasks,
    indicators: str = "HS_X_0040,TRF_0010",
    reporter: str = "682",          # 682 = Saudi Arabia
    year: int = 2023,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """Trigger ingestion of WTO time-series trade statistics."""
    background_tasks.add_task(_ingest_timeseries_task, indicators, reporter, year, db)
    return {"status": "queued", "source": "TimeSeries", "reporter": reporter}


@router.get("/preview/notifications")
async def preview_notifications(
    days_back: int = 7,
    hs: Optional[str] = None,
    free_text: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """
    Live preview of ePing notifications (no DB write).
    Useful for testing API connectivity.
    """
    async with WTOAPIClient() as wto:
        from datetime import date, timedelta
        from_date = (date.today() - timedelta(days=days_back)).isoformat()
        data = await wto.eping_search_notifications(
            domain_ids=[1, 2],
            distribution_date_from=from_date,
            hs=hs,
            free_text=free_text,
            page=page,
            page_size=page_size,
        )
    return data


@router.get("/preview/qrs")
async def preview_qrs(
    member_code: Optional[str] = None,
    product_codes: Optional[str] = None,
    in_force_only: bool = True,
    page: int = 1,
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """Live preview of quantitative restrictions (no DB write)."""
    async with WTOAPIClient() as wto:
        data = await wto.qrs_list(
            reporter_member_code=member_code,
            in_force_only=in_force_only,
            product_codes=product_codes,
            page=page,
        )
    return data


@router.get("/preview/timeseries")
async def preview_timeseries(
    indicators: str = "HS_X_0040",
    reporters: str = "682",
    partners: str = "000",
    periods: str = "2023",
    products: Optional[str] = None,
    max_records: int = 50,
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """
    Live preview of WTO time-series data.
    Default: Saudi Arabia (682) exports to World (000).
    """
    async with WTOAPIClient() as wto:
        data = await wto.ts_data(
            indicators=indicators,
            reporters=reporters,
            partners=partners,
            periods=periods,
            products=products,
            max_records=max_records,
        )
    return data


@router.get("/preview/saudi-export-profile")
async def preview_saudi_export_profile(
    hs_codes: str = "270900,290110,310210",  # Crude oil, Ethylene, Ammonium nitrate
    target_countries: str = "156,356,276",   # China, India, Germany
    year: int = 2023,
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """
    Compound query: Saudi export profile for given HS codes + target markets.
    Aggregates TS data, tariffs, QRs, and ePing notifications.
    """
    async with WTOAPIClient() as wto:
        data = await wto.get_saudi_export_profile(
            hs_codes=hs_codes.split(","),
            target_country_codes=target_countries.split(","),
            year=year,
        )
    return data


@router.get("/preview/tfad")
async def preview_tfad(
    countries: Optional[str] = "SAU,ARE,KWT,BHR,QAT,OMN",
    current_user: User = Depends(require_role(["ADMIN", "ANALYST"])),
):
    """Trade facilitation single-window data for GCC countries."""
    async with WTOAPIClient() as wto:
        data = await wto.tfad_procedures_single_window(
            countries=countries.split(",") if countries else None
        )
    return data


# ------------------------------------------------------------------
# Background task implementations
# ------------------------------------------------------------------

async def _ingest_notifications_task(days_back: int, domain_ids: List[int], db):
    logger.info(f"[INGEST] Starting ePing notifications: days_back={days_back}")
    try:
        async with WTOAPIClient() as wto:
            notifications = await wto.eping_fetch_all_recent(
                days_back=days_back,
                domain_ids=domain_ids,
            )
        # TODO: upsert into wto_notifications table
        logger.info(f"[INGEST] ePing: {len(notifications)} records fetched")
    except Exception as e:
        logger.error(f"[INGEST] ePing failed: {e}")


async def _ingest_qrs_task(member_code: Optional[str], db):
    logger.info(f"[INGEST] Starting QRS: member={member_code or 'all'}")
    try:
        async with WTOAPIClient() as wto:
            qrs = await wto.qrs_list(
                reporter_member_code=member_code,
                in_force_only=True,
            )
        logger.info(f"[INGEST] QRS: {len(qrs)} records fetched")
    except Exception as e:
        logger.error(f"[INGEST] QRS failed: {e}")


async def _ingest_timeseries_task(indicators: str, reporter: str, year: int, db):
    logger.info(f"[INGEST] Starting TimeSeries: indicators={indicators}, reporter={reporter}")
    try:
        async with WTOAPIClient() as wto:
            data = await wto.ts_data(
                indicators=indicators,
                reporters=reporter,
                partners="000",
                periods=str(year),
                max_records=1000,
            )
        count = len(data.get("Dataset", []))
        logger.info(f"[INGEST] TimeSeries: {count} records fetched")
    except Exception as e:
        logger.error(f"[INGEST] TimeSeries failed: {e}")
