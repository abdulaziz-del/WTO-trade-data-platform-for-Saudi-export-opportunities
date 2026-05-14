# WTO Trade Intelligence Platform — Setup & API Reference

## Quick Start

```bash
# 1. Clone and enter the project
git clone https://github.com/your-org/wto-platform.git
cd wto-platform

# 2. Start infrastructure (PostgreSQL, Redis, Elasticsearch)
docker-compose up -d

# 3. Backend
cd backend
cp .env.example .env          # → fill in your keys (see below)
pip install -r requirements.txt
alembic upgrade head           # run migrations
uvicorn src.main:app --reload  # starts on :8000

# 4. Frontend
cd ../frontend
npm install
npm run dev                    # starts on :3000
```

---

## Getting the WTO API Key (free)

| Step | Action |
|------|--------|
| 1 | Go to **https://apiportal.wto.org** |
| 2 | Click **Sign Up** (free, instant) |
| 3 | Under **Products**, subscribe to: `ePing`, `Quantitative Restrictions`, `Time Series V1`, `TFAD` |
| 4 | Go to **Profile → Subscriptions** → copy **Primary Key** |
| 5 | Paste it as `WTO_API_KEY` in your `.env` |

The same key covers all four products via the `Ocp-Apim-Subscription-Key` header.

---

## WTO API Endpoints Used

### ePing — TBT / SPS Notifications
| Endpoint | Usage |
|----------|-------|
| `GET /eping/notifications/search` | Search TBT/SPS notifications with filters |
| `GET /eping/members` | List WTO members (for country picker) |

Key parameters for notifications:
- `domainIds=1` → TBT only  
- `domainIds=2` → SPS only  
- `domainIds=1,2` → both  
- `countryIds` → filter by notifying country  
- `hs` → filter by HS code prefix  
- `distributionDateFrom` / `distributionDateTo` → date range  

---

### QRS — Quantitative Restrictions
| Endpoint | Usage |
|----------|-------|
| `GET /qrs/hs-versions` | HS nomenclature versions |
| `GET /qrs/members` | WTO members list |
| `GET /qrs/notifications` | QR notifications by member/year |
| `GET /qrs/products` | Products by HS code/description |
| `GET /qrs/qrs` | List active QR measures |
| `GET /qrs/qrs/{qrId}` | Full detail of one QR measure |

---

### Time Series — Trade Statistics
| Endpoint | Usage |
|----------|-------|
| `GET /timeseries/v1/data` | Core data query (exports, tariffs…) |
| `GET /timeseries/v1/data_count` | Count records before fetching |
| `GET /timeseries/v1/indicators` | Browse available indicators |
| `GET /timeseries/v1/reporters` | WTO reporter codes |
| `GET /timeseries/v1/partners` | WTO partner codes |
| `GET /timeseries/v1/products` | Products by HS/classification |
| `GET /timeseries/v1/years` | Available data years |

**Saudi Arabia reporter code: `682`**  
**World partner code: `000`**

Key indicators:
| Code | Description |
|------|-------------|
| `HS_X_0040` | Saudi exports by HS product |
| `HS_M_0040` | Imports by HS product |
| `TRF_0010` | MFN applied tariff rate |
| `TRF_0020` | WTO bound tariff rate |

Example — Saudi exports of petrochemicals to China in 2023:
```
GET /timeseries/v1/data
  ?i=HS_X_0040
  &r=682
  &p=156
  &ps=2023
  &spc=290110,290120
  &fmt=json
  &max=500
```

---

### TFAD — Trade Facilitation
| Endpoint | Usage |
|----------|-------|
| `GET /tfad/transparency/procedures_contacts_single_window` | Single-window & contact data |

---

## Platform API Endpoints (Internal)

Base URL: `http://localhost:8000/api/v1`

### Live WTO Data Previews (no DB write)
```
GET /ingestion/preview/notifications?days_back=7&hs=2709
GET /ingestion/preview/qrs?member_code=156&product_codes=270900
GET /ingestion/preview/timeseries?indicators=HS_X_0040&reporters=682&periods=2023
GET /ingestion/preview/saudi-export-profile?hs_codes=270900,290110&target_countries=156,356
GET /ingestion/preview/tfad?countries=SAU,ARE,KWT
```

### Trigger Ingestion (saves to DB)
```
POST /ingestion/run/notifications?days_back=30&domain_ids=1,2
POST /ingestion/run/qrs?member_code=682
POST /ingestion/run/timeseries?indicators=HS_X_0040,TRF_0010&reporter=682&year=2023
```

### Opportunities
```
GET  /opportunities?country_code=CHN&min_score=70&priority=HIGH&page=1
GET  /opportunities/{id}
POST /opportunities/{id}/analyze          (triggers AI analysis)
GET  /opportunities/summary/by-country
GET  /opportunities/summary/by-sector
```

### Dashboard
```
GET /dashboard/stats
GET /dashboard/recent-alerts
GET /dashboard/opportunity-map
```

---

## Saudi HS Codes — Key Export Products

| HS Code | Product | Notes |
|---------|---------|-------|
| 270900 | Crude petroleum oil | Largest export |
| 271019 | Other petroleum oils | Refined products |
| 290110 | Acyclic hydrocarbons — ethylene | Petrochemicals |
| 290120 | Propylene | Petrochemicals |
| 310210 | Ammonium nitrate (fertilizer) | SABIC |
| 310230 | Ammonium nitrate + calcium (fertilizer) | SABIC |
| 390110 | Polyethylene (low density) | Sabic/Petro Rabigh |
| 390120 | Polyethylene (high density) | |
| 760110 | Aluminium (unwrought) | ALBA-linked |
| 080410 | Dates | Agricultural |
| 300490 | Pharmaceutical products | Growing sector |

---

## Docker Compose

```yaml
# docker-compose.yml (infrastructure only)
version: '3.9'
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: wto_platform
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  elasticsearch:
    image: elasticsearch:8.15.0
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
    ports: ["9200:9200"]
    volumes: [esdata:/usr/share/elasticsearch/data]

volumes:
  pgdata:
  esdata:
```

---

## Deployment (AWS)

```bash
# Build images
docker build -t wto-platform-backend ./backend
docker build -t wto-platform-frontend ./frontend

# Push to ECR
aws ecr get-login-password --region me-south-1 | docker login ...
docker push ...

# Deploy to EKS (Kubernetes manifests in /deployment/k8s/)
kubectl apply -f deployment/k8s/
```

Recommended AWS regions for Saudi deployment:
- **me-south-1** (Bahrain) — lowest latency to KSA, SAMA-compliant
- **me-central-1** (UAE) — alternative GCC region
