import json
import os

import redis

from .models import Article


QUEUE_PREFIX = "ai_queue"
DEDUP_PREFIX = "ai_queued"


def get_redis():
    return redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        decode_responses=True,
    )


def enqueue_pending_articles(project, limit=500):
    client = get_redis()
    queued = 0

    articles = (
        Article.objects
        .filter(ai_status="pending", ai_headline="")
        .order_by("id")[:limit]
    )

    queue_name = f"{QUEUE_PREFIX}:{project}"

    for article in articles:
        job = {
            "project": project,
            "article_id": article.id,
            "title": article.title,
            "summary": article.summary,
            "category": article.category,
            "attempts": 0,
        }

        dedup_key = f"{DEDUP_PREFIX}:{project}:{article.id}"

        if client.set(dedup_key, "1", nx=True, ex=604800):
            client.rpush(queue_name, json.dumps(job))
            queued += 1

    return queued
