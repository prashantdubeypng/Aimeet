#!/bin/bash
set -e

cd /app/videocaller

# Run migrations
python manage.py migrate --noinput

# Collect static files (if needed)
python manage.py collectstatic --noinput

# Start Daphne web server
exec daphne -b 0.0.0.0 -p 8000 videocaller.asgi:application
