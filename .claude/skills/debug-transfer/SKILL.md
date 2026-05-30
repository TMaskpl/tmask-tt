---
name: debug-transfer
description: Diagnostyka nieudanych lub zawieszonych transferów w tmask-tt — logi, Celery, SSH, reset orphanów.
allowed-tools: [Bash]
---

Użyj gdy transfer ma status FAILED, utknął w RUNNING lub w ogóle się nie uruchomił.

## Krok 1 — Odczyt stanu joba z bazy

```bash
docker compose run --rm web python manage.py shell -c "
from apps.transfers.models import TransferJob, TransferLog
job = TransferJob.objects.get(pk=<JOB_ID>)
print(f'Status: {job.status}')
print(f'Error: {job.error_message}')
print(f'Celery task: {job.celery_task_id}')
print(f'Started: {job.started_at}  Finished: {job.finished_at}')
print('--- LOGS ---')
for log in job.logs.all():
    print(f'[{log.level.upper()}] {log.message}')
"
```

## Krok 2 — Identyfikacja błędu

| Komunikat w logu | Przyczyna | Co sprawdzić |
|-----------------|-----------|--------------|
| `AUTH FAILED` | Złe hasło lub klucz SSH | Pola `password`/`ssh_key` w Connection, typ klucza |
| `CONNECTION TIMEOUT` | Host nieosiągalny | Firewall, VPN, port 22, zasób sieciowy workera |
| `SOURCE NOT FOUND` | Zły `source_path` | Ścieżka pliku na zdalnym hoście |
| `INSUFFICIENT SPACE` | Brak miejsca na celu | Dysk na hoście docelowym |
| `SSH ERROR` | Problem z negocjacją SSH | Wersja OpenSSH, algorytmy szyfrowania |
| `UNEXPECTED ERROR` | Nieobsłużony wyjątek | Sprawdź logi workera (krok 3) |
| `TASK INTERRUPTED` | Worker zrestartował podczas transferu | Orphan — resetuj ręcznie (krok 5) |

## Krok 3 — Logi Celery workera

```bash
docker compose logs --tail=100 worker
docker compose logs --tail=50 beat
```

Szukaj linii z `ERROR` lub `UNEXPECTED` wokół czasu startu joba.

## Krok 4 — Ręczny test SSH z kontenera workera

```bash
# Test SFTP (paramiko)
docker compose exec worker python -c "
import paramiko, io
client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('<HOST>', port=22, username='<USER>', password='<PASS>', timeout=10)
sftp = client.open_sftp()
print(sftp.listdir('<PATH>'))
client.close()
"

# Test rsync — sprawdź czy rsync jest dostępny
docker compose exec worker rsync --version
docker compose exec worker ssh -o StrictHostKeyChecking=no -p 22 <USER>@<HOST> ls <PATH>
```

## Krok 5 — Reset osieroconych jobów (stuck RUNNING > 1h)

```bash
# Manualny reset — normalnie robi to cleanup_orphan_jobs co 5 min przez Beat
docker compose run --rm web python manage.py shell -c "
from django.utils import timezone
from datetime import timedelta
from apps.transfers.models import TransferJob
cutoff = timezone.now() - timedelta(hours=1)
qs = TransferJob.objects.filter(status='running', started_at__lt=cutoff)
print(f'Orphans: {qs.count()}')
qs.update(status='failed', error_message='MANUALLY RESET')
"

# Sprawdź czy Beat działa
docker compose logs --tail=20 beat
docker compose ps beat
```

## Krok 6 — Relay Flow (jeśli job.flow_id ustawione)

```bash
docker compose run --rm web python manage.py shell -c "
from apps.transfers.models import TransferJob
job = TransferJob.objects.get(pk=<JOB_ID>)
if job.flow:
    f = job.flow
    print(f'Flow: {f.name}')
    print(f'Source: {f.source_conn.host}:{f.source_path}')
    print(f'Dest:   {f.dest_conn.host}:{f.dest_path}')
"
```

Dla relay sprawdź oba połączenia (source_conn i dest_conn) osobno krokiem 4.
