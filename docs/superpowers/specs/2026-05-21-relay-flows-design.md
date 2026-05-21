# Design Spec: Relay Flows (Server-to-Server Transfer)

**Date:** 2026-05-21
**Status:** Approved

## Overview

Add a **Flow** abstraction that lets users configure reusable server-to-server (relay) transfers. The worker acts as an intermediary: it downloads from Server A via SFTP and uploads to Server B via SFTP, so no direct network path between the two servers is required. The existing local→remote transfer mode remains unchanged.

---

## Data Models

### New: `Flow` (app `flows`)

```python
class Flow(models.Model):
    owner       = FK(User)
    name        = CharField(100)
    source_conn = FK(Connection, related_name='source_flows')
    source_path = CharField(2000)
    dest_conn   = FK(Connection, related_name='dest_flows')
    dest_path   = CharField(2000)
    created_at  = DateTimeField(auto_now_add=True)
```

Validation: if `source_conn == dest_conn`, then `source_path != dest_path` (prevent copying file to itself).

### Modified: `TransferJob`

`connection` becomes nullable. New optional `flow` FK added:

```python
connection = FK(Connection, null=True, blank=True)   # was NOT NULL
flow       = FK(Flow,       null=True, blank=True)   # NEW
```

Exactly one of `connection` / `flow` must be set — enforced in `clean()` and in forms.

### Modified: `ScheduledTransfer`

Same pattern as `TransferJob`:

```python
connection = FK(Connection, null=True, blank=True)   # was NOT NULL
flow       = FK(Flow,       null=True, blank=True)   # NEW
```

Exactly one of `connection` / `flow` must be set.

**Migration note:** existing `TransferJob` and `ScheduledTransfer` rows keep their `connection` value unchanged. No data migration needed — only schema change (nullable).

---

## Worker: Relay Execution

### New module: `modules/relay/`

```
services/worker/modules/relay/
├── __init__.py
├── config.py    # RELAY_TEMP_DIR, RELAY_STREAM_THRESHOLD (default 100 MB)
└── handler.py   # RelayHandler
```

### `RelayHandler(source_params, dest_params).execute(log_callback)`

Execution steps:
1. Connect to `source_conn` via SFTP (Paramiko)
2. Download file to `BytesIO` (or `tempfile` if size > `RELAY_STREAM_THRESHOLD`)
3. Disconnect from source
4. Connect to `dest_conn` via SFTP
5. Upload from buffer → `dest_path`
6. Delete tempfile if one was created
7. Disconnect from dest

Errors are tagged with `SOURCE ERROR —` or `DEST ERROR —` prefix for readable logs.
Tempfile cleanup happens in a `finally` block — guaranteed even on exception.

### `tasks.py` changes

```python
def _build_relay_params(flow) -> tuple[dict, dict]:
    # returns (source_params, dest_params) from flow.source_conn / flow.dest_conn
    ...

@app.task
def execute_transfer(self, job_id):
    ...
    if job.flow:                              # NEW branch
        source_params, dest_params = _build_relay_params(job.flow)
        RelayHandler(source_params, dest_params).execute(log_callback)
    else:                                     # existing branch — unchanged
        handler_cls = SFTPHandler if job.connection.protocol == 'sftp' else RsyncHandler
        handler_cls(params).execute(log_callback)
```

---

## UI and Views

### New section: `/flows/`

| URL | View | Description |
|-----|------|-------------|
| `/flows/` | `flow_list` | User's flows + "Run" button per flow |
| `/flows/new/` | `flow_create` | Create form |
| `/flows/<pk>/edit/` | `flow_edit` | Edit form |
| `/flows/<pk>/delete/` | `flow_delete` | DELETE (POST) |
| `/flows/<pk>/run/` | `flow_run` | POST: creates `TransferJob(flow=flow)`, calls `.delay()`, redirects to job log |

### Flow form layout

```
[ Name              ]
[ Source Connection ▼]   [ Source Path       ]
[ Dest Connection   ▼]   [ Dest Path         ]
[        SAVE FLOW   ]
```

Both connection dropdowns show only connections owned by the current user.

### Changes to existing views

**Nav menu:** "Flows" link added between "Connections" and "Transfers".

**Transfer Logs (`/logs/`):** "Type" column shows `LOCAL→REMOTE` or `RELAY` (with flow name) for each job.

**Transfer Detail:** when job has a `flow`, header shows:
```
FLOW: <name>
SOURCE: <conn.name> : <source_path>
DEST:   <conn.name> : <dest_path>
```

### Scheduler form changes

Toggle added: **Connection** | **Flow**

- "Connection" selected → existing fields shown (unchanged)
- "Flow" selected → Flow dropdown shown, path fields hidden (Flow already contains paths)

---

## Testing

### Worker

**`tests/test_relay_handler.py`** (new):
- Happy path: download from source + upload to dest
- `SOURCE ERROR` when source unreachable
- `DEST ERROR` when dest unreachable
- Tempfile cleanup on exception

**`tests/test_tasks.py`** (extend):
- `execute_transfer` with `job.flow` set → calls `RelayHandler`
- `execute_transfer` with `job.connection` set → unchanged behaviour (existing tests pass)

### Web (`apps/flows/tests/`)

- `test_models.py`: same source+path validation
- `test_views.py`: full CRUD, `flow_run` creates `TransferJob` with correct FK

### Scheduler

- `connection` and `flow` both set → validation error
- neither `connection` nor `flow` set → validation error

---

## Files Affected

| File | Change |
|------|--------|
| `services/web/apps/flows/` | NEW app (models, views, forms, urls, templates, tests) |
| `services/web/apps/transfers/models.py` | `connection` nullable, add `flow` FK |
| `services/web/apps/transfers/migrations/` | New migration |
| `services/web/apps/scheduler/models.py` | `connection` nullable, add `flow` FK |
| `services/web/apps/scheduler/migrations/` | New migration |
| `services/web/apps/scheduler/forms.py` | Connection/Flow toggle |
| `services/web/apps/scheduler/views.py` | Handle flow-based schedule |
| `services/web/apps/transfers/views.py` | `transfer_logs` shows relay type |
| `services/web/config/urls.py` | Include `flows.urls` |
| `services/web/templates/base.html` | Nav: Flows link |
| `services/web/templates/flows/` | NEW templates (list, form) |
| `services/web/templates/transfers/create.html` | Show flow info in detail view |
| `services/web/templates/logs/list.html` | Type column |
| `services/worker/modules/relay/` | NEW module |
| `services/worker/tasks.py` | Relay branch in `execute_transfer` |
| `services/worker/tests/test_relay_handler.py` | NEW |
| `services/worker/tests/test_tasks.py` | Extend relay case |
