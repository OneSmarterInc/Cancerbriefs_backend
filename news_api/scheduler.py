from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone
import datetime


def scheduled_ingest():
    from .services import fetch_and_store_news

    now = timezone.localtime()
    print(f"[{now.strftime('%H:%M:%S')}] Checking for new stories...", flush=True)

    try:
        fetch_and_store_news()
    except Exception:
        import traceback
        traceback.print_exc()


def check_and_send_emails():
    from .models import NewsletterSendLog, SMTPConfig
    from .views import process_mass_blast

    config = SMTPConfig.objects.first()
    if not config or not config.daily_send_time:
        return

    now = timezone.localtime()
    current_date = now.date()

    try:
        scheduled_time = datetime.datetime.strptime(
            config.daily_send_time,
            "%H:%M"
        ).time()
    except (TypeError, ValueError):
        print(f"Invalid daily send time: {config.daily_send_time}", flush=True)
        return

    if now.time() < scheduled_time:
        return

    if NewsletterSendLog.objects.filter(send_date=current_date).exists():
        return

    success, message = process_mass_blast()
    print(f"Daily newsletter: {message}", flush=True)

    if success:
        NewsletterSendLog.objects.get_or_create(send_date=current_date)


def start():
    scheduler = BackgroundScheduler(
        timezone=timezone.get_current_timezone()
    )

    scheduler.add_job(
        scheduled_ingest,
        "interval",
        minutes=30,
        next_run_time=timezone.now(),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        id="news_ingestion",
        replace_existing=True,
    )

    scheduler.add_job(
        check_and_send_emails,
        "interval",
        minutes=1,
        next_run_time=timezone.now(),
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
        id="daily_email_check",
        replace_existing=True,
    )

    scheduler.start()

    print("Cyberbrief scheduler started. News ingestion scheduled every 30 minutes.", flush=True)

    return scheduler