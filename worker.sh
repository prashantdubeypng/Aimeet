#!/bin/bash
set -e

cd /app/videocaller

# Start Django-Q worker
exec python manage.py qcluster
