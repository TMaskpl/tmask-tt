from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings


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
