#!/bin/sh
set -e

ROLE="${ROLE:-combined}"
export CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-2}"

case "$ROLE" in
  combined)
    exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
    ;;
  web)
    exec gunicorn run:app --bind 0.0.0.0:"$PORT" --workers 1 --threads 4 --timeout 120
    ;;
  worker)
    exec celery -A celery_worker.celery worker -Q heavy,light --concurrency="$CELERY_CONCURRENCY" --loglevel=info
    ;;
  worker_light)
    exec celery -A celery_worker.celery worker -Q light --concurrency="${CELERY_CONCURRENCY}" --loglevel=info
    ;;
  worker_heavy)
    exec celery -A celery_worker.celery worker -Q heavy --concurrency="${CELERY_CONCURRENCY}" --loglevel=info
    ;;
  beat)
    exec celery -A celery_worker.celery beat --loglevel=info
    ;;
  *)
    echo "Unknown ROLE: $ROLE" >&2
    exit 1
    ;;
esac