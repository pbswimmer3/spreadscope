#!/bin/bash

# SpreadScope - System Dependencies Installation Script
# Run this on the host VM (Ubuntu 24.04) with sudo privileges

set -e

echo "🔄 Installing system dependencies for SpreadScope..."

# Update package lists
sudo apt-get update

# Install PostgreSQL 16 and required system packages
echo "📦 Installing PostgreSQL 16 and system packages..."
sudo apt-get install -y \
    postgresql-16 \
    postgresql-client-16 \
    postgresql-contrib-16 \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libpq-dev \
    gnupg \
    apt-transport-https \
    lsb-release \
    wget

# Add TimescaleDB repository (using signed-by for Ubuntu 24.04+)
echo "📦 Adding TimescaleDB repository..."
wget --quiet -O /tmp/timescaledb.asc https://packagecloud.io/timescale/timescaledb/gpgkey
sudo install -m 0644 /tmp/timescaledb.asc /usr/share/keyrings/timescaledb.asc
echo "deb [signed-by=/usr/share/keyrings/timescaledb.asc] https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" | sudo tee /etc/apt/sources.list.d/timescaledb.list

# Update package lists again
sudo apt-get update

# Install TimescaleDB for PostgreSQL 16
echo "📦 Installing TimescaleDB extension..."
sudo apt-get install -y timescaledb-2-postgresql-16

# Run TimescaleDB tuning wizard
echo "⚙️  Running TimescaleDB tuning wizard..."
sudo timescaledb-tune --quiet --yes

# Restart PostgreSQL to apply changes
echo "🔄 Restarting PostgreSQL..."
sudo systemctl restart postgresql

# Create project directory structure
echo "📁 Creating project directories..."
sudo mkdir -p /opt/spreadscope/{logs,config}
sudo chown -R $USER:$USER /opt/spreadscope

# Create Python virtual environment
echo "🐍 Creating Python virtual environment..."
python3 -m venv /opt/spreadscope/venv

# Install Python dependencies
echo "📦 Installing Python dependencies..."
/opt/spreadscope/venv/bin/pip install --upgrade pip
/opt/spreadscope/venv/bin/pip install -r /opt/spreadscope/requirements.txt

echo "✅ System dependencies installed successfully!"
echo ""
echo "Next steps:"
echo "1. Run 02_setup_database.sh to set up the database"
echo "2. Copy your config.yaml to /opt/spreadscope/config/"
echo "3. Run 03_enable_services.sh to start the system"