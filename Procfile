web: gunicorn run:app --bind 0.0.0.0:$PORT
worker: celery -A celery_worker.celery worker --loglevel=info -P solo -Q celery,heavy