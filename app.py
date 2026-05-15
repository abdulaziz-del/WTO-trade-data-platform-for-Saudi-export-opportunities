import os
import time
import logging
import threading
import re
import requests
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wto-platform")

app  = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

WTO_KEY    = os.getenv("WTO_API_KEY", "")
CLAUDE_KEY = os.getenv("CLAUDE_API_KEY", "")
CACHE_TTL  = 3600
_cache     = {"notifications": [], "opportunities": [], "at": 0}
_lock      = threading.Lock()

# ── Saudi key HS codes ──────────────────────────────────────────────────
SAUDI_HS = {
    "270900": "نفط خام",
    "290110": "إيثيلين",
    "290120": "بروبيلين",
    "310210": "نترات الأمونيوم",
    "390110": "بولي إيثيلين",
    "760110": "ألمنيوم",
    "080410": "تمور",
    "300490": "أدوية",
}

SAUDI_REPORTER = "682"   # WTO reporter code for Saudi Arabia

# ── WTO agreement mapping ────────────────────────────────────────────────
WTO_AGREEMENTS = {
    "TBT": {"name": "اتفاقية العوائق التقنية أمام التجارة", "articles": {"2": "اللوائح التقنية", "5": "تقييم المطابقة"}},
    "SPS": {"name": "اتفاقية الصحة والصحة النباتية",        "articles": {"3": "التنسيق", "5": "تقييم المخاطر"}},
    "GATT": {"name": "الاتفاقية العامة للتعريفات والتجارة", "articles": {"I": "الدولة الأولى بالرعاية", "II": "جداول التنازلات", "XI": "القيود الكمية"}},
}


# ════════════════════════════════════════════════════════════════
#  DATA FETCHING
# ════════════════════════════════════════════════════════════════

def cache_fresh():
    return (time.time() - _cache["at"]) < CACHE_TTL and bool(_cache["notifications"])


def extract_rows(d):
    if isinstance(d, list):
        return d
    if not isinstance(d, dict):
        return []
    for key in ["items", "notifications", "rows", "data", "results", "content"]:
        val = d.get(key)
        if isinstance(val, list):
            return val
    return []


def parse_notification(it):
    sym    = (it.get("documentSymbol") or it.get("symbol") or "").strip()
    area   = it.get("area", "")
    ntype  = "SPS" if (area == "SPS" or "/SPS/" in sym) else "TBT"

    title_en = (it.get("titlePlain") or it.get("title") or it.get("titleEnglish") or sym or "").strip()
    if "<" in title_en:
        title_en = re.sub(r"<[^>]+>", " ", title_en).strip()

    prods = it.get("productsFreeTextPlain") or it.get("productsFreeText") or ""
    if isinstance(prods, str):
        prods = [p.strip() for p in re.split(r"[,;،]", prods) if p.strip()][:5]
    elif not isinstance(prods, list):
        prods = []

    date_raw = it.get("distributionDate") or ""
    dead_raw = it.get("commentDeadlineDate") or ""
    is_open  = bool(dead_raw) or bool(it.get("isOpenForComments"))

    doc_link = it.get("notifiedDocumentLink") or ""
    dol_link = it.get("dolLink") or ""
    link_to_notif = it.get("linkToNotification") or ""

    docs = []
    if doc_link:
        raw = doc_link.replace("\r\n", "\n").replace("\r", "\n")
        for line in raw.split("\n"):
            for part in line.split(","):
                part = part.strip()
                if part.startswith("http"):
                    docs.append({"name": "مستند رسمي", "url": part, "type": "pdf"})
    if not docs and dol_link:
        dol_url = "https://docs.wto.org/dol2fe/Pages/SS/directdoc.aspx?filename=q:/" + dol_link.replace("\\", "/")
        docs.append({"name": "وثيقة WTO", "url": dol_url, "type": "doc"})

    eping_link = link_to_notif or (
        "https://eping.wto.org/en/Search/Index?documentSymbol=" + requests.utils.quote(sym) if sym else ""
    )

    # Match Saudi products
    saudi_match = []
    for hs, name in SAUDI_HS.items():
        if hs in " ".join(prods) or name in title_en:
            saudi_match.append({"hs": hs, "name": name})

    return {
        "id":              sym or str(it.get("id", "")),
        "symbol":          sym,
        "member":          it.get("notifyingMember") or it.get("member") or "",
        "memberCode":      it.get("notifyingMemberCode") or it.get("memberCode") or "",
        "date":            date_raw[:10] if len(date_raw) >= 10 else date_raw,
        "type":            ntype,
        "title":           title_en,
        "titleAr":         "",
        "status":          "مفتوح للتعليق" if is_open else "منتهي",
        "products":        prods,
        "commentDeadline": dead_raw[:10] if len(dead_raw) >= 10 else "",
        "docs":            docs,
        "epingLink":       eping_link,
        "saudiMatch":      saudi_match,
    }


def fetch_notifications():
    if not WTO_KEY:
        log.warning("No WTO_API_KEY — using empty data")
        return []
    headers  = {"Ocp-Apim-Subscription-Key": WTO_KEY, "Accept": "application/json"}
    all_data = []
    for pg in range(1, 7):
        try:
            r = requests.get(
                "https://api.wto.org/eping/notifications/search",
                headers=headers,
                params={"page": pg, "pageSize": 50, "language": 1},
                timeout=25
            )
            if r.status_code != 200:
                break
            d    = r.json()
            rows = extract_rows(d)
            if not rows:
                break
            all_data.extend([parse_notification(it) for it in rows])
            total = d.get("totalCount", d.get("total", 0)) if isinstance(d, dict) else 0
            if total and len(all_data) >= total:
                break
            time.sleep(0.4)
        except Exception as e:
            log.error("Fetch error pg %d: %s", pg, e)
            break
    return all_data


def fetch_tariffs(hs_codes, reporter="156"):
    """Fetch MFN tariffs from WTO TimeSeries API."""
    if not WTO_KEY:
        return {}
    try:
        headers = {"Ocp-Apim-Subscription-Key": WTO_KEY, "Accept": "application/json"}
        r = requests.get(
            "http://api.wto.org/timeseries/v1/data",
            headers=headers,
            params={
                "i":   "TRF_0010",
                "r":   reporter,
                "p":   SAUDI_REPORTER,
                "ps":  "2023",
                "spc": ",".join(hs_codes),
                "fmt": "json",
                "max": 100,
            },
            timeout=20
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log.warning("Tariff fetch error: %s", e)
    return {}


def build_opportunities(notifications):
    """Generate export opportunities from notification data."""
    opportunities = []
    # Static high-value Saudi opportunities
    static_opps = [
        {"id": "opp-1", "title": "بتروكيماويات → الصين",     "titleEn": "Petrochemicals → China",  "hs": "290110", "country": "الصين",           "score": 92, "priority": "حرج",    "agreement": "TBT م.2",    "type": "وصول للسوق"},
        {"id": "opp-2", "title": "أسمدة → الهند",            "titleEn": "Fertilizers → India",     "hs": "310210", "country": "الهند",           "score": 87, "priority": "عالي",   "agreement": "GATT م.II",  "type": "خفض تعريفة"},
        {"id": "opp-3", "title": "ألمنيوم → أوروبا",         "titleEn": "Aluminum → Europe",       "hs": "760110", "country": "الاتحاد الأوروبي","score": 71, "priority": "متوسط",  "agreement": "GATS م.XVI", "type": "سوق جديد"},
        {"id": "opp-4", "title": "تمور → أوروبا",            "titleEn": "Dates → Europe",          "hs": "080410", "country": "الاتحاد الأوروبي","score": 65, "priority": "متوسط",  "agreement": "SPS م.3",    "type": "تغيير تنظيمي"},
        {"id": "opp-5", "title": "بولي إيثيلين → كوريا",     "titleEn": "Polyethylene → Korea",    "hs": "390110", "country": "كوريا",           "score": 80, "priority": "عالي",   "agreement": "TBT م.2.7",  "type": "وصول للسوق"},
        {"id": "opp-6", "title": "أدوية → الولايات المتحدة","titleEn": "Pharma → USA",            "hs": "300490", "country": "الولايات المتحدة","score": 78, "priority": "عالي",   "agreement": "TRIPS م.27", "type": "سوق جديد"},
        {"id": "opp-7", "title": "نفط خام → اليابان",        "titleEn": "Crude Oil → Japan",       "hs": "270900", "country": "اليابان",         "score": 88, "priority": "عالي",   "agreement": "GATT م.I",   "type": "وصول للسوق"},
    ]
    # Add notification-derived opportunities
    for n in notifications[:10]:
        if n.get("saudiMatch") and n.get("status") == "مفتوح للتعليق":
            for sm in n["saudiMatch"][:1]:
                opportunities.append({
                    "id":        "notif-" + n["id"],
                    "title":     "فرصة من إشعار: " + n["title"][:60],
                    "titleEn":   n["title"][:60],
                    "hs":        sm["hs"],
                    "country":   n["member"],
                    "score":     60,
                    "priority":  "متوسط",
                    "agreement": n["type"] + " م.2",
                    "type":      "تغيير تنظيمي",
                    "source":    n["symbol"],
                })
    return static_opps + opportunities


def refresh(force=False):
    if not force and cache_fresh():
        return
    with _lock:
        if not force and cache_fresh():
            return
        notifs = fetch_notifications()
        if notifs:
            notifs.sort(key=lambda x: x.get("date", ""), reverse=True)
        opps = build_opportunities(notifs)
        _cache["notifications"] = notifs
        _cache["opportunities"] = opps
        _cache["at"] = time.time()
        log.info("Cache refreshed: %d notifications, %d opportunities", len(notifs), len(opps))


def startup():
    def _run():
        time.sleep(2)
        refresh(force=True)
        RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "")
        while True:
            time.sleep(840)
            try:
                if RENDER_URL:
                    requests.get(RENDER_URL + "/api/refresh", timeout=10)
                if (time.time() - _cache["at"]) >= CACHE_TTL:
                    refresh()
            except Exception as e:
                log.error("BG error: %s", e)
    threading.Thread(target=_run, daemon=True, name="wto-bg").start()


# ════════════════════════════════════════════════════════════════
#  ROUTES
# ════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "notifications": len(_cache["notifications"]),
        "opportunities": len(_cache["opportunities"]),
        "wto_key": bool(WTO_KEY),
        "claude_key": bool(CLAUDE_KEY),
        "cached_at": datetime.fromtimestamp(_cache["at"]).isoformat() if _cache["at"] else None,
    })


@app.route("/api/stats")
def stats():
    n = _cache["notifications"]
    o = _cache["opportunities"]
    return jsonify({
        "total_notifications": len(n),
        "sps":  sum(1 for x in n if x["type"] == "SPS"),
        "tbt":  sum(1 for x in n if x["type"] == "TBT"),
        "open": sum(1 for x in n if x["status"] == "مفتوح للتعليق"),
        "total_opportunities": len(o),
        "critical": sum(1 for x in o if x.get("priority") == "حرج"),
        "high":     sum(1 for x in o if x.get("priority") == "عالي"),
    })


@app.route("/api/notifications")
def get_notifications():
    if request.args.get("refresh") == "1":
        refresh(force=True)
    data = list(_cache["notifications"])
    t    = request.args.get("type", "").upper()
    st   = request.args.get("status", "")
    kw   = request.args.get("keyword", "").lower()
    mc   = request.args.get("member", "").lower()
    pg   = max(1, int(request.args.get("page", 1)))
    rw   = min(100, int(request.args.get("rows", 50)))
    if t in ("SPS", "TBT"):
        data = [n for n in data if n["type"] == t]
    if st == "open":
        data = [n for n in data if n["status"] == "مفتوح للتعليق"]
    if kw:
        data = [n for n in data if kw in n.get("title", "").lower() or kw in n.get("symbol", "").lower()]
    if mc:
        data = [n for n in data if mc in n.get("member", "").lower()]
    total     = len(data)
    page_data = data[(pg - 1) * rw: pg * rw]
    return jsonify({
        "notifications": page_data,
        "total": total,
        "page":  pg,
        "pages": max(1, (total + rw - 1) // rw),
        "cached_at": datetime.fromtimestamp(_cache["at"]).isoformat() if _cache["at"] else None,
    })


@app.route("/api/opportunities")
def get_opportunities():
    data    = list(_cache["opportunities"])
    country = request.args.get("country", "").lower()
    ptype   = request.args.get("type", "").lower()
    min_sc  = float(request.args.get("min_score", 0))
    if country:
        data = [o for o in data if country in o.get("country", "").lower()]
    if ptype:
        data = [o for o in data if ptype in o.get("type", "").lower()]
    if min_sc:
        data = [o for o in data if o.get("score", 0) >= min_sc]
    data.sort(key=lambda x: x.get("score", 0), reverse=True)
    return jsonify({"opportunities": data, "total": len(data)})


@app.route("/api/tariffs")
def get_tariffs():
    """Static tariff table for Saudi key products in major markets."""
    return jsonify({
        "tariffs": [
            {"hs": "270900", "product": "نفط خام",      "china": 0.0,  "india": 0.0,  "eu": 0.0,  "usa": 0.0,  "japan": 0.0},
            {"hs": "290110", "product": "إيثيلين",       "china": 2.0,  "india": 7.5,  "eu": 3.2,  "usa": 0.0,  "japan": 1.0},
            {"hs": "310210", "product": "أسمدة",         "china": 6.0,  "india": 12.0, "eu": 6.5,  "usa": 0.0,  "japan": 3.0},
            {"hs": "390110", "product": "بولي إيثيلين",  "china": 6.5,  "india": 10.0, "eu": 6.5,  "usa": 3.7,  "japan": 4.0},
            {"hs": "760110", "product": "ألمنيوم",        "china": 8.0,  "india": 7.5,  "eu": 3.0,  "usa": 0.0,  "japan": 1.3},
            {"hs": "080410", "product": "تمور",           "china": 5.0,  "india": 30.0, "eu": 9.6,  "usa": 1.8,  "japan": 8.5},
            {"hs": "300490", "product": "أدوية",          "china": 0.0,  "india": 10.0, "eu": 0.0,  "usa": 0.0,  "japan": 0.0},
        ]
    })


@app.route("/api/refresh", methods=["GET", "POST"])
def force_refresh():
    refresh(force=True)
    return jsonify({"ok": True, "notifications": len(_cache["notifications"]), "opportunities": len(_cache["opportunities"])})


@app.route("/api/analyze", methods=["POST"])
def analyze():
    if not CLAUDE_KEY:
        return jsonify({"error": "No Claude API key", "analysis": ""})
    try:
        n     = request.get_json() or {}
        ntype = n.get("type", "TBT")
        prompt_lines = [
            "أنت محلل قانوني متخصص في اتفاقيات منظمة التجارة العالمية.",
            "حلّل هذا الإشعار:",
            "الرمز: " + n.get("symbol", "") + " | الدولة: " + n.get("member", "") + " | النوع: " + ntype,
            "العنوان: " + n.get("title", ""),
            "المنتجات: " + ", ".join(n.get("products", [])),
            "موعد التعليق: " + n.get("commentDeadline", ""),
            "",
            "=== الملخص التنفيذي ===",
            "4-5 جمل عن جوهر الإشعار وأهميته",
            "",
            "=== التحليل القانوني ===",
            "الأساس في اتفاقية " + ("SPS المادة 5" if ntype == "SPS" else "TBT المادة 2"),
            "التوافق مع معايير " + ("Codex/OIE/IPPC" if ntype == "SPS" else "ISO/IEC"),
            "الأثر على صادرات المملكة العربية السعودية",
            "",
            "=== التوصيات ===",
            "3-4 توصيات عملية للمصدرين السعوديين",
            "اكتب بالعربية الفصحى.",
        ]
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1200,
                  "messages": [{"role": "user", "content": "\n".join(prompt_lines)}]},
            timeout=45
        )
        if r.status_code == 200:
            return jsonify({"analysis": r.json()["content"][0]["text"].strip()})
        return jsonify({"analysis": "", "error": r.text[:300]})
    except Exception as e:
        return jsonify({"error": str(e), "analysis": ""})


@app.route("/api/analyze-opportunity", methods=["POST"])
def analyze_opportunity():
    if not CLAUDE_KEY:
        return jsonify({"error": "No Claude API key", "analysis": ""})
    try:
        o = request.get_json() or {}
        prompt = "\n".join([
            "أنت محلل قانوني متخصص في تجارة المملكة العربية السعودية الدولية.",
            "حلّل فرصة التصدير التالية بالتفصيل:",
            "العنوان: " + o.get("title", ""),
            "الدولة المستهدفة: " + o.get("country", ""),
            "كود HS: " + o.get("hs", ""),
            "درجة الفرصة: " + str(o.get("score", "")) + "/100",
            "الأساس القانوني: " + o.get("agreement", ""),
            "",
            "اكتب تحليلاً يشمل:",
            "1. ملخص الفرصة وأهميتها الاقتصادية",
            "2. الإطار القانوني في WTO",
            "3. المتطلبات التنظيمية للوصول للسوق",
            "4. المخاطر المحتملة",
            "5. خطوات عملية للمصدر السعودي",
            "اكتب بالعربية الفصحى بأسلوب قانوني احترافي.",
        ])
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 1500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=45
        )
        if r.status_code == 200:
            return jsonify({"analysis": r.json()["content"][0]["text"].strip()})
        return jsonify({"analysis": "", "error": r.text[:300]})
    except Exception as e:
        return jsonify({"error": str(e), "analysis": ""})


@app.route("/api/translate", methods=["POST"])
def translate():
    if not CLAUDE_KEY:
        return jsonify({"ar": ""})
    try:
        body = request.get_json() or {}
        text = body.get("text", "")
        if not text:
            return jsonify({"ar": ""})
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 200,
                  "messages": [{"role": "user", "content": "ترجم إلى العربية الفصحى فقط بدون أي نص إضافي:\n" + text}]},
            timeout=15
        )
        if r.status_code == 200:
            return jsonify({"ar": r.json()["content"][0]["text"].strip()})
    except Exception as e:
        log.error("Translate: %s", e)
    return jsonify({"ar": ""})


@app.route("/api/wto/live-search")
def wto_live_search():
    """Proxy to WTO ePing API with live search."""
    if not WTO_KEY:
        return jsonify({"error": "No WTO API key", "notifications": []})
    headers = {"Ocp-Apim-Subscription-Key": WTO_KEY, "Accept": "application/json"}
    params  = {"page": request.args.get("page", 1), "pageSize": 50, "language": 1}
    for p in ["domainIds", "documentSymbol", "distributionDateFrom", "distributionDateTo", "countryIds", "hs", "freeText"]:
        v = request.args.get(p)
        if v:
            params[p] = v
    try:
        r = requests.get("https://api.wto.org/eping/notifications/search", headers=headers, params=params, timeout=25)
        if r.status_code == 200:
            d    = r.json()
            rows = extract_rows(d)
            return jsonify({
                "notifications": [parse_notification(it) for it in rows],
                "total": d.get("totalCount", len(rows)) if isinstance(d, dict) else len(rows),
                "page":  int(params["page"]),
            })
        return jsonify({"error": r.text[:200], "notifications": []})
    except Exception as e:
        return jsonify({"error": str(e), "notifications": []})


@app.route("/api/wto/tariffs-live")
def tariffs_live():
    """Live tariff data from WTO TimeSeries."""
    reporter = request.args.get("reporter", "156")
    hs_codes = request.args.get("hs", "290110,310210").split(",")
    data = fetch_tariffs(hs_codes, reporter)
    return jsonify(data)


@app.route("/api/test")
def test():
    if not WTO_KEY:
        return jsonify({"ok": False, "error": "No WTO_API_KEY set"})
    headers = {"Ocp-Apim-Subscription-Key": WTO_KEY, "Accept": "application/json"}
    try:
        r = requests.get("https://api.wto.org/eping/notifications/search",
                         headers=headers, params={"page": 1, "pageSize": 2, "language": 1}, timeout=15)
        rows = extract_rows(r.json()) if r.ok else []
        return jsonify({"ok": r.ok, "status": r.status_code, "rows": len(rows)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


startup()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
