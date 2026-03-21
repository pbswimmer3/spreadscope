#!/bin/bash

# SpreadScope - Database Setup Script
# Run this on the host VM after 01_install_system_deps.sh

set -e

echo "🔄 Setting up SpreadScope database..."

# Read database password from config or prompt
if [ -f "/opt/spreadscope/config/config.yaml" ]; then
    DB_PASSWORD=$(grep -A2 "database:" /opt/spreadscope/config/config.yaml | grep "password:" | awk '{print $2}')
else
    echo "📝 Please enter a password for the spreadscope database user:"
    read -s DB_PASSWORD
    echo ""
fi

# Create database user and database
echo "👤 Creating database user and database..."
sudo -u postgres psql -v db_pass="$DB_PASSWORD" -c "CREATE USER spreadscope WITH PASSWORD :'db_pass';" || echo "User may already exist, continuing..."
sudo -u postgres psql -c "CREATE DATABASE spreadscope_db OWNER spreadscope;" || echo "Database may already exist, continuing..."
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE spreadscope_db TO spreadscope;"

# Enable TimescaleDB extension
echo "🔧 Enabling TimescaleDB extension..."
sudo -u postgres psql -d spreadscope_db -c "CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"

# Run schema.sql
echo "📊 Creating database schema..."
if [ -f "/opt/spreadscope/schema.sql" ]; then
    sudo -u postgres psql -d spreadscope_db -f /opt/spreadscope/schema.sql
else
    echo "❌ schema.sql not found at /opt/spreadscope/schema.sql"
    echo "Please copy the schema.sql file to /opt/spreadscope/ and run this script again."
    exit 1
fi

# Set up initial configuration data
echo "⚙️  Setting up initial configuration..."
sudo -u postgres psql -d spreadscope_db << EOF
-- Insert venue configurations
INSERT INTO venue_config (venue, display_name, venue_type, api_base_url, polling_interval_seconds, is_enabled, supports_assets) VALUES
('polygon_spot', 'Polygon Spot', 'spot', 'https://api.polygon.io', 60, true, '{"BTC","ETH","AAPL","TSLA","NVDA"}'),
('coinbase_spot', 'Coinbase Spot', 'spot', 'https://api.coinbase.com', 30, true, '{"BTC","ETH"}'),
('coinbase_perps', 'Coinbase Perps', 'perps', 'https://api.coinbase.com', 30, true, '{"BTC","ETH"}'),
('hyperliquid_perps', 'Hyperliquid Perps', 'perps', 'https://api.hyperliquid.xyz', 15, true, '{"BTC","ETH"}'),
('synthetix', 'Synthetix/Pyth Oracle', 'synthetic', 'https://hermes.pyth.network', 30, true, '{"BTC","ETH"}'),
('dydx', 'dYdX', 'perps', 'https://indexer.dydx.trade/v4', 30, true, '{"BTC","ETH"}')
ON CONFLICT (venue) DO NOTHING;

-- Insert initial tracked pairs
INSERT INTO tracked_pairs (asset, real_venue, synthetic_venue, threshold_pct, is_enabled) VALUES
('BTC', 'coinbase_spot', 'hyperliquid_perps', 0.5, true),
('ETH', 'coinbase_spot', 'hyperliquid_perps', 0.5, true),
('BTC', 'coinbase_spot', 'dydx', 0.5, true),
('ETH', 'coinbase_spot', 'dydx', 0.5, true),
('BTC', 'coinbase_spot', 'synthetix', 0.5, true),
('ETH', 'coinbase_spot', 'synthetix', 0.5, true)
ON CONFLICT (asset, real_venue, synthetic_venue) DO NOTHING;
EOF

echo "✅ Database setup completed successfully!"
echo ""
echo "Database connection details:"
echo "  Host: localhost"
echo "  Port: 5432"
echo "  Database: spreadscope_db"
echo "  User: spreadscope"
echo "  Password: [set in config.yaml]"