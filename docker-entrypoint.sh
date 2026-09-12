#!/bin/sh
set -e

# ROLE controls what this container runs. Set it per Render service.
#   ROLE=combined     -> web + worker in ONE service via supervisord (recommended, cheapest)
#   ROLE=web          -> gunicorn only
#   ROLE=worker       -> celery worker on BOTH queues (heavy,light)
#   ROLE=worker_light -> celery worker on "light" queue only (for later split, if needed)
#   ROLE=worker_heavy -> celery worker on "heavy" queue only (for later split, if needed)
#   ROLE=beat         -> celery beat scheduler (only if/when you add periodic tasks)

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
    exec celery -A app.celery worker -Q heavy,light --concurrency="$CELERY_CONCURRENCY" --loglevel=info
    ;;
  worker_light)
    exec celery -A app.celery worker -Q light --concurrency="${CELERY_CONCURRENCY}" --loglevel=info
    ;;
  worker_heavy)
    exec celery -A app.celery worker -Q heavy --concurrency="${CELERY_CONCURRENCY}" --loglevel=info
    ;;
  beat)
    exec celery -A app.celery beat --loglevel=info
    ;;
  *)
    echo "Unknown ROLE: $ROLE" >&2
    exit 1
    ;;
esac