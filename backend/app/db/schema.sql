-- GridMerge schema (Req 5). Idempotent: safe to run on every startup.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS plans (
  id uuid PRIMARY KEY,
  utility text NOT NULL,
  source_url text NOT NULL,
  filename text,
  detected_format text NOT NULL,
  status text NOT NULL DEFAULT 'processing',   -- processing | complete | failed
  error text,
  project_count int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Added after the first release; ADD COLUMN keeps existing databases working.
ALTER TABLE plans ADD COLUMN IF NOT EXISTS page_range text;  -- e.g. "18-45"; NULL = all pages
-- SHA-256 of the committed snapshot CSV a loader plan came from (app/sources/snapshot.py);
-- startup reloads the source when the committed file changes. NULL for uploads.
ALTER TABLE plans ADD COLUMN IF NOT EXISTS snapshot_sha text;

CREATE TABLE IF NOT EXISTS projects (
  id serial PRIMARY KEY,
  plan_id uuid REFERENCES plans(id) ON DELETE CASCADE,
  utility text NOT NULL,
  state text,
  name text,
  type text,                        -- substation | transmission line | generation | NULL
  voltage_kv int,                   -- kV; NULL when unknown
  location_ref text,                -- substation/town/county text the geocoder saw
  geom geography(Point, 4326),      -- NULL when unresolved/unset (Req 4.4, 4.5)
  start_date date,
  end_date date,
  start_precision text,             -- year | quarter | month | day (Req 4.6)
  end_precision text,
  confidence real NOT NULL DEFAULT 0,
  source_url text,
  source_page int,
  raw_excerpt text,                 -- <= 2000 chars
  reviewed bool NOT NULL DEFAULT false,
  approximate bool NOT NULL DEFAULT false,      -- county-center fallback (Req 4.2, 9.4)
  requires_review bool NOT NULL DEFAULT false   -- geocoding could not place it (Req 4.4, 4.5)
);

CREATE INDEX IF NOT EXISTS projects_geom_gix ON projects USING GIST (geom);
CREATE INDEX IF NOT EXISTS projects_dates_ix ON projects (start_date, end_date);

-- Coordination briefs, keyed by the stable pair id "a_id-b_id" (a_id < b_id).
-- radius/pad record the thresholds the pair was flagged under so an edit can
-- re-run matching for exactly that pair (Req 13.4).
CREATE TABLE IF NOT EXISTS briefs (
  pair_id text PRIMARY KEY,
  a_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  b_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  text text NOT NULL,
  miles double precision NOT NULL,
  overlap_days int NOT NULL,
  radius double precision NOT NULL,
  pad int NOT NULL,
  stale bool NOT NULL DEFAULT false,
  generated_at timestamptz NOT NULL DEFAULT now()
);

-- Existing transmission lines from HIFLD: a reference layer (map backdrop, owner roster,
-- real routes for Req 17), never matched as planned projects. Loaded from the committed
-- snapshot by app startup or `python -m scripts.load_hifld`.
CREATE TABLE IF NOT EXISTS transmission_lines (
  id text PRIMARY KEY,              -- HIFLD ID
  owner text,                       -- HIFLD OWNER as published; NULL when not available
  owner_norm text,                  -- merged/renamed owner used for grouping (hifld.py)
  voltage_kv real,                  -- NULL when HIFLD has no voltage
  volt_class text,
  status text,
  line_type text,
  inferred bool,
  sub_1 text,                       -- endpoint substation names (often TAP*/UNKNOWN*)
  sub_2 text,
  source_date date,
  val_date date,
  geom geography(MultiLineString, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS transmission_lines_geom_gix ON transmission_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS transmission_lines_owner_ix ON transmission_lines (owner_norm);
