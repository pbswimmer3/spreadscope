-- SpreadScope - Seed Data

INSERT INTO venue_config (venue, display_name, venue_type, api_base_url, polling_interval_seconds, is_enabled, supports_assets) VALUES
    ('coinbase_spot', 'Coinbase Spot', 'spot', 'https://api.coinbase.com', 30, true, '{BTC,ETH}'),
    ('hyperliquid_perps', 'Hyperliquid Perps', 'perps', 'https://api.hyperliquid.xyz', 15, true, '{BTC,ETH}'),
    ('dydx', 'dYdX v4', 'perps', 'https://indexer.dydx.trade/v4', 30, true, '{BTC,ETH}'),
    ('synthetix', 'Synthetix/Pyth Oracle', 'synthetic', 'https://hermes.pyth.network', 30, true, '{BTC,ETH}'),
    ('polygon_spot', 'Polygon.io Spot', 'spot', 'https://api.polygon.io', 60, true, '{BTC,ETH}'),
    ('coinbase_perps', 'Coinbase Perps', 'perps', 'https://api.coinbase.com', 30, false, '{BTC,ETH}')
ON CONFLICT (venue) DO NOTHING;

INSERT INTO tracked_pairs (asset, real_venue, synthetic_venue, threshold_pct, is_enabled) VALUES
    ('BTC', 'coinbase_spot', 'hyperliquid_perps', 0.5, true),
    ('ETH', 'coinbase_spot', 'hyperliquid_perps', 0.5, true),
    ('BTC', 'coinbase_spot', 'dydx', 0.5, true),
    ('ETH', 'coinbase_spot', 'dydx', 0.5, true),
    ('BTC', 'coinbase_spot', 'synthetix', 0.5, true),
    ('ETH', 'coinbase_spot', 'synthetix', 0.5, true),
    ('BTC', 'polygon_spot', 'hyperliquid_perps', 0.5, true),
    ('ETH', 'polygon_spot', 'hyperliquid_perps', 0.5, true)
ON CONFLICT (asset, real_venue, synthetic_venue) DO NOTHING;