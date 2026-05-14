-- ============================================================
-- WTO Trade Intelligence Platform — Database Schema
-- PostgreSQL 15+
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- For full-text search

-- ============================================================
-- USERS & ROLES
-- ============================================================
CREATE TYPE user_role AS ENUM (
  'ADMIN', 'ANALYST', 'EXPORTER', 'GOVERNMENT_ENTITY', 'VIEWER'
);

CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email           VARCHAR(255) UNIQUE NOT NULL,
  password_hash   TEXT NOT NULL,
  full_name       VARCHAR(255) NOT NULL,
  role            user_role NOT NULL DEFAULT 'VIEWER',
  organization    VARCHAR(255),
  is_active       BOOLEAN DEFAULT TRUE,
  last_login      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_preferences (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  sectors         TEXT[],       -- e.g. ['agriculture', 'chemicals']
  countries       TEXT[],       -- ISO-3166 alpha-3 codes
  hs_codes        TEXT[],       -- e.g. ['0801', '2709']
  alert_email     BOOLEAN DEFAULT TRUE,
  alert_in_app    BOOLEAN DEFAULT TRUE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- COUNTRIES & HS CODES (Reference tables)
-- ============================================================
CREATE TABLE countries (
  code            VARCHAR(3) PRIMARY KEY,  -- ISO-3166 alpha-3
  code_alpha2     VARCHAR(2),
  name_en         VARCHAR(255) NOT NULL,
  name_ar         VARCHAR(255),
  region          VARCHAR(100),
  is_wto_member   BOOLEAN DEFAULT TRUE,
  accession_date  DATE
);

CREATE TABLE hs_codes (
  code            VARCHAR(10) PRIMARY KEY,  -- e.g. '080110'
  level           SMALLINT NOT NULL,        -- 2, 4, or 6 digit
  description_en  TEXT NOT NULL,
  description_ar  TEXT,
  section         VARCHAR(10),
  chapter         VARCHAR(2),
  parent_code     VARCHAR(10) REFERENCES hs_codes(code)
);

-- ============================================================
-- WTO AGREEMENTS REFERENCE
-- ============================================================
CREATE TABLE wto_agreements (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  code            VARCHAR(20) UNIQUE NOT NULL,  -- e.g. 'GATT1994', 'TBT', 'SPS'
  name_en         TEXT NOT NULL,
  name_ar         TEXT,
  articles        JSONB,  -- { "III": "National Treatment", ... }
  effective_date  DATE
);

-- ============================================================
-- TPR — TRADE POLICY REVIEWS
-- ============================================================
CREATE TYPE tpr_status AS ENUM ('DRAFT', 'PUBLISHED', 'ARCHIVED');

CREATE TABLE tpr_reports (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  wto_doc_symbol  VARCHAR(100) UNIQUE,  -- e.g. 'WT/TPR/S/436'
  country_code    VARCHAR(3) REFERENCES countries(code),
  review_date     DATE,
  publication_url TEXT,
  raw_text        TEXT,
  summary_en      TEXT,
  summary_ar      TEXT,
  status          tpr_status DEFAULT 'PUBLISHED',
  ingested_at     TIMESTAMPTZ DEFAULT NOW(),
  last_updated    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE tpr_sections (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tpr_id          UUID REFERENCES tpr_reports(id) ON DELETE CASCADE,
  section_code    VARCHAR(50),  -- e.g. 'I.1', 'II.3'
  title           TEXT,
  content         TEXT,
  key_findings    JSONB,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- NOTIFICATIONS — TBT / SPS
-- ============================================================
CREATE TYPE notification_type AS ENUM ('TBT', 'SPS', 'OTHER');
CREATE TYPE notification_status AS ENUM ('NEW', 'ANALYZED', 'ALERT_SENT', 'ARCHIVED');

CREATE TABLE wto_notifications (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  wto_symbol        VARCHAR(100) UNIQUE,
  notification_type notification_type NOT NULL,
  notifying_country VARCHAR(3) REFERENCES countries(code),
  title             TEXT NOT NULL,
  description       TEXT,
  affected_products TEXT[],     -- HS codes
  publication_date  DATE,
  comment_deadline  DATE,
  full_text_url     TEXT,
  raw_content       TEXT,
  status            notification_status DEFAULT 'NEW',
  ingested_at       TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- TARIFF DATA
-- ============================================================
CREATE TABLE tariff_schedules (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  country_code    VARCHAR(3) REFERENCES countries(code),
  hs_code         VARCHAR(10) REFERENCES hs_codes(code),
  year            SMALLINT NOT NULL,
  mfn_rate        NUMERIC(8,4),   -- MFN applied rate (%)
  bound_rate      NUMERIC(8,4),   -- WTO bound rate (%)
  preferential    JSONB,          -- {partner_code: rate}
  source          VARCHAR(50),    -- 'WITS', 'WTO_TAO', 'ITC'
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(country_code, hs_code, year)
);

-- ============================================================
-- DISPUTE SETTLEMENT
-- ============================================================
CREATE TYPE ds_status AS ENUM (
  'CONSULTATIONS', 'PANEL', 'APPEAL', 'ADOPTED', 'COMPLIANCE', 'CLOSED'
);

CREATE TABLE dispute_settlements (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  ds_number       VARCHAR(20) UNIQUE NOT NULL,  -- e.g. 'DS600'
  title           TEXT NOT NULL,
  complainant     VARCHAR(3) REFERENCES countries(code),
  respondent      VARCHAR(3) REFERENCES countries(code),
  third_parties   TEXT[],
  agreements      TEXT[],         -- WTO agreement codes
  affected_hs     TEXT[],         -- HS codes
  current_status  ds_status,
  initiated_date  DATE,
  summary         TEXT,
  wto_url         TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- OPPORTUNITIES
-- ============================================================
CREATE TYPE opportunity_type AS ENUM (
  'MARKET_ACCESS', 'REGULATORY_CHANGE', 'TARIFF_REDUCTION',
  'NEW_MARKET', 'COMPLIANCE_RISK', 'DISPUTE_OUTCOME'
);
CREATE TYPE opportunity_priority AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW');

CREATE TABLE export_opportunities (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title           TEXT NOT NULL,
  title_ar        TEXT,
  opportunity_type opportunity_type NOT NULL,
  priority        opportunity_priority DEFAULT 'MEDIUM',
  score           NUMERIC(5,2),  -- 0-100 opportunity score
  target_country  VARCHAR(3) REFERENCES countries(code),
  hs_codes        TEXT[],
  description     TEXT,
  description_ar  TEXT,
  legal_basis     JSONB,  -- [{agreement: 'TBT', article: '2.7', text: '...'}]
  source_type     VARCHAR(50),  -- 'TPR', 'NOTIFICATION', 'TARIFF', 'DISPUTE'
  source_id       UUID,
  ai_analysis     TEXT,
  recommendations JSONB,
  is_active       BOOLEAN DEFAULT TRUE,
  expires_at      DATE,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- ALERTS & NOTIFICATIONS (User-facing)
-- ============================================================
CREATE TYPE alert_status AS ENUM ('PENDING', 'SENT', 'READ', 'DISMISSED');

CREATE TABLE user_alerts (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
  opportunity_id  UUID REFERENCES export_opportunities(id),
  notification_id UUID REFERENCES wto_notifications(id),
  title           TEXT NOT NULL,
  body            TEXT,
  status          alert_status DEFAULT 'PENDING',
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  read_at         TIMESTAMPTZ
);

-- ============================================================
-- REPORTS
-- ============================================================
CREATE TYPE report_format AS ENUM ('PDF', 'DOCX', 'XLSX', 'JSON');
CREATE TYPE report_status AS ENUM ('QUEUED', 'GENERATING', 'READY', 'FAILED');

CREATE TABLE generated_reports (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID REFERENCES users(id),
  title           TEXT NOT NULL,
  report_type     VARCHAR(50),
  format          report_format DEFAULT 'PDF',
  status          report_status DEFAULT 'QUEUED',
  parameters      JSONB,   -- filters used to generate
  file_url        TEXT,
  file_size_bytes BIGINT,
  generated_at    TIMESTAMPTZ,
  expires_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- AUDIT LOG
-- ============================================================
CREATE TABLE audit_logs (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id         UUID REFERENCES users(id),
  action          VARCHAR(100) NOT NULL,
  resource_type   VARCHAR(100),
  resource_id     UUID,
  ip_address      INET,
  user_agent      TEXT,
  metadata        JSONB,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INGESTION JOBS (Tracking data pipeline runs)
-- ============================================================
CREATE TYPE job_status AS ENUM ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL');

CREATE TABLE ingestion_jobs (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  source          VARCHAR(50) NOT NULL,  -- 'WTO_TPR', 'EPING', 'WITS'
  status          job_status DEFAULT 'RUNNING',
  records_fetched INTEGER DEFAULT 0,
  records_saved   INTEGER DEFAULT 0,
  errors          JSONB,
  started_at      TIMESTAMPTZ DEFAULT NOW(),
  completed_at    TIMESTAMPTZ
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_tpr_country ON tpr_reports(country_code);
CREATE INDEX idx_tpr_date ON tpr_reports(review_date DESC);
CREATE INDEX idx_notif_type ON wto_notifications(notification_type);
CREATE INDEX idx_notif_country ON wto_notifications(notifying_country);
CREATE INDEX idx_notif_date ON wto_notifications(publication_date DESC);
CREATE INDEX idx_notif_status ON wto_notifications(status);
CREATE INDEX idx_tariff_country_hs ON tariff_schedules(country_code, hs_code);
CREATE INDEX idx_opp_country ON export_opportunities(target_country);
CREATE INDEX idx_opp_priority ON export_opportunities(priority, score DESC);
CREATE INDEX idx_opp_type ON export_opportunities(opportunity_type);
CREATE INDEX idx_alerts_user ON user_alerts(user_id, status);
CREATE INDEX idx_audit_user ON audit_logs(user_id, created_at DESC);

-- Full text search indexes
CREATE INDEX idx_tpr_fts ON tpr_reports USING GIN(to_tsvector('english', COALESCE(raw_text, '') || ' ' || COALESCE(summary_en, '')));
CREATE INDEX idx_opp_fts ON export_opportunities USING GIN(to_tsvector('english', title || ' ' || COALESCE(description, '')));
