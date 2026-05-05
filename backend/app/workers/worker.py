from redis import Redis
from rq import Queue, Worker

from app.core.config import get_settings
from app.ingestion.jobs import INGESTION_QUEUE_NAME


def main() -> None:
    settings = get_settings()
    redis_connection = Redis.from_url(settings.redis_url)
    queue = Queue(INGESTION_QUEUE_NAME, connection=redis_connection)
    worker = Worker([queue], connection=redis_connection)
    worker.work()


if __name__ == "__main__":
    main()
