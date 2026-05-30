---
name: retro-style
description: Zasady stylizacji UI w estetyce Terminal/CRT dla tmask-tt — Django templates, klasy CSS z crt.css.
---

Interfejs naśladuje terminal CRT lat 80. Plik stylów: `services/web/static/css/crt.css`. Nie twórz nowych klas CSS dla rzeczy, które już istnieją.

## Paleta kolorów (`crt.css` — zmienne CSS)

```css
--bg: #0a0a0a          /* tło — prawie czarny */
--green: #33ff33       /* tekst podstawowy — fosforyzująca zieleń */
--green-bright: #00ff41 /* akcenty, nagłówki, glow */
--amber: #ffb000       /* ostrzeżenia, status running */
--red: #ff3333         /* błędy, akcje destrukcyjne */
--dim: #1a1a1a         /* tło wierszy tabeli hover */
--border: #1f4d1f      /* obramowania boxów */
```

Nie używaj żadnych innych kolorów. Nigdy pastelowych gradientów ani `border-radius > 0`.

## Typografia

Font: `'JetBrains Mono'` (Google Fonts) z fallbackiem `'Courier New', monospace`. Już załadowany globalnie — nie dodawaj ponownie.

## Gotowe klasy CSS

### Kontenery

```html
<!-- Sekcja z tytułem w ASCII ramce -->
<div class="box">
  <span class="box-title">NAZWA SEKCJI</span>
  treść
</div>
```

### Przyciski

```html
<button class="btn">[ AKCJA ]</button>          <!-- zielony, glow on hover -->
<button class="btn btn-danger">[ USUŃ ]</button> <!-- czerwony -->
<button class="btn btn-warn">[ OSTRZEŻENIE ]</button> <!-- amber -->
<a href="..." class="btn">[ LINK ]</a>
```

Etykiety przycisków w nawiasach kwadratowych: `[ TEST CONNECTION ]`, `[ RUN NOW ]`, `[ SAVE ]`.

### Statusy transferów

```html
<span class="status status-pending">PENDING</span>
<span class="status status-running">RUNNING</span>  <!-- pulsuje amber -->
<span class="status status-done">DONE</span>
<span class="status status-failed">FAILED</span>
```

### Log terminal (HTMX live)

```html
<div class="log-terminal" id="log-output"
     hx-get="/transfers/{{ job.pk }}/logs/"
     hx-trigger="every 2s"
     hx-swap="innerHTML">
  {% for line in logs %}
  <div class="log-line log-{{ line.level }}">{{ line.message }}</div>
  {% endfor %}
</div>
```

Klasy linii: `log-info` (zielony), `log-warn` (amber), `log-error` (czerwony).

### Formularze

```html
{% for field in form %}
<div class="field">
  {{ field.label_tag }}
  {{ field }}
  {% if field.errors %}<div class="msg-error">{{ field.errors }}</div>{% endif %}
</div>
{% endfor %}
```

### Komunikaty systemowe

```html
<div class="msg-success">[ OK ] Operacja zakończona</div>
<div class="msg-error">[ ERR ] Coś poszło nie tak</div>
```

## Efekty CRT

Scanlines są nakładane globalnie przez `body::after` — nie duplikuj tego w komponentach. Glow (`text-shadow: 0 0 8px`) używaj tylko na nagłówkach `h1`, `h2` lub elementach z klasą `.glow`.

## Zasady pisania szablonów

- Dziedzicz zawsze z `{% extends "base.html" %}`
- Tekst uppercase z letter-spacing dla nagłówków tabel (`th`)
- Brak zaokrągleń — `border-radius: 0` wszędzie
- ASCII dekoracje w tytułach: `[`, `]`, `>`, `──` zamiast ikon
