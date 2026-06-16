import os
from dotenv import load_dotenv
from celery import Celery

# Load environment variables from the parent backend folder or root
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

def make_celery() -> Celery:
    app = Celery(
        "talentmatch",
        broker=os.getenv(
            "RABBITMQ_URL",
            "amqp://guest:guest@127.0.0.1:5672/"
        ),
        backend=os.getenv(
            "REDIS_URL",
            "redis://127.0.0.1:6379/0"
        ),
        include=["tasks.pipeline"],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_always_eager=False,        # EXPLICIT — never run inline
        task_store_eager_result=False,  # EXPLICIT
        result_expires=3600,            # results expire after 1 hour
        broker_connection_retry_on_startup=True,
    )
    return app

app = make_celery()
