"""
AI Analysis Service
Uses Claude API for NLP-powered legal analysis of WTO documents.
Maps findings to WTO agreements and generates structured opportunities.
"""
import json
from typing import Dict, List, Optional
from uuid import UUID

import anthropic

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# WTO Agreement legal framework — used to ground AI analysis
WTO_LEGAL_FRAMEWORK = {
    "GATT1994": {
        "name": "General Agreement on Tariffs and Trade 1994",
        "key_articles": {
            "I": "Most Favoured Nation (MFN) Treatment",
            "II": "Schedules of Concessions (Bound Tariffs)",
            "III": "National Treatment",
            "XI": "General Elimination of Quantitative Restrictions",
            "XX": "General Exceptions",
            "XXIV": "Customs Unions and Free Trade Areas",
        },
    },
    "GATS": {
        "name": "General Agreement on Trade in Services",
        "key_articles": {
            "II": "MFN Treatment",
            "VI": "Domestic Regulation",
            "XVI": "Market Access",
            "XVII": "National Treatment",
        },
    },
    "TBT": {
        "name": "Agreement on Technical Barriers to Trade",
        "key_articles": {
            "2": "Preparation, Adoption and Application of Technical Regulations",
            "5": "Procedures for Assessment of Conformity",
            "9": "International and Regional Systems",
        },
    },
    "SPS": {
        "name": "Agreement on Sanitary and Phytosanitary Measures",
        "key_articles": {
            "2": "Basic Rights and Obligations",
            "3": "Harmonisation",
            "5": "Assessment of Risk",
            "7": "Transparency",
        },
    },
    "TRIPS": {
        "name": "Agreement on Trade-Related Aspects of Intellectual Property Rights",
        "key_articles": {
            "3": "National Treatment",
            "4": "Most-Favoured-Nation Treatment",
            "27": "Patentable Subject Matter",
        },
    },
}

SAUDI_EXPORT_SECTORS = [
    "Petrochemicals (HS 27, 29)",
    "Plastics and Rubber (HS 39, 40)",
    "Fertilizers (HS 31)",
    "Aluminum (HS 76)",
    "Food Products — Halal (HS 02, 04, 16)",
    "Dates and Agricultural Products (HS 08)",
    "Pharmaceuticals (HS 30)",
    "Construction Materials (HS 25, 68, 69)",
]


class AIAnalysisService:
    """
    Applies Claude AI to analyze WTO documents and extract
    trade intelligence for Saudi exporters.
    """

    def __init__(self, db=None):
        self.db = db
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def analyze_tpr_report(self, tpr_text: str, country: str) -> Dict:
        """
        Analyze a TPR report for Saudi export opportunities.
        Returns structured analysis with legal citations.
        """
        prompt = self._build_tpr_analysis_prompt(tpr_text, country)

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            return self._parse_structured_response(raw)
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return self._fallback_analysis(country)

    async def analyze_notification(self, notification: Dict) -> Dict:
        """
        Analyze a TBT/SPS notification for compliance risks and opportunities.
        """
        prompt = self._build_notification_prompt(notification)

        try:
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system=self._get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            return self._parse_structured_response(raw)
        except Exception as e:
            logger.error(f"Notification analysis failed: {e}")
            return {}

    def score_opportunity(self, analysis: Dict, tariff_data: Optional[Dict] = None) -> float:
        """
        Rule-based + AI scoring of export opportunities.
        Score: 0–100
        Factors:
          - Market size proxy (country GDP weight)
          - Tariff level (lower = better)
          - Regulatory alignment
          - Saudi product competitiveness
          - Notification urgency (comment deadline proximity)
        """
        score = 50.0  # base

        # Tariff factor: lower tariff = higher score
        if tariff_data:
            mfn = tariff_data.get("mfn_rate", 10)
            if mfn < 3:
                score += 20
            elif mfn < 7:
                score += 10
            elif mfn > 15:
                score -= 10

        # WTO agreement alignment bonus
        if analysis.get("agreements_referenced"):
            score += 5 * min(len(analysis["agreements_referenced"]), 3)

        # Opportunity type weighting
        opp_type = analysis.get("opportunity_type", "")
        type_weights = {
            "MARKET_ACCESS": 15,
            "TARIFF_REDUCTION": 20,
            "REGULATORY_CHANGE": 10,
            "NEW_MARKET": 25,
        }
        score += type_weights.get(opp_type, 0)

        return min(max(score, 0), 100)

    # -------------------------------------------------------
    # Prompt Builders
    # -------------------------------------------------------
    def _get_system_prompt(self) -> str:
        return f"""You are a senior WTO legal advisor and trade analyst specializing in Saudi Arabian export opportunities.

Your analysis must:
1. Ground all findings in specific WTO agreement articles (GATT 1994, TBT, SPS, GATS, TRIPS)
2. Identify concrete opportunities for Saudi products in these sectors: {', '.join(SAUDI_EXPORT_SECTORS)}
3. Map compliance risks against Saudi regulatory obligations
4. Produce structured, actionable output

WTO Legal Framework available:
{json.dumps(WTO_LEGAL_FRAMEWORK, indent=2)}

Always respond in valid JSON format only. No preamble or explanation outside JSON."""

    def _build_tpr_analysis_prompt(self, tpr_text: str, country: str) -> str:
        return f"""Analyze this Trade Policy Review for {country} and identify export opportunities for Saudi Arabia.

TPR EXCERPT:
{tpr_text[:3000]}

Return a JSON object with this exact structure:
{{
  "country": "{country}",
  "opportunity_type": "MARKET_ACCESS|TARIFF_REDUCTION|REGULATORY_CHANGE|NEW_MARKET",
  "priority": "CRITICAL|HIGH|MEDIUM|LOW",
  "title": "concise opportunity title",
  "title_ar": "Arabic translation of title",
  "description": "detailed description of the opportunity",
  "description_ar": "Arabic translation",
  "saudi_products_affected": ["list of relevant Saudi products with HS codes"],
  "agreements_referenced": [
    {{"agreement": "TBT", "article": "2.7", "relevance": "explanation"}}
  ],
  "compliance_risks": ["list of risks"],
  "recommendations": [
    {{"action": "specific action", "timeline": "immediate/short-term/long-term", "responsible_entity": "GAFTE/MOC/ZATCA/Exporter"}}
  ],
  "key_metrics": {{
    "market_size_indicator": "large/medium/small",
    "tariff_competitiveness": "favorable/neutral/challenging",
    "regulatory_complexity": "low/medium/high"
  }}
}}"""

    def _build_notification_prompt(self, notification: Dict) -> str:
        return f"""Analyze this WTO {notification.get('type', 'TBT')} notification and assess impact on Saudi exporters.

NOTIFICATION:
Title: {notification.get('title')}
Country: {notification.get('notifying_country')}
Description: {notification.get('description')}
Affected HS Codes: {notification.get('affected_products', [])}
Comment Deadline: {notification.get('comment_deadline')}

Return a JSON object with this exact structure:
{{
  "impact_level": "HIGH|MEDIUM|LOW",
  "opportunity_type": "COMPLIANCE_RISK|MARKET_ACCESS|REGULATORY_CHANGE",
  "title": "brief impact summary",
  "description": "detailed analysis for Saudi exporters",
  "affected_saudi_sectors": ["sectors impacted"],
  "agreements_referenced": [
    {{"agreement": "TBT", "article": "2", "relevance": "explanation"}}
  ],
  "required_actions": [
    {{"action": "what Saudi exporters must do", "deadline": "when", "entity": "who"}}
  ],
  "comment_opportunity": {{
    "should_comment": true,
    "suggested_position": "Saudi Arabia's recommended position in WTO comment",
    "deadline": "{notification.get('comment_deadline')}"
  }}
}}"""

    def _parse_structured_response(self, raw: str) -> Dict:
        """Parse JSON from Claude response safely."""
        try:
            # Strip markdown code blocks if present
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            return json.loads(clean.strip())
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}. Raw: {raw[:200]}")
            return {"raw_analysis": raw, "parse_error": str(e)}

    def _fallback_analysis(self, country: str) -> Dict:
        """Fallback analysis when AI is unavailable."""
        return {
            "country": country,
            "opportunity_type": "MARKET_ACCESS",
            "priority": "MEDIUM",
            "title": f"Trade opportunity in {country} — Manual review required",
            "description": "Automated analysis unavailable. Please review the source document manually.",
            "agreements_referenced": [],
            "recommendations": [],
        }

    # -------------------------------------------------------
    # Batch Processing
    # -------------------------------------------------------
    async def batch_analyze_notifications(self, notifications: List[Dict]) -> List[Dict]:
        """Process multiple notifications with rate limiting."""
        results = []
        for i, notif in enumerate(notifications):
            try:
                analysis = await self.analyze_notification(notif)
                analysis["source_notification"] = notif.get("symbol")
                results.append(analysis)
                # Respect API rate limits
                if i % 5 == 4:
                    import asyncio
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Failed to analyze notification {notif.get('symbol')}: {e}")
        return results
