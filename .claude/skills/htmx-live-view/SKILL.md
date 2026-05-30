---
name: htmx-live-view
description: Wzorzec Django + HTMX dla widoków z live-update — log terminal, status transferu, wynik testu połączenia.
---

Projekt używa HTMX zamiast React/Vue. Widoki live-update działają przez polling partial HTML. Brak WebSocket.

## Warianty wzorca

### A) Polling ciągły (log terminal, status running)

Używany w: widok logów transferu (`/transfers/<pk>/logs/`).

**View (Django):**
```python
# views.py — zwraca partial HTML, NIE pełną stronę
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.contrib.auth.decorators import login_required

@login_required
def transfer_logs_partial(request, pk):
    job = get_object_or_404(TransferJob, pk=pk, owner=request.user)
    logs = job.logs.all()
    return TemplateResponse(request, 'transfers/_logs_partial.html', {'job': job, 'logs': logs})
```

**URL:**
```python
# urls.py
path('<int:pk>/logs/', views.transfer_logs_partial, name='transfer-logs'),
```

**Szablon partial (`_logs_partial.html`)** — BEZ `{% extends %}`:
```html
{% for log in logs %}
<div class="log-line log-{{ log.level }}">
  <span style="color:#444">{{ log.timestamp|time:"H:i:s" }}</span> {{ log.message }}
</div>
{% empty %}
<div class="log-line log-info">Oczekiwanie na logi...</div>
{% endfor %}
```

**Szablon główny — kontener z pollingiem:**
```html
<div class="log-terminal"
     id="log-output"
     hx-get="{% url 'transfers:transfer-logs' job.pk %}"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  {# zawartość inicjalna — zostanie zastąpiona przez HTMX #}
</div>
```

Zatrzymaj polling gdy transfer zakończony (status done/failed):
```html
<div class="log-terminal"
     id="log-output"
     hx-get="{% url 'transfers:transfer-logs' job.pk %}"
     hx-trigger="every 2s [document.getElementById('job-status').dataset.status === 'running']"
     hx-swap="innerHTML">
</div>
<span id="job-status"
      data-status="{{ job.status }}"
      class="status status-{{ job.status }}">{{ job.status|upper }}</span>
```

---

### B) Jednorazowy trigger (wynik akcji — test połączenia, uruchomienie transferu)

Używany w: `[TEST CONNECTION]` — request POST → wynik pojawia się bez przeładowania.

**View:**
```python
@login_required
def test_connection(request, pk):
    conn = get_object_or_404(Connection, pk=pk, owner=request.user)
    # ... logika testu ...
    ok = True  # lub False
    return TemplateResponse(request, 'connections/_test_result.html', {'ok': ok, 'message': msg})
```

**Partial (`_test_result.html`):**
```html
{% if ok %}
<div class="msg-success">[ OK ] {{ message }}</div>
{% else %}
<div class="msg-error">[ ERR ] {{ message }}</div>
{% endif %}
```

**Przycisk w szablonie:**
```html
<button class="btn"
        hx-post="{% url 'connections:test' conn.pk %}"
        hx-target="#test-result"
        hx-swap="innerHTML"
        hx-indicator="#spinner">
  [ TEST CONNECTION ]
</button>
<span id="spinner" class="htmx-indicator" style="color: var(--amber)"> TESTING...</span>
<div id="test-result"></div>
```

---

### C) Usuwanie wiersza z tabeli (bez przeładowania)

```html
<tr id="conn-row-{{ conn.pk }}">
  <td>{{ conn.name }}</td>
  <td>
    <button class="btn btn-danger"
            hx-delete="{% url 'connections:delete' conn.pk %}"
            hx-target="#conn-row-{{ conn.pk }}"
            hx-swap="outerHTML"
            hx-confirm="Usunąć połączenie {{ conn.name }}?">
      [ USUŃ ]
    </button>
  </td>
</tr>
```

View DELETE zwraca pusty `HttpResponse` (status 200) — HTMX zastępuje wiersz pustym stringiem.

---

## Reguły HTMX w tym projekcie

- Partial templates nazywaj z prefiksem `_` (np. `_logs_partial.html`, `_test_result.html`)
- Partial **nie** używa `{% extends "base.html" %}` — zwraca tylko fragment HTML
- `hx-target` wskazuje na `id` kontenera w głównym szablonie
- `hx-swap="innerHTML"` zastępuje zawartość; `hx-swap="outerHTML"` zastępuje cały element (np. wiersz tabeli)
- HTMX jest ładowany globalnie w `base.html` — nie importuj ponownie
- Używaj `hx-confirm` dla akcji destrukcyjnych (delete, reset)
