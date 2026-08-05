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


def send_telegram_notification(job) -> bool:
    user = job.owner
    if not user.telegram_chat_id:
        return False
    if job.status == 'done' and not user.telegram_on_done:
        return False
    if job.status == 'failed' and not user.telegram_on_failed:
        return False
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        return False

    icon = '✅' if job.status == 'done' else '❌'
    lines = [
        f'{icon} <b>Transfer #{job.pk} — {job.status.upper()}</b>',
        f'Plik: <code>{job.source_path}</code>',
        f'Cel: <code>{job.destination_path}</code>',
    ]
    if job.error_message:
        lines.append(f'Błąd: {job.error_message}')

    resp = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': user.telegram_chat_id, 'text': '\n'.join(lines), 'parse_mode': 'HTML'},
        timeout=10,
    )
    resp.raise_for_status()
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


def _build_slack_payload(job) -> dict:
    icon = ':white_check_mark:' if job.status == 'done' else ':x:'
    text = (
        f'{icon} *Transfer #{job.pk} — {job.status.upper()}*\n'
        f'Plik: `{job.source_path}`\n'
        f'Cel: `{job.destination_path}`'
    )
    if job.error_message:
        text += f'\nBłąd: {job.error_message}'
    return {'text': text}


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

    if 'hooks.slack.com' in user.webhook_url:
        payload = _build_slack_payload(job)
    else:
        payload = _build_webhook_payload(job)

    resp = requests.post(user.webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True


def _render_connection_health_notification(connection, status: str):
    template_name = 'connection_health_recovered' if status == 'ok' else 'connection_health_failed'
    label = 'RECOVERED' if status == 'ok' else 'FAILED'
    context = {'connection': connection, 'error': connection.health_error}
    subject = f'[TMask] Connection {connection.name} — HEALTH {label}'
    plain = render_to_string(f'notifications/{template_name}.txt', context)
    html  = render_to_string(f'notifications/{template_name}.html', context)
    return subject, plain, html


def send_connection_health_email(connection, status: str) -> bool:
    user = connection.owner
    if not user.email or not user.notify_on_failed:
        return False
    subject, plain, html = _render_connection_health_notification(connection, status)
    send_mail(
        subject,
        plain,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html,
        fail_silently=False,
    )
    return True


def send_connection_health_telegram(connection, status: str) -> bool:
    user = connection.owner
    if not user.telegram_chat_id or not user.telegram_on_failed:
        return False
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        return False

    icon = '✅' if status == 'ok' else '🔴'
    label = 'RECOVERED' if status == 'ok' else 'FAILED'
    lines = [
        f'{icon} <b>Connection {connection.name} — HEALTH {label}</b>',
        f'Host: <code>{connection.host}:{connection.port}</code>',
    ]
    if status == 'failed' and connection.health_error:
        lines.append(f'Błąd: {connection.health_error}')

    resp = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': user.telegram_chat_id, 'text': '\n'.join(lines), 'parse_mode': 'HTML'},
        timeout=10,
    )
    resp.raise_for_status()
    return True


def _build_connection_health_payload(connection, status: str) -> dict:
    return {
        'connection_id': connection.pk,
        'connection_name': connection.name,
        'status': status,
        'host': connection.host,
        'port': connection.port,
        'error': connection.health_error or None,
    }


def _build_connection_health_slack_payload(connection, status: str) -> dict:
    icon = ':white_check_mark:' if status == 'ok' else ':x:'
    label = 'RECOVERED' if status == 'ok' else 'FAILED'
    text = (
        f'{icon} *Connection {connection.name} — HEALTH {label}*\n'
        f'Host: `{connection.host}:{connection.port}`'
    )
    if status == 'failed' and connection.health_error:
        text += f'\nBłąd: {connection.health_error}'
    return {'text': text}


def send_connection_health_webhook(connection, status: str) -> bool:
    user = connection.owner
    if not user.webhook_url or not user.webhook_on_failed:
        return False
    try:
        block_private_url(user.webhook_url)
    except ValueError:
        return False

    if 'hooks.slack.com' in user.webhook_url:
        payload = _build_connection_health_slack_payload(connection, status)
    else:
        payload = _build_connection_health_payload(connection, status)

    resp = requests.post(user.webhook_url, json=payload, timeout=10)
    resp.raise_for_status()
    return True
