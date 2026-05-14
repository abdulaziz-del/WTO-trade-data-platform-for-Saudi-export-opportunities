# WTO Trade Intelligence Platform — System Architecture

## Overview

A microservices-oriented platform that ingests WTO public data, applies AI/NLP analysis,
and surfaces actionable Saudi export opportunities through an interactive dashboard.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │  Web (Next.js)│  │  Mobile (PWA)│  │  API Clients │                 │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                 │
└─────────┼─────────────────┼─────────────────┼───────────────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        API GATEWAY (Kong / Nginx)                       │
│   Rate Limiting │ Auth (JWT/OAuth2) │ Load Balancing │ SSL Termination  │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
        ┌─────────────────────┼──────────────────────┐
        │                     │                      │
        ▼                     ▼                      ▼
┌───────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Auth Service  │   │   Core API        │   │  Notification    │
│  (JWT + RBAC) │   │   (FastAPI)       │   │  Service         │
└───────────────┘   └────────┬─────────┘   └────────┬─────────┘
                             │                       │
        ┌────────────────────┼───────────────────────┤
        │                    │                       │
        ▼                    ▼                       ▼
┌───────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│  Data Ingestion│  │  Analysis Engine │  │  Report Generator    │
│  Service       │  │  (AI/NLP + Rules)│  │  (PDF/Word/Excel)    │
└───────┬───────┘  └────────┬─────────┘  └──────────────────────┘
        │                   │
        ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────┐  ┌─────────┐ │
│  │  PostgreSQL  │  │Elasticsearch │  │  Redis   │  │  S3/    │ │
│  │  (Primary)   │  │  (Search)    │  │  (Cache) │  │  Blob   │ │
│  └─────────────┘  └──────────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL DATA SOURCES                        │
│  ┌──────────────┐  ┌─────────┐  ┌───────────┐  ┌───────────┐  │
│  │  WTO API     │  │  ePing  │  │  WITS     │  │  Saudi    │  │
│  │  (TPR/TBT    │  │  (SPS/  │  │  Tariff   │  │  Official │  │
│  │   /SPS/DS)   │  │   TBT)  │  │  Data     │  │  APIs     │  │
│  └──────────────┘  └─────────┘  └───────────┘  └───────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Service Breakdown

### 1. Data Ingestion Service
- **WTO Connector**: REST calls to `documents.wto.org`, `www.wto.org/api`
- **ePing Scraper**: Puppeteer-based scraper for TBT/SPS notifications
- **WITS Connector**: World Bank WITS tariff data API
- **Scheduler**: Cron-based (daily TPR, hourly ePing)
- **Queue**: Bull (Redis-backed) for async processing

### 2. Core API (FastAPI)
- RESTful + OpenAPI spec
- Modules: opportunities, notifications, tariffs, disputes, reports
- AI integration via Claude API

### 3. Analysis Engine
- **Rule Engine**: WTO agreement mapping (GATT/GATS/TBT/SPS)
- **NLP Pipeline**: Document classification, entity extraction, opportunity scoring
- **Opportunity Scorer**: HS code–based market access scoring matrix

### 4. Notification Service
- WebSocket (Socket.io) for real-time alerts
- Email (SendGrid) + SMS (Twilio) optional
- User preference–driven filtering

### 5. Report Generator
- Python-Docx for Word, ReportLab for PDF
- Executive summary templates

---

## Technology Stack

| Layer          | Technology                            |
|----------------|---------------------------------------|
| Frontend       | Next.js 14, TypeScript, TailwindCSS   |
| Backend        | Python FastAPI + Node.js (notifications)|
| Database       | PostgreSQL 15 + Elasticsearch 8       |
| Cache          | Redis 7                               |
| Queue          | Bull (Redis)                          |
| AI/NLP         | Claude API (Anthropic)                |
| Auth           | JWT + Role-Based Access Control       |
| Deployment     | Docker + Kubernetes (AWS EKS / Azure AKS)|
| Storage        | AWS S3 / Azure Blob                   |
| Monitoring     | Prometheus + Grafana                  |
| CI/CD          | GitHub Actions                        |

---

## Security Architecture

- TLS 1.3 everywhere
- JWT with refresh token rotation
- RBAC: ADMIN, ANALYST, EXPORTER, GOVERNMENT_ENTITY, VIEWER
- Rate limiting per role
- Audit log for all data access
- PII anonymization in logs
- Compliance with Saudi PDPL (Personal Data Protection Law)
