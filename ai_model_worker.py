import json
import os
import time
import uuid

import psycopg
import redis
import torch
from dotenv import dotenv_values
from transformers import AutoModelForCausalLM, AutoTokenizer


REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
MODEL_PATH = os.getenv(
    "AI_MODEL_PATH",
    "/var/www/Cancerbriefs_backend/ai_model",
)
CANCER_ENV_FILE = os.getenv(
    "CANCER_ENV_FILE",
    "/var/www/Cancerbriefs_backend/.env",
)
CYBER_ENV_FILE = os.getenv(
    "CYBER_ENV_FILE",
    "/var/www/Cyberbrief_new_17_Sep_Backend-/.env",
)

FLEXEE_RESULT_TTL = int(os.getenv("FLEXEE_RESULT_TTL", "3600"))
FLEXEE_JOB_TIMEOUT = int(os.getenv("FLEXEE_JOB_TIMEOUT", "900"))

PROJECTS = {
    "cancer": {
        "env_file": CANCER_ENV_FILE,
        "fallback_text": "A cancer news report focusing on",
        "system_prompt": (
            "You are a strict, zero-hallucination cancer news editor. "
            "Summarize the provided text accurately and objectively in plain English "
            "(80-120 words). Use ONLY facts explicitly stated in the source text. "
            "Do not extrapolate. Never add historical comparisons, corporate boilerplate, "
            "or unverified impacts. If details are sparse, keep the summary brief and factual. "
            "Do not repeat the title."
        ),
    },
    "cyber": {
        "env_file": CYBER_ENV_FILE,
        "fallback_text": "A cybersecurity report and technical advisory focusing on",
        "system_prompt": (
            "You are a strict, zero-hallucination cybersecurity news editor. "
            "Summarize the provided text accurately and objectively in plain English "
            "(80-120 words). Use ONLY facts explicitly stated in the source text. "
            "Do not extrapolate. Never add historical comparisons, corporate boilerplate, "
            "or unverified impacts. If details are sparse, keep the summary brief and factual. "
            "Do not repeat the title."
        ),
    },
}

PROJECT_PRIORITY = {
    "flexee": 0,
    "cancer": 1,
    "cyber": 1,
}


def env_value(values, key, prefix):
    return os.getenv(f"{prefix}_{key}") or values.get(key)


def db_config(project):
    prefix = project.upper()
    values = dotenv_values(PROJECTS[project]["env_file"])

    return {
        "host": env_value(values, "DB_HOST", prefix) or "localhost",
        "port": int(env_value(values, "DB_PORT", prefix) or 5432),
        "dbname": env_value(values, "DB_NAME", prefix),
        "user": env_value(values, "DB_USER", prefix),
        "password": env_value(values, "DB_PASSWORD", prefix),
    }


def connect_db(project):
    config = db_config(project)

    missing = [
        key for key in ("dbname", "user", "password")
        if not config.get(key)
    ]

    if missing:
        raise RuntimeError(
            f"Missing database settings for {project}: {', '.join(missing)}"
        )

    return psycopg.connect(**config, autocommit=True)


def queue_key(project):
    return f"ai_queue:{project}"


def dedup_key(project, article_id):
    return f"ai_queued:{project}:{article_id}"


def result_key(job_id):
    return f"ai_result:{job_id}"


def load_pending_jobs(client, project):
    with connect_db(project) as conn:
        rows = conn.execute(
            """
            SELECT id, title, summary, category
            FROM news_api_article
            WHERE ai_status = 'pending' AND ai_headline = ''
            ORDER BY id
            LIMIT 500
            """
        ).fetchall()

    for article_id, title, summary, category in rows:
        key = dedup_key(project, article_id)

        if client.set(key, "1", nx=True, ex=604800):
            client.rpush(
                queue_key(project),
                json.dumps(
                    {
                        "project": project,
                        "article_id": article_id,
                        "title": title,
                        "summary": summary,
                        "category": category,
                        "attempts": 0,
                    }
                ),
            )

    if rows:
        print(
            f"[QUEUE] {project}: checked {len(rows)} pending articles",
            flush=True,
        )


def requeue_stale_jobs(client, project):
    with connect_db(project) as conn:
        rows = conn.execute(
            """
            SELECT id, title, summary, category
            FROM news_api_article
            WHERE ai_status = 'processing'
              AND ai_locked_at < NOW() - INTERVAL '30 minutes'
            ORDER BY id
            LIMIT 500
            """
        ).fetchall()

        for article_id, title, summary, category in rows:
            conn.execute(
                """
                UPDATE news_api_article
                SET ai_status = 'pending', ai_locked_at = NULL
                WHERE id = %s
                """,
                (article_id,),
            )

            client.delete(dedup_key(project, article_id))
            client.rpush(
                queue_key(project),
                json.dumps(
                    {
                        "project": project,
                        "article_id": article_id,
                        "title": title,
                        "summary": summary,
                        "category": category,
                        "attempts": 1,
                    }
                ),
            )

    if rows:
        print(
            f"[QUEUE] {project}: requeued {len(rows)} stale jobs",
            flush=True,
        )


def mark_processing(project, article_id):
    with connect_db(project) as conn:
        row = conn.execute(
            """
            UPDATE news_api_article
            SET ai_status = 'processing', ai_locked_at = NOW()
            WHERE id = %s AND ai_status = 'pending' AND ai_headline = ''
            RETURNING id
            """,
            (article_id,),
        ).fetchone()

    return row is not None


def mark_completed(project, article_id, title, summary):
    with connect_db(project) as conn:
        row = conn.execute(
            """
            UPDATE news_api_article
            SET ai_headline = %s,
                summary = %s,
                ai_status = 'completed',
                ai_locked_at = NULL,
                ai_completed_at = NOW()
            WHERE id = %s AND ai_status = 'processing'
            RETURNING id
            """,
            (title[:500], summary[:2000], article_id),
        ).fetchone()

    return row is not None


def mark_retry(project, article_id):
    with connect_db(project) as conn:
        conn.execute(
            """
            UPDATE news_api_article
            SET ai_status = 'pending', ai_locked_at = NULL
            WHERE id = %s
            """,
            (article_id,),
        )


def mark_failed(project, article_id):
    with connect_db(project) as conn:
        conn.execute(
            """
            UPDATE news_api_article
            SET ai_status = 'failed', ai_locked_at = NULL
            WHERE id = %s
            """,
            (article_id,),
        )


def clean_summary(text, title, project):
    text = (text or "").strip()

    if text.lower().startswith(title.lower()):
        text = text[len(title):].strip()

    if not text or len(text.split()) < 15:
        text = (
            f"Comprehensive {project} coverage regarding {title}. "
            "Read the complete analysis via the original source link provided below."
        )

    if not text.endswith((".", "!", "?")):
        text += "."

    return text[:2000]


def generate_summary(tokenizer, model, job):
    project = job["project"]
    title = (job.get("title") or "").strip()
    source_summary = (job.get("summary") or "").strip()

    if len(source_summary.split()) < 10:
        source_summary = (
            f"{PROJECTS[project]['fallback_text']}: {title}."
        )

    messages = [
        {
            "role": "system",
            "content": PROJECTS[project]["system_prompt"],
        },
        {
            "role": "user",
            "content": f"Title: {title}\n\nContent: {source_summary}",
        },
    ]

    text_input = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(
        [text_input],
        return_tensors="pt",
        truncation=True,
        max_length=1536,
    )

    model_device = next(model.parameters()).device

    inputs = {
        key: value.to(model_device)
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=120,
            min_new_tokens=30,
            temperature=0.3,
            do_sample=True,
            top_p=0.9,
            repetition_penalty=1.15,
            use_cache=True,
        )

    generated_tokens = outputs[0][
        inputs["input_ids"].shape[-1]:
    ]

    raw_summary = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True,
    )

    del outputs
    del generated_tokens
    del inputs

    return clean_summary(raw_summary, title, project)


def generate_flexee(tokenizer, model, job):
    prompt = str(job.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Flexee AI job has an empty prompt")

    max_tokens = max(1, min(int(job.get("max_tokens") or 1100), 2000))
    num_ctx = max(512, min(int(job.get("num_ctx") or 4096), 8192))

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert scholarly manuscript analyst. "
                "Always return valid JSON exactly matching the schema requested "
                "in the user prompt. Do not add markdown fences or prose around the JSON."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    text_input = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(
        [text_input],
        return_tensors="pt",
        truncation=True,
        max_length=num_ctx - max_tokens,
    )

    model_device = next(model.parameters()).device
    inputs = {
        key: value.to(model_device)
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            min_new_tokens=1,
            temperature=float(job.get("temperature") or 0.2),
            do_sample=True,
            top_p=0.9,
            repetition_penalty=1.15,
            use_cache=True,
        )

    generated_tokens = outputs[0][
        inputs["input_ids"].shape[-1]:
    ]

    content = tokenizer.decode(
        generated_tokens,
        skip_special_tokens=True,
    ).strip()

    del outputs
    del generated_tokens
    del inputs

    if not content:
        raise RuntimeError("Qwen returned an empty Flexee response")

    return {
        "model": "qwen2.5-shared",
        "content": content,
        "input_tokens": int(inputs["input_ids"].shape[-1]) if False else 0,
        "output_tokens": len(generated_tokens) if False else 0,
    }


def process_article_job(client, tokenizer, model, job):
    project = job["project"]
    article_id = job["article_id"]
    attempts = int(job.get("attempts", 0))

    if not mark_processing(project, article_id):
        client.delete(dedup_key(project, article_id))
        print(
            f"[SKIP] {project} article {article_id} is no longer pending",
            flush=True,
        )
        return

    try:
        summary = generate_summary(tokenizer, model, job)

        if mark_completed(project, article_id, job["title"], summary):
            client.delete(dedup_key(project, article_id))
            print(
                f"[AI] {project.upper()} article {article_id} completed",
                flush=True,
            )
        else:
            raise RuntimeError(
                f"Article {article_id} was not in processing state"
            )

    except Exception as exc:
        print(
            f"[AI ERROR] {project} article {article_id}: {exc}",
            flush=True,
        )

        client.delete(dedup_key(project, article_id))

        if attempts < 2:
            mark_retry(project, article_id)
            job["attempts"] = attempts + 1
            client.rpush(queue_key(project), json.dumps(job))
            print(
                f"[AI RETRY] {project} article {article_id} "
                f"attempt {attempts + 2}/3",
                flush=True,
            )
        else:
            mark_failed(project, article_id)
            print(
                f"[AI FAILED] {project} article {article_id}",
                flush=True,
            )


def process_flexee_job(client, tokenizer, model, job):
    job_id = str(job.get("job_id") or "")
    if not job_id:
        raise ValueError("Flexee job is missing job_id")

    try:
        payload = generate_flexee(tokenizer, model, job)
        client.set(
            result_key(job_id),
            json.dumps({"ok": True, "result": payload}),
            ex=FLEXEE_RESULT_TTL,
        )
        print(
            f"[AI] FLEXEE job {job_id} completed",
            flush=True,
        )
    except Exception as exc:
        client.set(
            result_key(job_id),
            json.dumps({"ok": False, "error": str(exc)}),
            ex=FLEXEE_RESULT_TTL,
        )
        print(
            f"[AI ERROR] FLEXEE job {job_id}: {exc}",
            flush=True,
        )


def select_next_job(client):
    flexee_job = client.lpop(queue_key("flexee"))
    if flexee_job is not None:
        return "flexee", flexee_job

    for project in ("cancer", "cyber"):
        raw = client.lpop(queue_key(project))
        if raw is not None:
            return project, raw

    return None, None


def main():
    client = redis.from_url(
        REDIS_URL,
        decode_responses=True,
    )

    client.ping()
    print("[AI WORKER] Redis connected", flush=True)

    for project in ("cancer", "cyber"):
        requeue_stale_jobs(client, project)
        load_pending_jobs(client, project)

    print(
        f"[AI WORKER] Loading Qwen2.5 from {MODEL_PATH}",
        flush=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

    if torch.cuda.is_available():
        print("[AI WORKER] CUDA detected; loading Qwen2.5 on GPU", flush=True)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            dtype=torch.float16,
            device_map="auto",
        )
    else:
        print(
            "[AI WORKER] No CUDA detected; loading Qwen2.5 on CPU with BF16",
            flush=True,
        )
        torch.set_num_threads(2)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            dtype=torch.bfloat16,
            device_map=None,
            low_cpu_mem_usage=True,
        )
        model = model.to("cpu")

    model.eval()
    model.generation_config.use_cache = True

    print(
        "[AI WORKER] Qwen2.5 loaded. Flexee priority / Cancer-Cyber normal queue started.",
        flush=True,
    )

    while True:
        selected_project, raw = select_next_job(client)

        if raw is None:
            time.sleep(2)
            for project in ("cancer", "cyber"):
                load_pending_jobs(client, project)
            continue

        try:
            job = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"[AI WORKER] Invalid queue payload: {exc}", flush=True)
            continue

        print(
            f"[AI WORKER] Selected {selected_project.upper()} job",
            flush=True,
        )

        if selected_project == "flexee":
            process_flexee_job(client, tokenizer, model, job)
        else:
            process_article_job(client, tokenizer, model, job)


if __name__ == "__main__":
    main()
