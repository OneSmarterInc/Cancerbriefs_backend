import os
import hashlib
import re
import html
import datetime
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from email.utils import format_datetime, parsedate_to_datetime

import requests
import feedparser
from django.db import close_old_connections
from django.utils import timezone
from django.conf import settings

from .models import Article, RSSFeed


# --- STRICT CYBERSECURITY KEYWORD FILTER ---
CYBER_KEYWORDS = [
    "cancer",
    "cancers",
    "oncology",
    "oncologist",
    "oncological",
    "tumor",
    "tumour",
    "tumors",
    "tumours",
    "malignancy",
    "malignant",
    "neoplasm",
    "neoplasia",
    "carcinoma",
    "sarcoma",
    "adenocarcinoma",
    "breast cancer",
    "lung cancer",
    "lung carcinoma",
    "prostate cancer",
    "prostate carcinoma",
    "colorectal cancer",
    "colon cancer",
    "rectal cancer",
    "pancreatic cancer",
    "liver cancer",
    "hepatic cancer",
    "stomach cancer",
    "gastric cancer",
    "ovarian cancer",
    "cervical cancer",
    "uterine cancer",
    "endometrial cancer",
    "kidney cancer",
    "renal cancer",
    "bladder cancer",
    "thyroid cancer",
    "brain cancer",
    "brain tumor",
    "brain tumour",
    "skin cancer",
    "melanoma",
    "oral cancer",
    "mouth cancer",
    "head and neck cancer",
    "esophageal cancer",
    "oesophageal cancer",
    "testicular cancer",
    "bone cancer",
    "bile duct cancer",
    "cholangiocarcinoma",
    "gallbladder cancer",
    "leukemia",
    "leukaemia",
    "lymphoma",
    "hodgkin lymphoma",
    "non-hodgkin lymphoma",
    "multiple myeloma",
    "myeloma",
    "myelodysplastic syndrome",
    "myeloproliferative neoplasm",
    "acute lymphoblastic leukemia",
    "acute myeloid leukemia",
    "chronic lymphocytic leukemia",
    "chronic myeloid leukemia",
    "metastasis",
    "metastatic cancer",
    "metastatic disease",
    "cancer metastasis",
    "cancer spread",
    "tumor metastasis",
    "tumour metastasis",
    "invasive cancer",
    "advanced cancer",
    "late-stage cancer",
    "stage 4 cancer",
    "cancer recurrence",
    "cancer relapse",
    "recurrent cancer",
    "cancer diagnosis",
    "cancer screening",
    "cancer detection",
    "early cancer detection",
    "early detection",
    "cancer prevention",
    "cancer risk",
    "cancer risks",
    "cancer symptoms",
    "cancer diagnostic",
    "oncology diagnosis",
    "biopsy",
    "liquid biopsy",
    "cancer biomarker",
    "biomarkers",
    "tumor marker",
    "tumour marker",
    "genetic testing",
    "cancer genetics",
    "genomic testing",
    "tumor profiling",
    "tumour profiling",
    "molecular profiling",
    "precision oncology",
    "precision medicine",
    "chemotherapy",
    "radiotherapy",
    "radiation therapy",
    "radiation oncology",
    "immunotherapy",
    "targeted therapy",
    "targeted cancer therapy",
    "hormone therapy",
    "hormonal therapy",
    "endocrine therapy",
    "cancer treatment",
    "cancer treatments",
    "cancer therapy",
    "cancer therapies",
    "oncology treatment",
    "oncology therapy",
    "cancer surgery",
    "oncology surgery",
    "tumor surgery",
    "tumour surgery",
    "stem cell transplant",
    "bone marrow transplant",
    "CAR-T",
    "CAR T-cell therapy",
    "cell therapy",
    "gene therapy",
    "cancer vaccine",
    "cancer vaccines",
    "clinical trial",
    "clinical trials",
    "cancer clinical trial",
    "oncology clinical trial",
    "phase 1 trial",
    "phase 2 trial",
    "phase 3 trial",
    "trial results",
    "clinical study",
    "cancer research",
    "oncology research",
    "cancer study",
    "oncology study",
    "cancer researchers",
    "cancer researcher",
    "oncology researchers",
    "FDA cancer",
    "FDA oncology",
    "FDA approval",
    "cancer drug approval",
    "oncology drug approval",
    "EMA cancer",
    "EMA oncology",
    "drug approval",
    "new cancer drug",
    "cancer drug",
    "oncology drug",
    "cancer medicine",
    "oncology medicine",
    "cancer drug discovery",
    "oncology drug discovery",
    "cancer pharmaceutical",
    "oncology pharmaceutical",
    "pharmaceutical oncology",
    "cancer biotech",
    "oncology biotech",
    "biotech cancer",
    "cancer immunology",
    "tumor immunology",
    "tumour immunology",
    "immune checkpoint",
    "checkpoint inhibitor",
    "PD-1",
    "PD-L1",
    "CTLA-4",
    "T-cell",
    "T cell therapy",
    "immune therapy",
    "BRCA",
    "BRCA1",
    "BRCA2",
    "EGFR",
    "ALK",
    "KRAS",
    "BRAF",
    "HER2",
    "HER-2",
    "PIK3CA",
    "TP53",
    "APC",
    "MSI",
    "MSI-H",
    "MMR",
    "NTRK",
    "RET fusion",
    "ROS1",
    "IDH",
    "FGFR",
    "oncogenes",
    "oncogene",
    "tumor suppressor",
    "tumour suppressor",
    "cancer mutation",
    "cancer mutations",
    "genetic mutation",
    "driver mutation",
    "genomic alteration",
    "HPV cancer",
    "HPV vaccine",
    "cervical cancer screening",
    "mammogram",
    "mammography",
    "colonoscopy",
    "lung cancer screening",
    "PSA screening",
    "prostate screening",
    "tobacco cancer",
    "smoking cancer",
    "smoking-related cancer",
    "alcohol cancer risk",
    "obesity cancer risk",
    "environmental cancer",
    "occupational cancer",
    "carcinogen",
    "carcinogenic",
    "cancer mortality",
    "cancer deaths",
    "cancer survival",
    "cancer survivor",
    "cancer survivors",
    "survival rate",
    "five-year survival",
    "cancer incidence",
    "cancer prevalence",
    "cancer burden",
    "palliative care",
    "hospice cancer",
    "supportive oncology",
    "cancer pain",
    "cancer care",
    "oncology care",
    "NCI",
    "National Cancer Institute",
    "American Cancer Society",
    "ASCO",
    "American Society of Clinical Oncology",
    "ESMO",
    "European Society for Medical Oncology",
    "Cancer Research UK",
    "WHO cancer",
    "World Health Organization cancer"
]

def is_cybersecurity_related(title, summary):
    text = f"{title} {summary}".lower()
    return any(keyword in text for keyword in CYBER_KEYWORDS)

def clean_text(value):
    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r'&#[a-zA-Z0-9;]+', "'", text) 
    text = text.replace("&#xd", "").replace("&#xD", "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())

def strip_ai_artifacts(text):
    if not text:
        return ""
    
    text = re.sub(r'^(here is|summary:|assistant:|sure).*?:', '', text, flags=re.IGNORECASE)
    text = re.sub(r"(?:i'm|i am|i have|i've)\s+(?:excited to share|planned|announced|noted).*?(?:\.|:)", "", text, flags=re.IGNORECASE)
    text = re.sub(r'```[a-zA-Z]*', '', text) 
    text = text.replace('`', '') 
    text = re.sub(r'[\u4e00-\u9fff\u3000-\u30ff]', '', text)
    text = re.sub(r'\([^)]*\)', '', text)                    
    text = re.sub(r'\[.*?\]', '', text)                      
    text = re.sub(r'[\(\)\[\]\{\}\|\<\>\~_#\*\\/]', ' ', text)
    text = re.sub(r'\s*[,;:\-\.]\s*[,;:\-\.]+', '.', text)    
    text = re.sub(r'\s{2,}', ' ', text)                      
    return text.strip()

def detect_category(title, summary, default_category=None):
    return "Cybersecurity"

def make_guid(source, link, title):
    return hashlib.sha256(f"{source}|{link}|{title}".encode("utf-8")).hexdigest()

def reset_article_database():
    deleted_count, _ = Article.objects.all().delete()
    print(f"Database Reset: Removed {deleted_count} old articles.")
    return deleted_count

def get_active_feeds():
    feeds = RSSFeed.objects.filter(is_active=True)
    return [{"name": f.name, "url": f.url, "category": f.category} for f in feeds]

def parse_entry_datetime(item):
    """
    Parses entry date into a timezone-aware UTC datetime.
    Checks published_parsed, updated_parsed, string representations, or returns None.
    """
    time_tuple = item.get("published_parsed") or item.get("updated_parsed")
    if time_tuple:
        try:
            dt = datetime.datetime(*time_tuple[:6], tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            pass

    raw_date = item.get("published") or item.get("updated") or ""
    if raw_date:
        try:
            dt = parsedate_to_datetime(raw_date)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            pass

        try:
            dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except Exception:
            pass

    return None

def fetch_feed_data(feed_info):
    items = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        response = requests.get(feed_info["url"], timeout=15, headers=headers)
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        for item in feed.entries[:25]:
            items.append({"feed_info": feed_info, "item": item})

        print(f"RSS OK [{feed_info['name']}]: {len(items)} articles", flush=True)
    except requests.exceptions.Timeout:
        print(f"RSS TIMEOUT [{feed_info['name']}]: request exceeded 15 seconds", flush=True)
    except requests.exceptions.RequestException as e:
        print(f"RSS ERROR [{feed_info['name']}]: {e}", flush=True)
    except Exception as e:
        print(f"RSS ERROR [{feed_info['name']}]: {e}", flush=True)
    return items

def fetch_and_store_news():
    close_old_connections()
    
    thirty_days_ago = timezone.now() - timedelta(days=30)
    expired_count, _ = Article.objects.filter(created_at__lt=thirty_days_ago).delete()
    if expired_count > 0:
        print(f"Database Cleanup: Purged {expired_count} stories older than 30 days.")

    current_rss_feeds = get_active_feeds()
    raw_items = []

    executor = ThreadPoolExecutor(max_workers=25)
    futures = [executor.submit(fetch_feed_data, feed) for feed in current_rss_feeds]

    try:
        for future in as_completed(futures, timeout=90):
            try:
                raw_items.extend(future.result())
            except Exception as e:
                print(f"RSS worker error: {e}", flush=True)
        executor.shutdown(wait=True)
    except FuturesTimeoutError:
        unfinished = sum(1 for future in futures if not future.done())
        print(
            f"RSS scan timeout: {unfinished} feed requests did not finish within 90 seconds. Continuing with completed feeds.",
            flush=True
        )
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    new_found = 0
    filtered_out_keywords = 0
    filtered_out_time = 0

    now = timezone.now()
    cutoff_time = now - timedelta(hours=2)
    future_cutoff = now
    candidates = []

    for data in raw_items:
        feed_info = data["feed_info"]
        item = data["item"]
        title = clean_text(item.get("title"))
        raw_summary = clean_text(item.get("summary") or item.get("description") or "")
        link = item.get("link", "")

        if not title:
            continue

        published_dt = parse_entry_datetime(item)

        if published_dt and (published_dt < cutoff_time or published_dt > future_cutoff):
            filtered_out_time += 1
            continue

        if not is_cybersecurity_related(title, raw_summary):
            filtered_out_keywords += 1
            continue

        category = detect_category(title, raw_summary, default_category=feed_info.get("category"))
        guid = make_guid(feed_info["name"], link, title)

        published_date_str = clean_text(item.get("published") or item.get("updated") or "")
        if not published_date_str:
            published_date_str = format_datetime(timezone.now())

        # --- KEYWORD CLASSIFICATION FOR PROFESSOR ASSIGNMENT ---
        from .models import determine_professor_by_content
        combined_text = f"{title} {raw_summary} {category}"
        assigned_prof_id = determine_professor_by_content(combined_text)

        candidates.append({
            "guid": guid,
            "source": feed_info["name"],
            "category": category,
            "title": title,
            "summary": raw_summary,
            "link": link,
            "published": published_date_str,
            "professor_id": assigned_prof_id,
        })

    print(f"RSS processing complete: {len(raw_items)} fetched, {len(candidates)} cybersecurity candidates.", flush=True)

    if candidates:
        Article.objects.bulk_create(
            [
                Article(
                    guid=item["guid"],
                    source=item["source"],
                    category=item["category"],
                    title=item["title"],
                    ai_headline="",
                    summary=item["summary"],
                    link=item["link"],
                    published=item["published"],
                    professor_id=item["professor_id"],  # <--- Assigned based on keywords
                )
                for item in candidates
            ],
            batch_size=200,
            ignore_conflicts=True,
        )
        new_found = len(candidates)

        for item in candidates:
            print(
                f"--> PROCESSED CYBER STORY [{item['source']} | Desk ID: {item['professor_id']}]: {item['title'][:40]}...",
                flush=True
            )

    print(
        f"Live Scan Complete: Checked {len(raw_items)} articles. "
        f"Filtered (Outside 2h window or future-dated): {filtered_out_time}. "
        f"Filtered (Non-cyber): {filtered_out_keywords}. "
        f"Saved/processed: {new_found} candidates.",
        flush=True,
    )

    print("Checking for unsummarized articles...", flush=True)
    pending_articles = list(
        Article.objects.filter(ai_headline="").order_by("id")[:10]
    )
    print(
        f"Found {len(pending_articles)} unsummarized articles.",
        flush=True,
    )

    if pending_articles:
        print(
            f"AI Model Processing up to 10 unsummarized cybersecurity articles with Qwen2.5...",
            flush=True,
        )
        
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            MODEL_PATH = os.path.join(settings.BASE_DIR, "ai_model")
            tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
            model = AutoModelForCausalLM.from_pretrained(MODEL_PATH)
        except Exception as e:
            print(f"Failed to load AI model from {MODEL_PATH}. Error: {e}")
            return

        for art in pending_articles:
            cleaned_title = clean_text(art.title)
            cleaned_raw_summary = clean_text(art.summary)
            
            if len(cleaned_raw_summary.split()) < 10:
                content_to_use = f"A cybersecurity report and technical advisory focusing on: {cleaned_title}."
            else:
                content_to_use = cleaned_raw_summary

            messages = [
                {
                    "role": "system", 
                    "content": (
                        "You are a strict, zero-hallucination cybersecurity news editor. "
                        "Summarize the provided text accurately and objectively in plain English (80-120 words). "
                        "CRITICAL RULES:\n"
                        "1. Use ONLY facts explicitly stated in the source text. Do not extrapolate.\n"
                        "2. NEVER add historical comparisons, corporate boilerplate (e.g., 'commitment to security'), or unverified impacts.\n"
                        "3. If details are sparse, keep the summary brief and factual based solely on the title and provided snippet.\n"
                        "4. Do not repeat the title."
                    )
                },
                {"role": "user", "content": f"Title: {cleaned_title}\n\nContent: {content_to_use}"}
            ]
            
            try:
                text_input = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True
                )
                
                inputs = tokenizer([text_input], return_tensors="pt").to(model.device)
                
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=220,    
                    min_new_tokens=100,    
                    temperature=0.3,
                    do_sample=True,
                    top_p=0.9,
                    repetition_penalty=1.15 
                )
                
                generated_tokens = outputs[0][inputs["input_ids"].shape[-1]:]
                raw_summary = tokenizer.decode(generated_tokens, skip_special_tokens=True)
                final_summary = strip_ai_artifacts(raw_summary)
                
            except Exception as exc:
                print(f"AI Error on '{art.title[:20]}': {exc}")
                continue

            if final_summary:
                if final_summary.lower().startswith(cleaned_title.lower()):
                    final_summary = final_summary[len(cleaned_title):].strip()
                
                final_summary = re.sub(r'^[^a-zA-Z0-9]+', '', final_summary).strip()
                
                if len(final_summary) > 0:
                    final_summary = final_summary[0].upper() + final_summary[1:]
                
                if not final_summary.endswith((".", "!", "?")):
                    last_punctuation = max(final_summary.rfind("."), final_summary.rfind("!"), final_summary.rfind("?"))
                    if last_punctuation > len(final_summary) * 0.5:
                        final_summary = final_summary[:last_punctuation+1]
                    else:
                        final_summary += "."

            if len(final_summary.split()) < 15:
                final_summary = f"Comprehensive cybersecurity coverage regarding {cleaned_title}. Read the complete analysis via the original source link provided below."

            art.ai_headline = art.title[:500]
            art.summary = final_summary[:2000]

            # --- RE-EVALUATE PROFESSOR ID WITH AI SUMMARY ---
            from .models import determine_professor_by_content
            combined_text = f"{art.title} {art.ai_headline} {art.summary} {art.category}"
            art.professor_id = determine_professor_by_content(combined_text)

            art.save(update_fields=["ai_headline", "summary", "professor_id"])
            print(f"--> AI Summary & Desk Assignment Ready [Desk ID: {art.professor_id}]: {art.title[:30]}...")

    close_old_connections()

def get_stored_news():
    return Article.objects.all().order_by("-id")

