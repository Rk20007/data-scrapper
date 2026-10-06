from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery("lead_engine", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])

celery_app.conf.update(
    timezone=settings.timezone,
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=False,  # never re-run a task that may have half-sent an email
    worker_prefetch_multiplier=1,
    task_time_limit=1800,
    task_soft_time_limit=1700,
    result_expires=86400,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.send_queue_tick": {"queue": "email"},
        "app.workers.tasks.poll_inbox": {"queue": "email"},
        "app.workers.tasks.run_source": {"queue": "crawl"},
        "app.workers.tasks.monitor_company": {"queue": "crawl"},
        "app.workers.tasks.enrich_company": {"queue": "crawl"},
    },
    beat_schedule={
        "dispatch-due-sources": {"task": "app.workers.tasks.dispatch_due_sources", "schedule": 300.0},
        "process-pending-documents": {"task": "app.workers.tasks.process_pending_documents", "schedule": 600.0},
        "monitor-company-websites": {"task": "app.workers.tasks.dispatch_company_monitoring",
                                     "schedule": crontab(hour=5, minute=30)},
        "discover-companies": {"task": "app.workers.tasks.discover", "schedule": crontab(hour="7,19", minute=0)},
        "assess-companies": {"task": "app.workers.tasks.assess_pending_companies", "schedule": crontab(minute=20)},
        "enrich-contacts": {"task": "app.workers.tasks.dispatch_contact_enrichment", "schedule": crontab(minute=40)},
        "plan-outreach": {"task": "app.workers.tasks.plan_outreach", "schedule": 900.0},
        "schedule-followups": {"task": "app.workers.tasks.schedule_followups", "schedule": 1800.0},
        "send-queue": {"task": "app.workers.tasks.send_queue_tick", "schedule": 60.0},
        "poll-inbox": {"task": "app.workers.tasks.poll_inbox", "schedule": 300.0},
        "reap-stuck-sends": {"task": "app.workers.tasks.reap_stuck", "schedule": 900.0},
        "rescore-all": {"task": "app.workers.tasks.rescore", "schedule": crontab(hour=2, minute=15)},
        "daily-digest": {"task": "app.workers.tasks.daily_digest", "schedule": crontab(hour=9, minute=0)},
    },
)
