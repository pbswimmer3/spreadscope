#!/bin/bash

# SpreadScope - Services Enablement Script
# Run this on the host VM after database setup

set -e

echo "🔄 Setting up SpreadScope systemd services..."

# Create spreadscope user if it doesn't exist
if ! id "spreadscope" &>/dev/null; then
    echo "👤 Creating spreadscope user..."
    sudo useradd -r -s /bin/false -m -d /opt/spreadscope spreadscope
fi

# Set ownership of project directory
echo "📁 Setting directory permissions..."
sudo chown -R spreadscope:spreadscope /opt/spreadscope
sudo chmod 755 /opt/spreadscope

# Copy systemd service files
echo "⚙️  Installing systemd services..."
sudo cp /opt/spreadscope/services/*.service /etc/systemd/system/

# Reload systemd
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

# Enable and start services
echo "🚀 Enabling and starting services..."
for service in spreadscope-ingestion spreadscope-calculator spreadscope-dashboard; do
    echo "  - $service"
    sudo systemctl enable $service
    sudo systemctl start $service
done

# Wait a moment for services to start
sleep 3

# Check service status
echo "📊 Service status:"
for service in spreadscope-ingestion spreadscope-calculator spreadscope-dashboard; do
    status=$(sudo systemctl is-active $service)
    echo "  - $service: $status"
done

echo ""
echo "✅ Services setup completed!"
echo ""
echo "To check logs:"
echo "  sudo journalctl -u spreadscope-ingestion -f"
echo "  sudo journalctl -u spreadscope-calculator -f"
echo "  sudo journalctl -u spreadscope-dashboard -f"
echo ""
echo "To stop services:"
echo "  sudo systemctl stop spreadscope-ingestion spreadscope-calculator spreadscope-dashboard"
echo ""
echo "Dashboard should be available at: http://$(hostname -I | awk '{print $1}'):8050"