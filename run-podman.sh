#!/bin/bash

# Run the container using Podman
echo "Starting GLPI API container with Podman..."

podman run -d \
  --name glpi-api \
  -p 5000:5000 \
  --restart unless-stopped \
  glpi-api:latest

echo "✓ Container started!"
echo ""
echo "API is now available at: http://localhost:5000"
echo ""
echo "To view logs:"
echo "  podman logs -f glpi-api"
echo ""
echo "To stop the container:"
echo "  podman stop glpi-api"
echo ""
echo "To restart the container:"
echo "  podman restart glpi-api"
