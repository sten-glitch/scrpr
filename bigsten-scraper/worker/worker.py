"""
Optional entry point: python -m worker.worker
Same queues and connection as: rq worker high normal --url $REDIS_URL
"""
import sys
from redis import Redis
from rq import Worker, Queue

from config.settings import REDIS_URL

if __name__ == "__main__":
    conn = Redis.from_url(REDIS_URL)
    queues = [Queue("high", connection=conn), Queue("normal", connection=conn)]
    worker = Worker(queues, connection=conn)
    worker.work()
