"""
Celery worker entrypoint.

Run with:
    celery -A celery_worker.celery worker --loglevel=info -P solo   (Windows)
    celery -A celery_worker.celery worker --loglevel=info           (Linux/macOS)
"""
from app import create_app

# Create the Flask app – this calls make_celery() and configures the global celery
flask_app = create_app()
flask_app.app_context().push()

# Now import the configured celery instance and register tasks
from extensions import celery
from app.tools import tasks  # noqa: F401, E402