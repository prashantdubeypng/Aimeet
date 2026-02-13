#!/usr/bin/env bash
# Exit on error
set -o errexit

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Navigate to Django project directory
cd videocaller

# Collect static files
python manage.py collectstatic --no-input

# Run migrations
python manage.py migrate --no-input
