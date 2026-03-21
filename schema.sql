-- SpreadScope Database Schema
-- PostgreSQL + TimescaleDB

-- Enable TimescaleDB extension (run this first)
-- CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ============================================================================
-- Configuration Tables
-- ============================================================================

-- Venue configuration
CREATE TABLE venue_config (
    venue TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    venue_type TEXT NOT NULL CHECK (venue_type IN ('spot', 'perps', 'synthetic')),
    api_base_url TEXT NOT NULL,
    polling_interval_seconds INTEGER DEFAULT 30,
    is_enabled BOOLEAN DEFAULT true,
    supports_assets TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tracked pairs for spread calculation
CREATE TABLE tracked_pairs (
    id SERIAL PRIMARY KEY,
    asset TEXT NOT NULL,
    real_venue TEXT NOT NULL REFERENCES venue_config(venue),
    synthetic_venue TEXT NOT NULL REFERENCES venue_config(venue),
    threshold_pct DOUBLE PRECISION DEFAULT 0.5,
    is_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(asset, real_venue, synthetic_venue)
);

-- ============================================================================
-- Time-Series Data Tables (TimescaleDB Hypertables)
-- ============================================================================

-- Raw price observations from all venues
CREATE TABLE price_observations (
    time TIMESTAMPTZ NOT NULL,
    asset TEXT NOT NULL,
    venue TEXT NOT NULL REFERENCES venue_config(venue),
    price DOUBLE PRECISION NOT NULL CHECK (price > 0),
    volume_24h DOUBLE PRECISION,
    funding_rate DOUBLE PRECISION,
    open_interest DOUBLE PRECISION,
    extra_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to hypertable with 7-day chunk interval
SELECT create_hypertable('price_observations', 'time', chunk_time_interval => INTERVAL '7 days');

-- Indexes for fast lookups
CREATE INDEX idx_price_observations_asset_venue_time 
    ON price_observations (asset, venue, time DESC);

CREATE INDEX idx_price_observations_time 
    ON price_observations (time DESC);

-- Calculated spreads between real and synthetic venues
CREATE TABLE spreads (
    time TIMESTAMPTZ NOT NULL,
    asset TEXT NOT NULL,
    real_venue TEXT NOT NULL,
    synthetic_venue TEXT NOT NULL,
    real_price DOUBLE PRECISION NOT NULL,
    synthetic_price DOUBLE PRECISION NOT NULL,
    spread_abs DOUBLE PRECISION NOT NULL,
    spread_pct DOUBLE PRECISION NOT NULL,
    venue_pair TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Convert to hypertable
SELECT create_hypertable('spreads', 'time', chunk_time_interval => INTERVAL '7 days');

-- Indexes for spread queries
CREATE INDEX idx_spreads_asset_pair_time 
    ON spreads (asset, venue_pair, time DESC);

CREATE INDEX idx_spreads_spread_pct_time 
    ON spreads (spread_pct, time DESC);

-- ============================================================================
-- Opportunity Events (Regular Table)
-- ============================================================================

CREATE TABLE opportunity_events (
    id SERIAL PRIMARY KEY,
    asset TEXT NOT NULL,
    venue_pair TEXT NOT NULL,
    threshold_pct DOUBLE PRECISION NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    duration_seconds INTEGER,
    peak_spread_pct DOUBLE PRECISION,
    avg_spread_pct DOUBLE PRECISION,
    entry_spread_pct DOUBLE PRECISION,
    exit_spread_pct DOUBLE PRECISION,
    observations_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for opportunity queries
CREATE INDEX idx_opportunity_events_asset_pair 
    ON opportunity_events (asset, venue_pair);

CREATE INDEX idx_opportunity_events_opened_at 
    ON opportunity_events (opened_at DESC);

CREATE INDEX idx_opportunity_events_closed_at
    ON opportunity_events (closed_at DESC) WHERE closed_at IS NOT NULL;

-- ============================================================================
-- Funding Rate Snapshots (TimescaleDB Hypertable)
-- ============================================================================

CREATE TABLE funding_rate_snapshots (
    time TIMESTAMPTZ NOT NULL,
    asset TEXT NOT NULL,
    venue TEXT NOT NULL REFERENCES venue_config(venue),
    funding_rate DOUBLE PRECISION NOT NULL,
    annualized_rate DOUBLE PRECISION NOT NULL,
    next_funding_time TIMESTAMPTZ,
    mark_price DOUBLE PRECISION,
    index_price DOUBLE PRECISION,
    open_interest DOUBLE PRECISION,
    volume_24h DOUBLE PRECISION,
    extra_data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

SELECT create_hypertable('funding_rate_snapshots', 'time', chunk_time_interval => INTERVAL '7 days');

CREATE INDEX idx_funding_rate_asset_venue_time
    ON funding_rate_snapshots (asset, venue, time DESC);

CREATE INDEX idx_funding_rate_annualized
    ON funding_rate_snapshots (annualized_rate, time DESC);

-- Keep funding rate snapshots for 1 year
SELECT add_retention_policy('funding_rate_snapshots', INTERVAL '1 year');

-- ============================================================================
-- Carry Signals (Bot-Readable)
-- ============================================================================

CREATE TABLE carry_signals (
    id SERIAL PRIMARY KEY,
    asset TEXT NOT NULL,
    spot_venue TEXT NOT NULL,
    perp_venue TEXT NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('entry', 'exit', 'update')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'executed', 'expired', 'cancelled')),

    -- Funding rate data at signal time
    funding_rate_8h DOUBLE PRECISION NOT NULL,
    annualized_rate DOUBLE PRECISION NOT NULL,
    consecutive_positive_periods INTEGER DEFAULT 0,

    -- Price data at signal time
    spot_price DOUBLE PRECISION NOT NULL,
    perp_price DOUBLE PRECISION NOT NULL,
    entry_spread_pct DOUBLE PRECISION NOT NULL,

    -- Position sizing (based on portfolio config)
    suggested_size_usd DOUBLE PRECISION NOT NULL,
    suggested_leverage DOUBLE PRECISION DEFAULT 1.0,
    portfolio_capital_usd DOUBLE PRECISION NOT NULL,

    -- Expected returns
    expected_daily_return_usd DOUBLE PRECISION,
    expected_annual_return_usd DOUBLE PRECISION,
    expected_apy_pct DOUBLE PRECISION,

    -- Risk
    estimated_fees_usd DOUBLE PRECISION,
    breakeven_hours DOUBLE PRECISION,

    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    executed_at TIMESTAMPTZ,
    notes TEXT,

    -- Link to parent signal (for exit signals referencing an entry)
    parent_signal_id INTEGER REFERENCES carry_signals(id)
);

CREATE INDEX idx_carry_signals_active
    ON carry_signals (status, asset, perp_venue) WHERE status = 'active';

CREATE INDEX idx_carry_signals_created
    ON carry_signals (created_at DESC);

-- ============================================================================
-- Funding Rate Hourly Aggregates
-- ============================================================================

CREATE MATERIALIZED VIEW funding_rates_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    asset,
    venue,
    COUNT(*) AS observations,
    AVG(funding_rate) AS avg_funding_rate,
    AVG(annualized_rate) AS avg_annualized_rate,
    MIN(funding_rate) AS min_funding_rate,
    MAX(funding_rate) AS max_funding_rate,
    AVG(open_interest) AS avg_open_interest
FROM funding_rate_snapshots
GROUP BY 1, 2, 3
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'funding_rates_hourly',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- ============================================================================
-- Continuous Aggregates for Historical Analysis
-- ============================================================================

-- Hourly spreads aggregate
CREATE MATERIALIZED VIEW spreads_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    asset,
    venue_pair,
    COUNT(*) AS observations,
    AVG(spread_pct) AS avg_spread_pct,
    MIN(spread_pct) AS min_spread_pct,
    MAX(spread_pct) AS max_spread_pct,
    STDDEV(spread_pct) AS stddev_spread_pct,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY spread_pct) AS median_spread_pct
FROM spreads
GROUP BY 1, 2, 3
WITH NO DATA;

-- Daily spreads aggregate
CREATE MATERIALIZED VIEW spreads_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    asset,
    venue_pair,
    COUNT(*) AS observations,
    AVG(spread_pct) AS avg_spread_pct,
    MIN(spread_pct) AS min_spread_pct,
    MAX(spread_pct) AS max_spread_pct,
    STDDEV(spread_pct) AS stddev_spread_pct
FROM spreads
GROUP BY 1, 2, 3
WITH NO DATA;

-- Hourly price aggregates
CREATE MATERIALIZED VIEW prices_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    asset,
    venue,
    COUNT(*) AS observations,
    AVG(price) AS avg_price,
    MIN(price) AS min_price,
    MAX(price) AS max_price,
    AVG(volume_24h) AS avg_volume_24h,
    AVG(funding_rate) AS avg_funding_rate
FROM price_observations
GROUP BY 1, 2, 3
WITH NO DATA;

-- ============================================================================
-- Retention Policies
-- ============================================================================

-- Keep raw price observations for 90 days
SELECT add_retention_policy('price_observations', INTERVAL '90 days');

-- Keep raw spreads for 180 days
SELECT add_retention_policy('spreads', INTERVAL '180 days');

-- Keep hourly aggregates for 1 year
SELECT add_retention_policy('spreads_hourly', INTERVAL '1 year');
SELECT add_retention_policy('prices_hourly', INTERVAL '1 year');

-- Keep daily aggregates for 2 years
SELECT add_retention_policy('spreads_daily', INTERVAL '2 years');

-- ============================================================================
-- Continuous Aggregate Refresh Policies
-- ============================================================================

-- Refresh hourly spreads every hour, covering last 7 days
SELECT add_continuous_aggregate_policy(
    'spreads_hourly',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- Refresh daily spreads every day, covering last 30 days
SELECT add_continuous_aggregate_policy(
    'spreads_daily',
    start_offset => INTERVAL '30 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day'
);

-- Refresh hourly prices every hour, covering last 7 days
SELECT add_continuous_aggregate_policy(
    'prices_hourly',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- ============================================================================
-- Helper Functions and Views
-- ============================================================================

-- View for current spreads (last 5 minutes)
CREATE OR REPLACE VIEW current_spreads AS
SELECT 
    s.*,
    p1.price as current_real_price,
    p2.price as current_synthetic_price,
    EXTRACT(EPOCH FROM (NOW() - s.time)) as seconds_ago
FROM spreads s
LEFT JOIN LATERAL (
    SELECT price FROM price_observations 
    WHERE asset = s.asset AND venue = s.real_venue 
    ORDER BY time DESC LIMIT 1
) p1 ON true
LEFT JOIN LATERAL (
    SELECT price FROM price_observations 
    WHERE asset = s.asset AND venue = s.synthetic_venue 
    ORDER BY time DESC LIMIT 1
) p2 ON true
WHERE s.time > NOW() - INTERVAL '5 minutes'
ORDER BY s.time DESC;

-- View for open opportunities
CREATE OR REPLACE VIEW open_opportunities AS
SELECT 
    o.*,
    EXTRACT(EPOCH FROM (NOW() - o.opened_at)) as duration_seconds_open,
    cs.spread_pct as current_spread_pct
FROM opportunity_events o
LEFT JOIN current_spreads cs ON cs.asset = o.asset AND cs.venue_pair = o.venue_pair
WHERE o.closed_at IS NULL;

-- Function to close an opportunity
CREATE OR REPLACE FUNCTION close_opportunity(
    p_opportunity_id INTEGER,
    p_exit_spread_pct DOUBLE PRECISION
) RETURNS VOID AS $$
DECLARE
    v_duration_seconds INTEGER;
    v_avg_spread_pct DOUBLE PRECISION;
BEGIN
    -- Calculate duration and average spread
    SELECT 
        EXTRACT(EPOCH FROM (NOW() - opened_at)),
        AVG(spread_pct)
    INTO 
        v_duration_seconds,
        v_avg_spread_pct
    FROM spreads 
    WHERE asset = (SELECT asset FROM opportunity_events WHERE id = p_opportunity_id)
      AND venue_pair = (SELECT venue_pair FROM opportunity_events WHERE id = p_opportunity_id)
      AND time BETWEEN (SELECT opened_at FROM opportunity_events WHERE id = p_opportunity_id) AND NOW();
    
    -- Update the opportunity
    UPDATE opportunity_events 
    SET 
        closed_at = NOW(),
        duration_seconds = v_duration_seconds,
        avg_spread_pct = COALESCE(v_avg_spread_pct, 0),
        exit_spread_pct = p_exit_spread_pct,
        updated_at = NOW()
    WHERE id = p_opportunity_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Triggers for Updated Timestamps
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_venue_config_updated_at
    BEFORE UPDATE ON venue_config
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tracked_pairs_updated_at
    BEFORE UPDATE ON tracked_pairs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_opportunity_events_updated_at
    BEFORE UPDATE ON opportunity_events
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Initial Data (Optional - can be loaded separately)
-- ============================================================================

-- Note: Venue configurations and tracked pairs will be loaded by 02_setup_database.sh
-- This keeps the schema clean and separate from initial data.

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE price_observations IS 'Raw price observations from all venues, stored as TimescaleDB hypertable';
COMMENT ON TABLE spreads IS 'Calculated spreads between real and synthetic venues, stored as TimescaleDB hypertable';
COMMENT ON TABLE opportunity_events IS 'Tracked opportunity events when spreads exceed thresholds';
COMMENT ON TABLE venue_config IS 'Configuration for price data sources (venues)';
COMMENT ON TABLE tracked_pairs IS 'Pairs to track for spread calculation';

COMMENT ON COLUMN price_observations.funding_rate IS 'Current funding rate for perpetual futures venues';
COMMENT ON COLUMN price_observations.open_interest IS 'Open interest for perpetual futures venues';
COMMENT ON COLUMN spreads.spread_pct IS 'Percentage spread: (synthetic - real) / real * 100';
COMMENT ON COLUMN spreads.venue_pair IS 'Concatenated venue pair: real_venue:synthetic_venue';

-- ============================================================================
-- Schema Version
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    description TEXT
);

INSERT INTO schema_version (version, description) VALUES 
    ('1.0.0', 'Initial SpreadScope schema with TimescaleDB hypertables and continuous aggregates')
ON CONFLICT (version) DO NOTHING;