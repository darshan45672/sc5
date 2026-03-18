#!/bin/bash

# Build the container image using Podman
echo "Building GLPI API container with Podman..."

podman build -f deployment/Dockerfile -t glpi-api:latest .

echo "✓ Build complete!"
echo ""
echo "To run the container:"
echo "  podman run -d -p 5000:5000 --name glpi-api glpi-api:latest"
echo ""
echo "To view logs:"
echo "  podman logs -f glpi-api"
echo ""
echo "To stop the container:"
echo "  podman stop glpi-api"
echo ""
echo "To remove the container:"
echo "  podman rm glpi-api"
