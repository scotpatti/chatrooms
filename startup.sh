#!/bin/bash
set -e
echo "Running database migrations..."
flask db upgrade
echo "Starting gunicorn..."
exec gunicorn app:app --bind 0.0.0.0:8000 --workers 2 --timeout 120
