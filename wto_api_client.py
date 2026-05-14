"""
WTO Official API Connector
===========================
Integrates all real WTO public API endpoints:

  ePing (TBT/SPS Notifications):
    GET /eping/notifications/search
    GET /eping/members

  Quantitative Restrictions (QRS):
    GET /qrs/hs-versions
    GET /qrs/members
    GET /qrs/notifications
    GET /qrs/products
    GET /qrs/qrs
    GET /qrs/qrs/{qrId}

  Time Series / Trade Statistics:
    GET /timeseries/v1/data
    GET /timeseries/v1/data_count
    GET /timeseries/v1/metadata
    GET /timeseries/v1/topics
    GET /timeseries/v1/frequencies
    GET /timeseries/v1/periods
    GET /timeseries/v1/units
    GET /timeseries/v1/indicator_categories
    GET /timeseries/v1/indicators
    GET /timeseries/v1/territory/regions
    GET /timeseries/v1/territory/groups
    GET /timeseries/v1/reporters
    GET /timeseries/v1/partners
    GET /timeseries/v1/product_classifications
    GET /timeseries/v1/products
    GET /timeseries/v1/years
    GET /timeseries/v1/value_flags

  Trade Facilitation (TFAD):
    GET /tfad/transparency/procedures_contacts_single_window

Docs: https://apiportal.wto.org
"""

import asyncio
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

WTO_BASE = "https://api.wto.org"
TS_BASE  = "http://api.wto.org/timeseries/v1"   # note: http (WTO's own domain)


class WTOAPIClient:
    """
    Async HTTP client for all WTO public APIs.
    Pass your API subscription key via the Ocp-Apim-Subscription-Key header
    (obtain a free key at https://apiportal.wto.org).
    """

    def __init__(self, api_key: Optional[str] = None):
        self._key = api_key or settings.WTO_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def __aenter__(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": "WTO-TradeIntelligencePlatform/1.0",
        }
        if self._key:
            headers["Ocp-Apim-Subscription-Key"] = self._key

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_):
        if self._client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _get(self, url: str, params: Optional[Dict] = None) -> Any:
        """Execute GET request and return parsed JSON (or raise)."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error(f"WTO API HTTP {exc.response.status_code}: {url} | {exc.response.text[:300]}")
            raise
        except httpx.RequestError as exc:
            logger.error(f"WTO API request error: {url} | {exc}")
            raise

    async def _paginate(
        self,
        url: str,
        params: Optional[Dict] = None,
        page_key: str = "page",
        results_key: str = "results",
        max_pages: int = 10,
    ) -> List[Dict]:
        """Auto-paginate a WTO endpoint until no more data."""
        params = dict(params or {})
        all_results: List[Dict] = []
        page = 1
        while page <= max_pages:
            params[page_key] = page
            data = await self._get(url, params)
            batch = data if isinstance(data, list) else data.get(results_key, data)
            if not batch:
                break
            all_results.extend(batch)
            if len(batch) < params.get("pageSize", params.get("page_size", 100)):
                break
            page += 1
        return all_results

    # ==================================================================
    # ePING — TBT / SPS Notifications
    # ==================================================================

    async def eping_search_notifications(
        self,
        language: str = "E",
        domain_ids: Optional[List[int]] = None,   # 1=TBT, 2=SPS
        document_symbol: Optional[str] = None,
        distribution_date_from: Optional[str] = None,  # YYYY-MM-DD
        distribution_date_to: Optional[str] = None,
        country_ids: Optional[List[int]] = None,
        hs: Optional[str] = None,
        ics: Optional[str] = None,
        free_text: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        """
        Search ePing TBT/SPS notifications.
        domainIds: 1 = TBT, 2 = SPS
        https://api.wto.org/eping/notifications/search
        """
        params: Dict[str, Any] = {
            "language": language,
            "page": page,
            "pageSize": page_size,
        }
        if domain_ids:
            params["domainIds"] = ",".join(map(str, domain_ids))
        if document_symbol:
            params["documentSymbol"] = document_symbol
        if distribution_date_from:
            params["distributionDateFrom"] = distribution_date_from
        if distribution_date_to:
            params["distributionDateTo"] = distribution_date_to
        if country_ids:
            params["countryIds"] = ",".join(map(str, country_ids))
        if hs:
            params["hs"] = hs
        if ics:
            params["ics"] = ics
        if free_text:
            params["freeText"] = free_text

        return await self._get(f"{WTO_BASE}/eping/notifications/search", params)

    async def eping_get_members(self, language: str = "E") -> List[Dict]:
        """
        Get list of WTO members as used by ePing.
        https://api.wto.org/eping/members
        """
        return await self._get(f"{WTO_BASE}/eping/members", {"language": language})

    async def eping_fetch_all_recent(
        self,
        days_back: int = 30,
        domain_ids: Optional[List[int]] = None,
    ) -> List[Dict]:
        """
        Convenience: fetch all TBT+SPS notifications from the last N days.
        Returns a flat list across all pages.
        """
        from_date = (datetime.utcnow().date() if days_back == 0
                     else date.fromordinal(date.today().toordinal() - days_back)).isoformat()

        results = []
        page = 1
        while True:
            data = await self.eping_search_notifications(
                domain_ids=domain_ids or [1, 2],
                distribution_date_from=from_date,
                page=page,
                page_size=100,
            )
            batch = data.get("notifications", data) if isinstance(data, dict) else data
            if not batch:
                break
            results.extend(batch)
            total = data.get("total", len(results)) if isinstance(data, dict) else len(results)
            if len(results) >= total:
                break
            page += 1
        logger.info(f"ePing: fetched {len(results)} notifications (last {days_back} days)")
        return results

    # ==================================================================
    # QRS — Quantitative Restrictions
    # ==================================================================

    async def qrs_hs_versions(self) -> List[Dict]:
        """GET /qrs/hs-versions — list available HS nomenclature versions."""
        return await self._get(f"{WTO_BASE}/qrs/hs-versions")

    async def qrs_members(
        self,
        member_code: Optional[str] = None,
        name: Optional[str] = None,
        page: int = 1,
    ) -> List[Dict]:
        """GET /qrs/members"""
        return await self._get(f"{WTO_BASE}/qrs/members", {
            "member_code": member_code,
            "name": name,
            "page": page,
        })

    async def qrs_notifications(
        self,
        reporter_member_code: Optional[str] = None,
        notification_year: Optional[int] = None,
        page: int = 1,
    ) -> List[Dict]:
        """GET /qrs/notifications — QR notifications by member / year."""
        return await self._get(f"{WTO_BASE}/qrs/notifications", {
            "reporter_member_code": reporter_member_code,
            "notification_year": notification_year,
            "page": page,
        })

    async def qrs_products(
        self,
        hs_version: Optional[str] = None,
        code: Optional[str] = None,
        description: Optional[str] = None,
        page: int = 1,
    ) -> List[Dict]:
        """GET /qrs/products"""
        return await self._get(f"{WTO_BASE}/qrs/products", {
            "hs_version": hs_version,
            "code": code,
            "description": description,
            "page": page,
        })

    async def qrs_list(
        self,
        reporter_member_code: Optional[str] = None,
        in_force_only: bool = True,
        year_of_entry_into_force: Optional[int] = None,
        product_codes: Optional[str] = None,
        product_ids: Optional[str] = None,
        page: int = 1,
    ) -> List[Dict]:
        """GET /qrs/qrs — list quantitative restrictions."""
        return await self._get(f"{WTO_BASE}/qrs/qrs", {
            "reporter_member_code": reporter_member_code,
            "in_force_only": "true" if in_force_only else "false",
            "year_of_entry_into_force": year_of_entry_into_force,
            "product_codes": product_codes,
            "product_ids": product_ids,
            "page": page,
        })

    async def qrs_detail(self, qr_id: int) -> Dict:
        """GET /qrs/qrs/{qrId} — full details of a single QR measure."""
        return await self._get(f"{WTO_BASE}/qrs/qrs/{qr_id}")

    # ==================================================================
    # TIME SERIES — Trade Statistics
    # ==================================================================

    async def ts_topics(self, lang: str = "E") -> List[Dict]:
        """GET /timeseries/v1/topics"""
        return await self._get(f"{TS_BASE}/topics", {"lang": lang})

    async def ts_indicators(
        self,
        indicator_code: Optional[str] = None,
        name: Optional[str] = None,
        topic: Optional[str] = None,
        product_classification: Optional[str] = None,
        freq: Optional[str] = None,
        lang: str = "E",
    ) -> List[Dict]:
        """GET /timeseries/v1/indicators"""
        return await self._get(f"{TS_BASE}/indicators", {
            "i": indicator_code,
            "name": name,
            "t": topic,
            "pc": product_classification,
            "tp": None,
            "frq": freq,
            "lang": lang,
        })

    async def ts_reporters(
        self,
        name: Optional[str] = None,
        income_group: Optional[str] = None,
        region: Optional[str] = None,
        group: Optional[str] = None,
        lang: str = "E",
    ) -> List[Dict]:
        """GET /timeseries/v1/reporters"""
        return await self._get(f"{TS_BASE}/reporters", {
            "name": name,
            "ig": income_group,
            "reg": region,
            "gp": group,
            "lang": lang,
        })

    async def ts_partners(
        self,
        name: Optional[str] = None,
        income_group: Optional[str] = None,
        region: Optional[str] = None,
        group: Optional[str] = None,
        lang: str = "E",
    ) -> List[Dict]:
        """GET /timeseries/v1/partners"""
        return await self._get(f"{TS_BASE}/partners", {
            "name": name,
            "ig": income_group,
            "reg": region,
            "gp": group,
            "lang": lang,
        })

    async def ts_products(
        self,
        name: Optional[str] = None,
        product_classification: Optional[str] = None,
        lang: str = "E",
    ) -> List[Dict]:
        """GET /timeseries/v1/products"""
        return await self._get(f"{TS_BASE}/products", {
            "name": name,
            "pc": product_classification,
            "lang": lang,
        })

    async def ts_years(self) -> List[int]:
        """GET /timeseries/v1/years — available data years."""
        return await self._get(f"{TS_BASE}/years")

    async def ts_data(
        self,
        indicators: Union[str, List[str]],
        reporters: Union[str, List[str]],
        partners: Optional[Union[str, List[str]]] = None,
        periods: Optional[Union[str, List[str]]] = None,
        product_classification: Optional[str] = None,
        products: Optional[Union[str, List[str]]] = None,
        fmt: str = "json",
        mode: str = "full",
        decimals: int = 2,
        offset: int = 0,
        max_records: int = 500,
        heading: str = "H",
        lang: str = "E",
        include_meta: bool = False,
    ) -> Dict:
        """
        GET /timeseries/v1/data — core trade statistics endpoint.

        indicators : WTO indicator code(s), e.g. 'HS_M_0040' for imports by HS
        reporters  : WTO reporter code(s), e.g. '682' for Saudi Arabia
        partners   : WTO partner code(s), e.g. '000' for World
        periods    : year(s) or range, e.g. '2020,2021,2022'
        products   : HS code(s), e.g. '270900' for crude oil

        Saudi Arabia reporter code: 682
        Common indicators:
          HS_M_0040  — Imports by HS product
          HS_X_0040  — Exports by HS product
          TRF_0010   — MFN applied tariff rates
          TRF_0020   — WTO bound tariff rates
        """
        def _join(v):
            if v is None:
                return None
            return ",".join(v) if isinstance(v, list) else v

        params = {
            "i":    _join(indicators),
            "r":    _join(reporters),
            "p":    _join(partners),
            "ps":   _join(periods),
            "pc":   product_classification,
            "spc":  _join(products),
            "fmt":  fmt,
            "mode": mode,
            "dec":  decimals,
            "off":  offset,
            "max":  max_records,
            "head": heading,
            "lang": lang,
            "meta": 1 if include_meta else 0,
        }
        return await self._get(f"{TS_BASE}/data", params)

    async def ts_data_count(
        self,
        indicators: Union[str, List[str]],
        reporters: Union[str, List[str]],
        partners: Optional[Union[str, List[str]]] = None,
        periods: Optional[Union[str, List[str]]] = None,
        product_classification: Optional[str] = None,
        products: Optional[Union[str, List[str]]] = None,
    ) -> int:
        """GET /timeseries/v1/data_count — count records before fetching."""
        def _join(v):
            return ",".join(v) if isinstance(v, list) else v if v else None

        result = await self._get(f"{TS_BASE}/data_count", {
            "i":  _join(indicators),
            "r":  _join(reporters),
            "p":  _join(partners),
            "ps": _join(periods),
            "pc": product_classification,
            "spc": _join(products),
        })
        return result.get("count", result) if isinstance(result, dict) else result

    async def ts_metadata(
        self,
        indicators: Optional[str] = None,
        reporters: Optional[str] = None,
        partners: Optional[str] = None,
        product_classification: Optional[str] = None,
        lang: str = "E",
    ) -> Dict:
        """GET /timeseries/v1/metadata"""
        return await self._get(f"{TS_BASE}/metadata", {
            "i": indicators, "r": reporters, "p": partners,
            "pc": product_classification, "lang": lang,
        })

    async def ts_frequencies(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/frequencies", {"lang": lang})

    async def ts_periods(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/periods", {"lang": lang})

    async def ts_units(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/units", {"lang": lang})

    async def ts_indicator_categories(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/indicator_categories", {"lang": lang})

    async def ts_regions(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/territory/regions", {"lang": lang})

    async def ts_groups(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/territory/groups", {"lang": lang})

    async def ts_product_classifications(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/product_classifications", {"lang": lang})

    async def ts_value_flags(self, lang: str = "E") -> List[Dict]:
        return await self._get(f"{TS_BASE}/value_flags", {"lang": lang})

    # ==================================================================
    # TFAD — Trade Facilitation Agreement Database
    # ==================================================================

    async def tfad_procedures_single_window(
        self, countries: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        GET /tfad/transparency/procedures_contacts_single_window
        Returns single-window and contact procedure data by country.
        countries: list of ISO-3 codes, e.g. ['SAU', 'ARE', 'KWT']
        """
        params = {}
        if countries:
            # API expects repeated param: countries[]=SAU&countries[]=ARE
            params["countries[]"] = countries
        return await self._get(
            f"{WTO_BASE}/tfad/transparency/procedures_contacts_single_window", params
        )

    # ==================================================================
    # Compound Queries — Saudi-focused helpers
    # ==================================================================

    async def get_saudi_export_profile(
        self,
        hs_codes: List[str],
        target_country_codes: List[str],
        year: int = 2023,
    ) -> Dict:
        """
        Aggregate key data for Saudi export analysis:
        - Saudi export volumes by HS code (TS)
        - MFN tariffs applied by target countries (TS)
        - Active QRs in target countries for these HS codes (QRS)
        - Recent TBT/SPS notifications from target countries (ePing)
        """
        results: Dict[str, Any] = {}

        # 1. Saudi exports (reporter=682 = Saudi Arabia, partner=000 = World)
        try:
            results["saudi_exports"] = await self.ts_data(
                indicators="HS_X_0040",
                reporters="682",
                partners="000",
                products=",".join(hs_codes),
                periods=str(year),
            )
        except Exception as e:
            logger.warning(f"Export data fetch failed: {e}")
            results["saudi_exports"] = {}

        # 2. MFN tariff rates in target markets
        tariff_tasks = [
            self.ts_data(
                indicators="TRF_0010",   # MFN applied
                reporters=code,
                partners="682",
                products=",".join(hs_codes),
                periods=str(year),
            )
            for code in target_country_codes
        ]
        try:
            tariff_results = await asyncio.gather(*tariff_tasks, return_exceptions=True)
            results["tariffs"] = {
                code: r for code, r in zip(target_country_codes, tariff_results)
                if not isinstance(r, Exception)
            }
        except Exception as e:
            logger.warning(f"Tariff data fetch failed: {e}")
            results["tariffs"] = {}

        # 3. Active QRs
        try:
            qr_tasks = [
                self.qrs_list(
                    reporter_member_code=code,
                    in_force_only=True,
                    product_codes=",".join(hs_codes),
                )
                for code in target_country_codes
            ]
            qr_results = await asyncio.gather(*qr_tasks, return_exceptions=True)
            results["quantitative_restrictions"] = {
                code: r for code, r in zip(target_country_codes, qr_results)
                if not isinstance(r, Exception)
            }
        except Exception as e:
            logger.warning(f"QR data fetch failed: {e}")
            results["quantitative_restrictions"] = {}

        # 4. Recent TBT/SPS notifications
        try:
            results["notifications"] = await self.eping_fetch_all_recent(
                days_back=90,
                domain_ids=[1, 2],
            )
        except Exception as e:
            logger.warning(f"ePing fetch failed: {e}")
            results["notifications"] = []

        return results
