import os
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
)
