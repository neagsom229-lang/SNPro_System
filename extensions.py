from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from celery import Celery, shared_task
import ssl

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)

# Celery instance (configured by make_celery)
celery = None


def make_celery(app):
    global celery

    broker_url = app.config["CELERY_BROKER_URL"]
    backend_url = app.config["CELERY_RESULT_BACKEND"]

    celery = Celery(
        app.import_name,
        broker=broker_url,
        backend=backend_url,
    )

    celery.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_soft_time_limit=1800,
        task_time_limit=1900,
        task_acks_late=True,
        worker_max_tasks_per_child=50,
        worker_prefetch_multiplier=1,          # <-- prevents queue starvation
        task_routes={
            "app.tools.tasks.task_auto_edit_video": {"queue": "heavy"},
            "app.tools.tasks.task_enhance_video": {"queue": "heavy"},
            "app.tools.tasks.task_images_to_video": {"queue": "heavy"},
            # all other tasks go to "light" queue (default)
        },
        # --- Recommended: retry broker connection at startup instead of crashing ---
        broker_connection_retry_on_startup=True,
    )

    # --- FIX: Configure SSL if using TLS (rediss://) ---
    # Upstash (and most cloud Redis providers) require TLS. Celery needs explicit
    # SSL options when the URL starts with "rediss://", otherwise it raises:
    #   ValueError: A rediss:// URL must have parameter ssl_cert_reqs ...
    #
    # IMPORTANT: Use the ssl.CERT_NONE constant (an integer), NOT the string
    # "CERT_NONE". The redis-py library expects the integer constant.
    if isinstance(broker_url, str) and broker_url.startswith("rediss://"):
        celery.conf.broker_use_ssl = {
            "ssl_cert_reqs": ssl.CERT_NONE,
        }
    if isinstance(backend_url, str) and backend_url.startswith("rediss://"):
        celery.conf.redis_backend_use_ssl = {
            "ssl_cert_reqs": ssl.CERT_NONE,
        }

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery