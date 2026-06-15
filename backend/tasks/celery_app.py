import sys
import os
from dotenv import load_dotenv

# Load environment variables and set python path
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_norm_backend = os.path.normcase(_BACKEND_DIR)
if not any(os.path.normcase(p) == _norm_backend for p in sys.path):
    sys.path.insert(0, _BACKEND_DIR)

load_dotenv(os.path.join(_BACKEND_DIR, ".env"))

from celery import Celery

app = Celery(
    "talentmatch",
    broker=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    include=["tasks.pipeline"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=False,      # Explicit False
    task_store_eager_result=False, # Explicit False
)
