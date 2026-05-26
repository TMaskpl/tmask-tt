import requests
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from url_validator import block_private_url


def _render_notification(job):
    status = job.status
    context = {'job': job}
    subject = f'[TMask] Transfer #{job.pk} — {"DONE" if status == "done" else "FAILED"}'
    plain = render_to_string(f'notifications/transfer_{status}.txt', context)
    html  = render_to_string(f'notifications/transfer_{status}.html', context)
    return subject, plain, html


def send_email_notification(job) -> bool:
    user = job.owner
    if not user.email:
        return False
    if job.status == 'done' and not user.notify_on_done:
        return False
    if job.status == 'failed' and not user.notify_on_failed:
        return False
    subject, plain, html = _render_notification(job)
    send_mail(
        subject,
        plain,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html,
        fail_silently=False,
    )
    return True


def _build_webhook_payload(job) -> dict:
    if job.connection:
        connection_label = f'{job.connection.name} ({job.connection.protocol.upper()})'
    elif job.flow:
        connection_label = f'RELAY: {job.flow.name}'
    else:
        connection_label = '—'

    def fmt_dt(dt):
        return dt.strftime('%Y-%m-%d %H:%M') if dt else None

    return {
        'job_id': job.pk,
        'status': job.status,
        'source_path': job.source_path,
        'destination_path': job.destination_path,
        'connection': connection_label,
        'started_at': fmt_dt(job.started_at),
        'finished_at': fmt_dt(job.finished_at),
        'error': job.error_message or None,
    }


def send_webhook_notification(job) -> bool:
    user = job.owner
    if not user.webhook_url:
        return False
    if job.status == 'done' and not user.webhook_on_done:
        return False
    if job.status == 'failed' and not user.webhook_on_failed:
        return False
    try:
        block_private_url(user.webhook_url)
    except ValueError:
        return False
    payload = _build_webhook_payload(job)
    resp = requests.post(user.webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True
