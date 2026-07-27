# Dark Ops Console — Redesign wizualny tmask-transporter — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zastąpić motyw "terminal CRT" (fosforyzująca zieleń, scanlines, ASCII-ramki) nowoczesnym dark-mode design systemem "Dark Ops Console" (slate/navy, Inter + JetBrains Mono, karty zamiast ASCII-ramek, glow punktowy) w całej aplikacji tmask-transporter, bez zmiany żadnej funkcji ani struktury nawigacji.

**Architecture:** Jeden plik CSS (`static/css/crt.css`, treść całkowicie wymieniona) + dwa self-hostowane fonty (Inter, JetBrains Mono) jako fundament (Task 1), potem `base.html`+`500.html` (Task 2), potem migracja pozostałych 28 szablonów w 7 grupach funkcjonalnych (Task 3–9), każda grupa: reskin markupu + przeniesienie inline `style=`/`<style>` do wspólnego arkusza + weryfikacja testów Django.

**Tech Stack:** Django templates (plain HTML, brak SPA), plain CSS (brak preprocesora/build stepu), vanilla JS per-feature, Chart.js v4.4.6 (self-hosted), HTMX (self-hosted). Repo: `/Users/dniemczok/Desktop/TMaskPL/tmask-tt/`, kod web w `services/web/`.

## Global Constraints

- **Zero zmian funkcjonalnych** — żadna strona nie zyskuje/traci funkcji, żadne query/URL/view/model nie zmienia się w tym planie.
- **Zero zmian struktury nawigacji** — te same linki w `nav`, ta sama hierarchia stron.
- **Dark-only** — brak trybu jasnego. Brak build stepu — plain CSS, `{% static %}`, cache-busting ręczny `?v=N` w `base.html`.
- **Zachować dokładnie te nazwy klas** (JS zależy od nich przez `querySelectorAll`) — NIE zmieniać, NIE usuwać:
  - `.ssh-only-field`, `.db-kind-field` (używane w `static/js/connections_form.js:17-18`)
  - `.cron-ex` (używane w `static/js/scheduler_form.js:4`)
  - `#file-browser-overlay`, `#file-browser-modal`, `#file-browser-content` (używane w `static/js/browser.js`, atrybuty `data-browse-*`)
  - `.file-hidden`, `data-file-display` (używane przez logikę pokazywania nazwy wybranego pliku)
  - wszystkie `id=` atrybuty w formularzach/przyciskach referowane przez JS (np. `#dry-run-btn`, `#execute-btn`, `#sched-form`, `#id_table_name`, `#api-token-label`, `#copy-token-btn`, `#close-token-modal`, `#new-token-value`, `#import-file`, `#import-file-name`, `#upload-file-name`, `#scan-btn`, `#scan-result`, `#webhook-test-result`, `#known-host-section`) — te NIE zmieniają się w żadnym tasku.
- **Zero testów asercjących stary markup** — potwierdzone przez `grep -rn "assertContains" apps --include="test_*.py"` skrzyżowane z `box-title`/tekstem przycisków: **brak wyników**. Żaden istniejący test Django nie asercjuje treści `[ LABEL ]` ani klasy `.box`/`.box-title` — redesign nie wymaga poprawek testów z tego powodu. Mimo to każdy task kończy się pełnym przebiegiem testów `web` (i `worker` jeśli task dotyka czegoś współdzielonego — w tym planie nie dotyczy, cały plan jest czysto frontendowy w `services/web/`).
- **Konwencja zamiany etykiet przycisków** (patrz spec, sekcja "Przyciski — decyzja o `[ LABEL ]`"): usuń nawiasy kwadratowe i otaczające spacje; camelCase→Title Case dla zwykłych słów; zachowaj wielkimi literami akronimy: `SSH`, `DB`, `API`, `ID`, `QR`, `2FA`, `CRON`. Zachowaj wiodący symbol `+` bez zmian (np. `+ Dodaj Usera`). Każdy task poniżej podaje dokładną tabelę starych→nowych etykiet — nie improwizować.
- **Cache-busting**: każdy task, który zmienia `crt.css`, bumpuje `?v=N` w `templates/base.html` (i w dowolnym innym miejscu, które ładuje ten plik — sprawdzone: tylko `base.html:8`, `accounts/login.html:7`, `accounts/totp_verify.html:7` ładują go bez przechodzenia przez `base.html`, bo są renderowane przed zalogowaniem — patrz Task 2 i Task 4).
- **Testy uruchamiane per task**: `docker compose --profile test build web-test && docker compose --profile test run --rm web-test python -m pytest apps/ -q` (zawsze `build` jawnie przed `run` — [[feedback-docker-compose-run-stale-image]], stary obraz cicho maskuje wyniki).
- **Manualna weryfikacja per task** — uruchomić `docker compose up -d`, otworzyć `https://localhost` (self-signed cert), sprawdzić dotknięte strony w przeglądarce na 375px i 1440px, zgodnie z ogólną zasadą projektu dla zmian UI.

---

## Plik referencyjny: pełna treść nowego `static/css/crt.css`

Ten plik jest tworzony w Task 1 i **rozszerzany** (nie nadpisywany) w Task 3 (dashboard), Task 4 (profile/2FA), Task 8 (scheduler). Każdy z tych tasków dopisuje swoją sekcję na końcu pliku z komentarzem-nagłówkiem w tym samym stylu co istniejący `/* ====== DASHBOARD ====== */` dziś. Nazwa pliku **zostaje `crt.css`** (nie `theme.css`) — jedyne miejsce poza `base.html` które go referuje bezpośrednio to `accounts/login.html` i `accounts/totp_verify.html` (renderowane przed `base.html`'s nav), więc zmiana nazwy pliku wymagałaby aktualizacji 3 miejsc zamiast 1 bez żadnej korzyści — zostajemy przy istniejącej nazwie.

---

### Task 1: Design tokens + self-hosted fonty + współdzielone komponenty CSS

**Files:**
- Modify: `services/web/static/css/crt.css` (całkowita wymiana treści, 483 → nowa treść)
- Create: `services/web/static/fonts/inter-400.woff2`, `inter-500.woff2`, `inter-600.woff2`, `inter-700.woff2`
- Create: `services/web/static/fonts/jetbrains-mono-400.woff2`, `jetbrains-mono-700.woff2`
- Test: `services/web/apps/dashboard/tests/test_views.py` (istniejący plik — dopisujemy jeden smoke test, patrz Step 5)

**Interfaces:**
- Produces: design tokeny CSS (`--bg`, `--surface`, `--surface-raised`, `--border`, `--border-subtle`, `--text`, `--text-muted`, `--text-dim`, `--accent`, `--accent-dim`, `--accent-glow`, `--warn`, `--danger`, `--danger-glow`, `--radius-sm`, `--radius-md`, `--radius-lg`, `--shadow-card`, `--shadow-raised`, `--ease-standard`, `--font-ui`, `--font-mono`, `--font-size-xs/sm/base/lg/xl`) — wszystkie kolejne tasks konsumują te nazwy dokładnie.
- Produces: klasy `.panel`, `.panel-nested`, `.panel-title`, `.btn`/`.btn-danger`/`.btn-warn`/`.btn-small`, `.status`/`.status-pending/running/done/failed/cancelled`, `.toolbar`, `.row-actions`, `th.col-actions`/`td.col-actions`, `.field`/`.field-grid`/`.field-with-btn`/`.file-name`/`.file-hidden`, `.field-error`, `.field-hint`, `.messages`/`.msg-error`/`.msg-ok`/`.msg-success`, `.test-ok`/`.test-fail`/`.test-result`, `.progress-wrap`/`.progress-bar`/`.progress-bar-fill`/`.progress-label`, `.log-terminal`/`.log-line`/`.log-info/.log-warn/.log-error`, `.inline-form`, `.form-actions`, `.two-col`, `.center-viewport`, `.auth-card`, `.text-muted`, `nav`/`nav a`/`nav a.logo`/`.org-name`/`.nav-right`, `table`/`th`/`td`, `input`/`select`/`textarea`/`label`, `main`, `body`, `.glow` (opt-in, nie default na h1/h2), breakpointy 900/600/560px, `prefers-reduced-motion`.
- Consumes: nic (pierwszy task).

#### Step 1: Pobierz self-hostowane fonty (woff2)

Fonty Inter i JetBrains Mono to open-source (SIL Open Font License), pobierane raz i wersjonowane w repo jak każdy inny static asset (analogicznie do `static/js/chart.min.js`, które już jest w repo jako vendored plik).

```bash
mkdir -p /Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/static/fonts
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/static/fonts

# Inter — wagi 400/500/600/700, statyczne woff2 z oficjalnego release Google Fonts (rsms/inter)
curl -sfL -o inter-400.woff2 "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Regular.woff2"
curl -sfL -o inter-500.woff2 "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Medium.woff2"
curl -sfL -o inter-600.woff2 "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-SemiBold.woff2"
curl -sfL -o inter-700.woff2 "https://github.com/rsms/inter/raw/master/docs/font-files/Inter-Bold.woff2"

# JetBrains Mono — wagi 400/700 (bez zmian względem obecnego zakresu wag)
curl -sfL -o jetbrains-mono-400.woff2 "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/webfonts/JetBrainsMono-Regular.woff2"
curl -sfL -o jetbrains-mono-700.woff2 "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/webfonts/JetBrainsMono-Bold.woff2"

ls -la
```

Expected: 6 plików `.woff2`, każdy > 0 bajtów. Jeśli którykolwiek `curl` zwróci błąd (np. zmieniona ścieżka release) — sprawdzić aktualny URL na stronie projektu (`rsms.me/inter/` / `jetbrains.com/lp/mono/`) i pobrać ręcznie, nazwy plików muszą zostać dokładnie takie jak wyżej (kolejne tasks i `@font-face` poniżej referują te dokładne nazwy).

#### Step 2: Napisz kompletną nową treść `crt.css`

Zastąp **całą** zawartość pliku `/Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/static/css/crt.css` poniższą treścią:

```css
/* ============================================================
   FONTY — self-hosted (Inter + JetBrains Mono)
   ============================================================ */
@font-face {
  font-family: 'Inter';
  src: url('../fonts/inter-400.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter';
  src: url('../fonts/inter-500.woff2') format('woff2');
  font-weight: 500; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter';
  src: url('../fonts/inter-600.woff2') format('woff2');
  font-weight: 600; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'Inter';
  src: url('../fonts/inter-700.woff2') format('woff2');
  font-weight: 700; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'JetBrains Mono';
  src: url('../fonts/jetbrains-mono-400.woff2') format('woff2');
  font-weight: 400; font-style: normal; font-display: swap;
}
@font-face {
  font-family: 'JetBrains Mono';
  src: url('../fonts/jetbrains-mono-700.woff2') format('woff2');
  font-weight: 700; font-style: normal; font-display: swap;
}

/* ============================================================
   DESIGN TOKENS — "Dark Ops Console"
   ============================================================ */
:root {
  /* Powierzchnie */
  --bg:             #0f172a;
  --surface:        #1e293b;
  --surface-raised: #243244;
  --border:         #334155;
  --border-subtle:  #1e293b;

  /* Tekst */
  --text:       #f8fafc;
  --text-muted: #94a3b8;
  --text-dim:   #64748b;

  /* Akcent */
  --accent:      #22c55e;
  --accent-dim:  #16a34a;
  --accent-glow: rgba(34, 197, 94, 0.35);

  /* Semantyczne statusy */
  --warn:         #f59e0b;
  --warn-glow:    rgba(245, 158, 11, 0.3);
  --danger:       #ef4444;
  --danger-glow:  rgba(239, 68, 68, 0.3);

  /* Skala */
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --shadow-card:   0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3);
  --shadow-raised: 0 8px 24px rgba(0,0,0,0.35);
  --ease-standard: cubic-bezier(0.16, 1, 0.3, 1);

  /* Typografia */
  --font-ui:   'Inter', -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', 'Courier New', monospace;
  --font-size-xs:   0.75rem;
  --font-size-sm:   0.85rem;
  --font-size-base: 0.95rem;
  --font-size-lg:   1.25rem;
  --font-size-xl:   1.75rem;
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-ui);
  font-size: var(--font-size-base);
  line-height: 1.5;
  min-height: 100vh;
}

h1, h2 { font-weight: 700; letter-spacing: 0.01em; }

/* Opt-in glow — używany punktowo (nie domyślnie na h1/h2 jak w starym motywie) */
.glow {
  color: var(--accent);
  text-shadow: 0 0 8px var(--accent-glow);
}

/* ============================================================
   PANELE (zastępują dawne .box/.box-title)
   ============================================================ */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 1.25rem;
  margin-bottom: 1.25rem;
}

.panel-nested {
  background: var(--surface-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 1rem 1.25rem;
  margin: 1rem 0;
}

.panel-title {
  display: block;
  font-family: var(--font-ui);
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 1rem;
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 1rem;
}

@media (max-width: 600px) {
  .field-grid { grid-template-columns: 1fr; }
}

/* ============================================================
   NAVIGATION
   ============================================================ */
nav {
  border-bottom: 1px solid var(--border);
  padding: 0.75rem 1.5rem;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem 1.4rem;
  position: sticky;
  top: 0;
  background: rgba(30, 41, 59, 0.85);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  z-index: 100;
}

nav a.logo {
  color: var(--text);
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  border: none;
  padding: 0;
  margin-right: 0.4rem;
  text-decoration: none;
  transition: color 0.2s var(--ease-standard);
}

nav a.logo:hover, nav a.logo.active { color: var(--accent); }

.org-name {
  color: var(--text-dim);
  font-size: var(--font-size-xs);
  letter-spacing: 0.02em;
  margin-right: 1rem;
}

nav a {
  color: var(--text-muted);
  text-decoration: none;
  font-size: var(--font-size-sm);
  padding: 0.35rem 0.7rem;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  transition: border-color 0.2s var(--ease-standard), color 0.2s var(--ease-standard), background 0.2s var(--ease-standard);
}

nav a:hover, nav a.active {
  border-color: var(--border);
  background: var(--surface-raised);
  color: var(--text);
}

nav a.active { color: var(--accent); }

nav .nav-right { margin-left: auto; color: var(--text-dim); font-size: var(--font-size-xs); }

/* ============================================================
   LAYOUT
   ============================================================ */
main { padding: 2rem; max-width: 1200px; margin: 0 auto; }

/* ============================================================
   TABLES
   ============================================================ */
table { width: 100%; border-collapse: collapse; }
th {
  color: var(--text-muted);
  text-align: left;
  padding: 0.6rem 0.5rem;
  border-bottom: 1px solid var(--border);
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
td { padding: 0.6rem 0.5rem; border-bottom: 1px solid var(--border-subtle); }
tr:hover td { background: var(--surface-raised); }

th.col-actions, td.col-actions { text-align: right; white-space: nowrap; }

.row-actions {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  justify-content: flex-end;
}

.toolbar { margin-bottom: 1.25rem; }

/* ============================================================
   FORMS
   ============================================================ */
input, select, textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  font-family: inherit;
  font-size: inherit;
  border-radius: var(--radius-sm);
  padding: 0.5rem 0.7rem;
  width: 100%;
  outline: none;
  transition: border-color 0.2s var(--ease-standard), box-shadow 0.2s var(--ease-standard);
}

input:focus, select:focus, textarea:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

label {
  display: block;
  margin-bottom: 0.3rem;
  color: var(--text-muted);
  font-size: var(--font-size-sm);
  font-weight: 500;
}

.field { margin-bottom: 1rem; }

.field-error { color: var(--danger); font-size: var(--font-size-xs); margin-top: 0.25rem; display: block; }
.field-hint  { color: var(--text-dim); font-size: var(--font-size-xs); margin-top: 0.25rem; display: block; }

.field-with-btn { display: flex; gap: 0.5rem; align-items: center; }
.field-with-btn input,
.field-with-btn select { flex: 1; }

.file-name { font-size: var(--font-size-xs); color: var(--text-muted); }
label.btn-small { cursor: pointer; }
.file-hidden {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

/* ============================================================
   BUTTONS
   ============================================================ */
.btn {
  background: var(--surface-raised);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-family: var(--font-ui);
  font-weight: 500;
  font-size: var(--font-size-sm);
  padding: 0.5rem 1.1rem;
  text-decoration: none;
  display: inline-block;
  transition: border-color 0.2s var(--ease-standard), color 0.2s var(--ease-standard), box-shadow 0.2s var(--ease-standard), background 0.2s var(--ease-standard);
}

.btn:hover { border-color: var(--accent); color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.btn-danger { border-color: var(--danger); color: var(--danger); }
.btn-danger:hover { box-shadow: 0 0 0 3px var(--danger-glow); }

.btn-warn { border-color: var(--warn); color: var(--warn); }
.btn-warn:hover { box-shadow: 0 0 0 3px var(--warn-glow); }

.btn-small { padding: 0.35rem 0.65rem; font-size: var(--font-size-xs); white-space: nowrap; }

/* ============================================================
   STATUS PILLS
   ============================================================ */
.status {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: var(--font-size-xs);
  font-weight: 500;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  color: var(--text-muted);
}

.status-pending   { color: var(--text-dim); }
.status-running   { color: var(--warn); border-color: var(--warn); animation: pulse 1.5s ease-in-out infinite; }
.status-done      { color: var(--accent); border-color: var(--accent); }
.status-failed    { color: var(--danger); border-color: var(--danger); }
.status-cancelled { color: var(--text-dim); }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }

/* ============================================================
   PROGRESS BAR
   ============================================================ */
.progress-wrap { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
.progress-bar {
  flex: 1;
  height: 0.9rem;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 999px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: var(--accent);
  box-shadow: 0 0 6px var(--accent-glow);
  transition: width 0.4s var(--ease-standard);
}
.progress-label { font-size: var(--font-size-xs); color: var(--accent); min-width: 3.5em; text-align: right; }

/* ============================================================
   LOG TERMINAL — jedyne miejsce z "prawdziwym terminalem"
   ============================================================ */
.log-terminal {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  min-height: 200px;
  max-height: 400px;
  overflow-y: auto;
  padding: 1rem;
}

.log-line { margin-bottom: 0.2rem; }
.log-info  { color: var(--text-muted); }
.log-warn  { color: var(--warn); }
.log-error { color: var(--danger); }

/* ============================================================
   MESSAGES
   ============================================================ */
.messages { margin-bottom: 1rem; }
.msg-error   { color: var(--danger); background: rgba(239,68,68,0.08); padding: 0.6rem 0.8rem; border: 1px solid var(--danger); border-radius: var(--radius-sm); margin-bottom: 0.5rem; white-space: pre-wrap; }
.msg-ok      { color: var(--accent); background: rgba(34,197,94,0.08); padding: 0.6rem 0.8rem; border: 1px solid var(--accent); border-radius: var(--radius-sm); margin-bottom: 0.5rem; white-space: pre-wrap; }
.msg-success { color: var(--accent); background: rgba(34,197,94,0.08); padding: 0.6rem 0.8rem; border: 1px solid var(--accent); border-radius: var(--radius-sm); margin-bottom: 0.5rem; }

/* ============================================================
   TEST RESULT (connections/webhook inline test)
   ============================================================ */
.test-result {
  display: inline-block;
  vertical-align: middle;
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-xs);
  margin-left: 0.3rem;
}
.test-ok   { color: var(--accent); }
.test-fail { color: var(--danger); }

/* ============================================================
   UTILITY (zastępują powtarzalne inline style="...")
   ============================================================ */
.inline-form { display: inline; }
.form-actions { display: flex; gap: 1rem; margin-top: 1.5rem; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
.center-viewport { display: flex; justify-content: center; align-items: center; min-height: 100vh; }
.auth-card { width: 400px; }
.text-muted { color: var(--text-muted); }
.text-dim { color: var(--text-dim); }

/* ============================================================
   RESPONSIVE
   ============================================================ */
@media (max-width: 560px) {
  main { padding: 1rem; }
  nav { padding: 0.6rem 1rem; gap: 0.4rem 0.9rem; }
  nav .nav-right { width: 100%; margin-left: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .status-running { animation: none; }
}
```

**Uwaga:** ten plik będzie **rozszerzony** (nie nadpisany) w Task 3 (sekcja `DASHBOARD`), Task 4 (sekcja `PROFILE / 2FA`), Task 8 (sekcja `SCHEDULER`) — każdy z tych tasków dopisuje swoją sekcję na końcu z tym samym stylem nagłówka komentarza. Nie usuwaj istniejących sekcji przy dopisywaniu.

#### Step 3: Zweryfikuj składnię CSS

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -c "
import tinycss2
with open('static/css/crt.css') as f:
    rules = tinycss2.parse_stylesheet(f.read(), skip_whitespace=True)
errors = [r for r in rules if r.type == 'error']
print(f'{len(rules)} rules, {len(errors)} parse errors')
for e in errors: print(e)
"
```

Jeśli `tinycss2` nie jest zainstalowany w obrazie `web-test` — pomiń ten krok automatycznej walidacji i przejdź od razu do Step 4 (walidacja przez faktyczne załadowanie strony w przeglądarce jest wystarczająca, `tinycss2` to tylko szybki dodatkowy check).

Expected: `0 parse errors`.

#### Step 4: Bump cache-busting w `base.html`

W pliku `services/web/templates/base.html` linia 8, zmień:

```diff
- <link rel="stylesheet" href="{% static 'css/crt.css' %}?v=5">
+ <link rel="stylesheet" href="{% static 'css/crt.css' %}?v=6">
```

(Poza tym `base.html` nie jest jeszcze dotykany w tym tasku — pełna migracja nav/messages/modal jest w Task 2. Ten bump jest potrzebny już teraz, żeby przeglądarka nie serwowała starego pliku z cache przy manualnej weryfikacji poniżej.)

Analogicznie w `services/web/templates/accounts/login.html:7` i `services/web/templates/accounts/totp_verify.html:7` (jedyne dwa szablony renderowane przed `base.html`, ładujące `crt.css` bezpośrednio, bez `?v=` w ogóle dziś):

```diff
- <link rel="stylesheet" href="{% static 'css/crt.css' %}">
+ <link rel="stylesheet" href="{% static 'css/crt.css' %}?v=6">
```

#### Step 5: Dopisz smoke test (design tokens obecne)

Do istniejącego pliku `services/web/apps/dashboard/tests/test_views.py` dopisz na końcu:

```python
class DarkOpsConsoleTokensTest(TestCase):
    def test_stylesheet_defines_design_tokens(self):
        css_path = settings.BASE_DIR / "static" / "css" / "crt.css"
        content = css_path.read_text()
        for token in ("--bg:", "--surface:", "--accent:", "--danger:", "--font-ui:", "--font-mono:"):
            self.assertIn(token, content, f"brak tokenu {token} w crt.css")
```

Sprawdź na górze pliku czy `from django.conf import settings` i `from django.test import TestCase` już są zaimportowane (prawdopodobnie tak, plik testuje widoki Django) — jeśli `settings` nie jest zaimportowany, dodaj `from django.conf import settings` do importów.

#### Step 6: Uruchom testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/dashboard/tests/test_views.py -v
```

Expected: `DarkOpsConsoleTokensTest::test_stylesheet_defines_design_tokens PASSED`, żaden istniejący test w tym pliku nie regresuje.

#### Step 7: Manualna weryfikacja fontów

```bash
docker compose up -d
curl -sk -o /dev/null -w "%{http_code}\n" https://localhost/static/fonts/inter-400.woff2
curl -sk -o /dev/null -w "%{http_code}\n" https://localhost/static/fonts/jetbrains-mono-400.woff2
```

Expected: oba `200`. Jeśli `404` — sprawdź czy `docker compose run --rm web python manage.py collectstatic --noinput` zostało uruchomione (fonty muszą trafić do `STATIC_ROOT`/`staticfiles/fonts/` tak samo jak `static/js/chart.min.js` dziś).

#### Step 8: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/static/css/crt.css services/web/static/fonts/ services/web/templates/base.html services/web/templates/accounts/login.html services/web/templates/accounts/totp_verify.html services/web/apps/dashboard/tests/test_views.py
git commit -m "feat(ui): design tokens + self-hosted fonty + komponenty bazowe (Dark Ops Console, task 1/9)"
```

---

### Task 2: `base.html` (nav, messages, file-browser modal) + `500.html`

**Files:**
- Modify: `services/web/templates/base.html` (całość, 62 linie)
- Modify: `services/web/templates/500.html` (całość, 15 linii)
- Modify: `services/web/static/css/crt.css` (dopisz sekcję `FILE BROWSER MODAL` na końcu)

**Interfaces:**
- Consumes: wszystkie tokeny/klasy z Task 1 (`.btn`, `.btn-danger`, `.msg-error`, `.msg-success`, `.inline-form`).
- Produces: klasy `#file-browser-overlay`/`#file-browser-modal`/`#file-browser-content` (CSS, markup id niezmieniony — JS z `browser.js` zależy od tych id), `.breadcrumbs`, `.file-list` (skonsumowane przez `connections/browser_fragment.html` w Task 5, ale CSS już gotowe tutaj).

#### Step 1: Dopisz sekcję File Browser Modal do `crt.css`

Na końcu `services/web/static/css/crt.css` (po sekcji `RESPONSIVE`/`prefers-reduced-motion` z Task 1) dopisz:

```css
/* ============================================================
   FILE BROWSER MODAL
   ============================================================ */
#file-browser-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

#file-browser-modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-raised);
  padding: 1.5rem;
  width: min(700px, 90vw);
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

#file-browser-content {
  overflow-y: auto;
  flex: 1;
  min-height: 200px;
}

.breadcrumbs {
  font-size: var(--font-size-sm);
  color: var(--warn);
  margin-bottom: 0.5rem;
  word-break: break-all;
}
.breadcrumbs a { color: var(--warn); text-decoration: none; }
.breadcrumbs a:hover { color: var(--accent); }

.file-list { list-style: none; }
.file-list li { padding: 0.3rem 0; border-bottom: 1px solid var(--border-subtle); }
.file-list a { color: var(--text); text-decoration: none; }
.file-list a:hover { color: var(--accent); }

.browse-actions { margin-bottom: 0.5rem; }
```

#### Step 2: Przepisz `base.html`

Zastąp całą treść `/Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}TMASK-TRANSPORTER{% endblock %}</title>
  {% load static %}
  <link rel="stylesheet" href="{% static 'css/crt.css' %}?v=6">
  <script src="{% static 'js/htmx.min.js' %}"></script>
  <script src="{% static 'js/browser.js' %}?v=2"></script>
  <script src="{% static 'js/confirm-forms.js' %}"></script>
</head>
<body>
  {% if user.is_authenticated %}
  <nav>
    <a href="{% url 'dashboard:index' %}" class="logo {% if request.resolver_match.app_name == 'dashboard' %}active{% endif %}" title="Dashboard">TMASK-TRANSPORTER</a>
    <span class="org-name">{{ organization.name }}</span>
    <a href="{% url 'transfers:create' %}" class="{% if request.resolver_match.app_name == 'transfers' %}active{% endif %}">Transfers</a>
    <a href="{% url 'connections:list' %}" class="{% if request.resolver_match.app_name == 'connections' %}active{% endif %}">Connections</a>
    <a href="{% url 'flows:list' %}" class="{% if request.resolver_match.app_name == 'flows' %}active{% endif %}">Flows</a>
    <a href="{% url 'scheduler:list' %}" class="{% if request.resolver_match.app_name == 'scheduler' %}active{% endif %}">Scheduler</a>
    <a href="{% url 'db_transfers:list' %}" class="{% if request.resolver_match.app_name == 'db_transfers' %}active{% endif %}">DB Transfers</a>
    <a href="{% url 'transfers:logs' %}">Logs</a>
    {% if user.is_admin %}
    <a href="{% url 'accounts:users' %}">Users</a>
    <a href="{% url 'audit_log:list' %}" class="{% if request.resolver_match.app_name == 'audit_log' %}active{% endif %}">Audit Log</a>
    {% endif %}
    <span class="nav-right">
      {{ user.username|upper }} [{{ user.role|upper }}]
      &nbsp;|&nbsp;
      <a href="{% url 'accounts:profile' %}">Profil</a>
      &nbsp;|&nbsp;
      <form method="post" action="{% url 'accounts:logout' %}" class="inline-form">
        {% csrf_token %}
        <button type="submit" class="btn btn-small">Logout</button>
      </form>
    </span>
  </nav>
  {% endif %}

  <main>
    {% if messages %}
    <div class="messages">
      {% for message in messages %}
      <div class="msg-{% if message.tags == 'error' %}error{% else %}success{% endif %}">
        {{ message }}
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% block content %}{% endblock %}
  </main>
  <div id="file-browser-overlay" style="display:none">
    <div id="file-browser-modal">
      <span class="panel-title">File Browser</span>
      <div id="file-browser-content"></div>
      <button type="button" class="btn btn-danger" data-browse-close>Zamknij</button>
    </div>
  </div>
  {% block scripts %}{% endblock %}
</body>
</html>
```

Zmiany wprowadzone (dla review — nie są to niezamierzone efekty uboczne):
- `[ TMASK-TRANSPORTER ]` → `TMASK-TRANSPORTER` (bez brakietów, styl przez `nav a.logo`)
- `TRANSFERS`/`CONNECTIONS`/... → `Transfers`/`Connections`/... (Title Case, zgodnie z konwencją — nawigacja to nie przycisk terminala, ale zwykły link, spójność z resztą UI)
- `USER: {{ user.username|upper }}` → `{{ user.username|upper }}` (słowo "USER:" było czysto dekoracyjne, informacja jest oczywista z kontekstu paska nav)
- `style="display:inline"` na formularzu logout → `class="inline-form"`
- `style="border:none;padding:0;"` na przycisku Logout → usunięte (nowy `.btn-small` już wygląda poprawnie w kontekście nav, nie trzeba go "odstylowywać" do zera)
- `> {{ message }}` → `{{ message }}` (usunięcie ozdobnego `>` przed komunikatem, `.msg-*` teraz ma własne tło/ramkę jako wskaźnik statusu)
- `<span class="box-title">FILE BROWSER</span>` → `<span class="panel-title">File Browser</span>`
- `[ ZAMKNIJ ]` → `Zamknij`

#### Step 3: Przepisz `500.html`

Zastąp całą treść `/Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/templates/500.html`:

```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  body {
    background: #0f172a; color: #f8fafc; font-family: -apple-system, sans-serif;
    display: flex; justify-content: center; align-items: center; height: 100vh;
  }
  .panel {
    background: #1e293b; border: 1px solid #334155; border-radius: 10px;
    padding: 3rem; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.35);
  }
  h1 { color: #ef4444; font-size: 2rem; margin-bottom: 0.5rem; }
  p { color: #94a3b8; margin-bottom: 1.5rem; }
  a {
    color: #22c55e; text-decoration: none; border: 1px solid #22c55e;
    border-radius: 6px; padding: 0.5rem 1.2rem; display: inline-block;
  }
  a:hover { box-shadow: 0 0 0 3px rgba(34,197,94,0.35); }
</style></head>
<body>
  <div class="panel">
    <h1>System Error</h1>
    <p>Kernel panic — skontaktuj się z administratorem</p>
    <a href="/">Reboot</a>
  </div>
</body></html>
```

`500.html` musi zostać samodzielny (bez `{% load static %}`/`{% extends %}`) — Django renderuje customowy handler 500 często poza pełnym middleware stack, więc hardcodowane hex-y zamiast `var(--token)` są celowe (nie próbujemy ładować `crt.css` tutaj, tak jak nie robił tego oryginał).

#### Step 4: Testy — sprawdź czy istniejący test 500 nadal przechodzi

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
grep -rln "500" services/web/apps --include="test_*.py" | xargs grep -l "500.html\|status_code, 500\|force_500\|/500" 2>/dev/null
```

Jeśli grep nic nie zwróci — nie ma dedykowanego testu dla `500.html`, pomiń ten krok (strona nie jest odwiedzana automatycznie w `DEBUG=True` dev/test środowisku). Jeśli grep coś zwróci, otwórz wskazany plik i sprawdź czy asercjuje treść tekstową usuniętą w Step 3 (`[ SYSTEM ERROR ]`, `KERNEL PANIC — CONTACT ADMIN`, `[ REBOOT ]`) — jeśli tak, zaktualizuj assercję na nowy tekst (`System Error`, `Kernel panic — skontaktuj się z administratorem`, `Reboot`).

#### Step 5: Pełny przebieg testów `web`

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: `541 passed` (bez regresji — ten task nie dodaje nowych testów, tylko sprawdza że żaden istniejący się nie zepsuł).

#### Step 6: Manualna weryfikacja w przeglądarce

```bash
docker compose up -d --build
```

Otwórz `https://localhost` zalogowany — sprawdź: nav renderuje się poprawnie (sticky, blur tła przy scrollu), aktywny link podświetlony akcentem, komunikat po zalogowaniu/wylogowaniu ma nowy styl `.msg-*`, modal file-browsera (kliknij `BROWSE` na dowolnym polu ścieżki w Connections/Transfers) otwiera się z nowym wyglądem karty.

#### Step 7: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/base.html services/web/templates/500.html services/web/static/css/crt.css
git commit -m "feat(ui): base.html nav/messages/modal + 500.html na nowym design systemie (task 2/9)"
```

---

### Task 3: Dashboard (`dashboard/index.html` + `dashboard.js`)

**Files:**
- Modify: `services/web/templates/dashboard/index.html` (całość, 53 linie)
- Modify: `services/web/static/js/dashboard.js` (linie 6-8, 49-50)
- Modify: `services/web/static/css/crt.css` (dopisz sekcję `DASHBOARD` na końcu)

**Interfaces:**
- Consumes: `.panel`, `.panel-title`, `--accent`, `--danger`, `--warn`, `--text-muted`, `--radius-md`, `--shadow-card`, `--ease-standard` z Task 1.
- Produces: `.dash-header`, `.dash-sub`, `.dash-empty`, `.stat-grid`, `.stat-tile`, `.stat-value`, `.stat-label`, `.chart-grid`, `.chart-box`, `.chart-canvas` — używane wyłącznie na tej stronie, żaden kolejny task ich nie konsumuje.

#### Step 1: Dopisz sekcję Dashboard do `crt.css`

Na końcu `services/web/static/css/crt.css` dopisz:

```css
/* ============================================================
   DASHBOARD
   ============================================================ */
.dash-header {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}

.dash-header h1 {
  font-size: var(--font-size-xl);
  letter-spacing: 0.02em;
}

.dash-sub { color: var(--text-dim); font-size: var(--font-size-sm); }

.dash-empty {
  border: 1px dashed var(--border);
  border-radius: var(--radius-md);
  color: var(--warn);
  padding: 2.5rem 1rem;
  text-align: center;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  margin-bottom: 2.6rem;
}

.stat-tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: 1.1rem 1.2rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  position: relative;
  min-width: 0;
  overflow: hidden;
  transition: border-color 0.25s var(--ease-standard), transform 0.25s var(--ease-standard), box-shadow 0.25s var(--ease-standard);
  animation: tile-rise 0.5s var(--ease-standard) both;
}

.stat-tile::before {
  content: '';
  position: absolute;
  top: 0; left: 0; bottom: 0;
  width: 3px;
  background: var(--accent);
}

.stat-tile:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: var(--shadow-raised);
}

.stat-value {
  font-size: 2.4rem;
  font-weight: 700;
  line-height: 1;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: var(--font-size-xs);
  letter-spacing: 0.04em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.stat-tile.accent-done::before    { background: var(--accent); }
.stat-tile.accent-failed::before  { background: var(--danger); }
.stat-tile.accent-failed .stat-value { color: var(--danger); }
.stat-tile.accent-rate::before    { background: var(--warn); }
.stat-tile.accent-rate .stat-value { color: var(--warn); }

.stat-tile:nth-child(1) { animation-delay: 0.00s; }
.stat-tile:nth-child(2) { animation-delay: 0.07s; }
.stat-tile:nth-child(3) { animation-delay: 0.14s; }
.stat-tile:nth-child(4) { animation-delay: 0.21s; }

@keyframes tile-rise {
  from { opacity: 0; transform: translateY(14px); }
  to   { opacity: 1; transform: translateY(0); }
}

.chart-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1.5rem;
  align-items: stretch;
  margin-top: 0.5rem;
}

.chart-box {
  margin-bottom: 0;
  min-width: 0;
  animation: tile-rise 0.5s var(--ease-standard) 0.24s both;
}
.chart-box.chart-full { grid-column: 1 / -1; }

.chart-canvas {
  position: relative;
  min-width: 0;
  height: 280px;
  margin-top: 0.4rem;
}

.chart-box.chart-full .chart-canvas { height: 240px; }

@media (max-width: 900px) {
  .stat-grid { grid-template-columns: repeat(2, 1fr); }
  .chart-grid { grid-template-columns: 1fr; }
  .chart-box.chart-full { grid-column: auto; }
}

@media (max-width: 560px) {
  .stat-grid { grid-template-columns: 1fr 1fr; gap: 0.6rem; }
  .stat-value { font-size: 1.9rem; }
  .dash-header h1 { font-size: 1.4rem; }
  .chart-canvas { height: 240px; }
}

@media (prefers-reduced-motion: reduce) {
  .stat-tile, .chart-box { animation: none; }
}
```

#### Step 2: Przepisz `dashboard/index.html`

Zastąp całą treść `/Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/templates/dashboard/index.html`:

```html
{% extends 'base.html' %}
{% load static %}
{% block title %}DASHBOARD — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="dash-header">
  <h1>Dashboard</h1>
  <span class="dash-sub">ostatnie 30 dni</span>
</div>

{{ data|json_script:"dashboard-data" }}

{% if data.success.total %}
<section class="stat-grid">
  <div class="stat-tile">
    <span class="stat-value">{{ data.success.total }}</span>
    <span class="stat-label">Transfery</span>
  </div>
  <div class="stat-tile accent-done">
    <span class="stat-value">{{ data.success.done }}</span>
    <span class="stat-label">Udane</span>
  </div>
  <div class="stat-tile accent-failed">
    <span class="stat-value">{{ data.success.failed }}</span>
    <span class="stat-label">Błędy</span>
  </div>
  <div class="stat-tile accent-rate">
    <span class="stat-value">{{ data.success.rate_pct }}%</span>
    <span class="stat-label">Success rate</span>
  </div>
</section>

<div class="chart-grid">
  <div class="panel chart-box">
    <span class="panel-title">Transfery / dzień</span>
    <div class="chart-canvas"><canvas id="chart-per-day"></canvas></div>
  </div>
  <div class="panel chart-box">
    <span class="panel-title">Success rate</span>
    <div class="chart-canvas"><canvas id="chart-success"></canvas></div>
  </div>
  <div class="panel chart-box chart-full">
    <span class="panel-title">Top źródła</span>
    <div class="chart-canvas"><canvas id="chart-top"></canvas></div>
  </div>
</div>
{% else %}
<div class="dash-empty">Brak danych — wykonaj pierwszy transfer</div>
{% endif %}
{% endblock %}
{% block scripts %}
<script src="{% static 'js/chart.min.js' %}"></script>
<script src="{% static 'js/dashboard.js' %}?v=3"></script>
{% endblock %}
```

Zmiana: `?v=2` → `?v=3` na `dashboard.js` (bump cache-busting, bo plik zmienia się w Step 3 poniżej). `class="glow"` usunięty z `<h1>DASHBOARD</h1>` — nagłówek dashboardu nie potrzebuje już glow (spec: glow punktowy, nie na każdym h1). `// ostatnie 30 dni` → `ostatnie 30 dni` (usunięcie ozdobnego `//`, `.dash-sub` ma już własny stonowany kolor).

#### Step 3: Zaktualizuj paletę w `dashboard.js`

W `/Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web/static/js/dashboard.js`, linie 6-8:

```diff
-  // paleta CRT (tokeny z crt.css)
-  const GREEN = '#00ff41', RED = '#ff3333', AMBER = '#ffb000';
-  const GRID = 'rgba(51, 255, 51, 0.08)', TICK = '#7fae7f';
+  // paleta Dark Ops Console (tokeny z crt.css :root)
+  const ACCENT = '#22c55e', DANGER = '#ef4444', WARN = '#f59e0b';
+  const GRID = 'rgba(148, 163, 184, 0.12)', TICK = '#94a3b8';
```

I linia 17 (font family):

```diff
-  Chart.defaults.font.family = "'JetBrains Mono', monospace";
+  Chart.defaults.font.family = "'Inter', -apple-system, sans-serif";
```

Następnie zamień pozostałe wystąpienia `GREEN`/`RED`/`AMBER` na `ACCENT`/`DANGER`/`WARN` w całym pliku (linie 30-31, 49-50, 51, 65):

```diff
       datasets: [
-        { label: 'DONE', data: data.per_day.done, backgroundColor: GREEN, borderRadius: 2, maxBarThickness: 22 },
-        { label: 'FAILED', data: data.per_day.failed, backgroundColor: RED, borderRadius: 2, maxBarThickness: 22 },
+        { label: 'DONE', data: data.per_day.done, backgroundColor: ACCENT, borderRadius: 4, maxBarThickness: 22 },
+        { label: 'FAILED', data: data.per_day.failed, backgroundColor: DANGER, borderRadius: 4, maxBarThickness: 22 },
       ],
```

```diff
       datasets: [{
         data: [data.success.done, data.success.failed, data.success.other],
-        backgroundColor: [GREEN, RED, AMBER],
-        borderColor: '#0a0a0a',
+        backgroundColor: [ACCENT, DANGER, WARN],
+        borderColor: '#1e293b',
         borderWidth: 2,
         hoverOffset: 8,
       }],
```

```diff
-      datasets: [{ label: 'JOBS', data: data.top.counts, backgroundColor: GREEN, borderRadius: 2, maxBarThickness: 18 }],
+      datasets: [{ label: 'JOBS', data: data.top.counts, backgroundColor: ACCENT, borderRadius: 4, maxBarThickness: 18 }],
```

(`borderColor: '#0a0a0a'` → `'#1e293b'` bo to obwódka segmentów doughnut chart, musi pasować do nowego `--surface` tła karty, nie starego `--bg` czerni; `borderRadius: 2` → `4` — delikatnie bardziej zaokrąglone słupki, spójne z ogólnym podniesieniem `radius` w całym designie.)

#### Step 4: Testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/dashboard/ -v
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: wszystkie testy dashboard PASSED, pełny suite `541 passed` (JS nie jest testowany przez pytest — weryfikacja wizualna w Step 5 pokrywa poprawność wykresów).

#### Step 5: Manualna weryfikacja

```bash
docker compose up -d --build
```

Otwórz `https://localhost/` (dashboard) — sprawdź: 4 kafle KPI z wjazdem staggered animation, 3 wykresy Chart.js renderują się z nową paletą (zielony/czerwony/pomarańczowy na ciemnym tle, siatka w jasnoszarym kolorze zamiast zielonkawej), legenda czytelna, hover na kaflu podnosi go i podświetla obramowanie akcentem. Sprawdź na 375px i 1440px.

#### Step 6: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/dashboard/index.html services/web/static/js/dashboard.js services/web/static/css/crt.css
git commit -m "feat(ui): dashboard na nowym design systemie, Chart.js re-theming (task 3/9)"
```

---

### Task 4: Accounts + Users (login, profile, 2FA, users)

**Files:**
- Modify: `services/web/templates/accounts/login.html` (całość, 46 linii)
- Modify: `services/web/templates/accounts/profile.html` (całość, 499 linii — `<style>` blok usunięty, CSS przeniesione do `crt.css`)
- Modify: `services/web/templates/accounts/totp_setup.html` (całość, 38 linii)
- Modify: `services/web/templates/accounts/totp_verify.html` (całość, 31 linii)
- Modify: `services/web/templates/accounts/totp_recovery_codes.html` (całość, 23 linie)
- Modify: `services/web/templates/users/list.html` (całość, 38 linii)
- Modify: `services/web/templates/users/create.html` (całość, 24 linie)
- Modify: `services/web/static/css/crt.css` (dopisz sekcję `PROFILE / 2FA` na końcu)
- No change: `services/web/templates/accounts/_webhook_test_result.html` (już używa `.test-ok`/`.test-fail` z Task 1, zero zmian potrzebnych)

**Interfaces:**
- Consumes: `.panel`, `.panel-title`, `.btn`/`.btn-danger`/`.btn-small`, `.field`, `.field-error`, `.center-viewport`, `.auth-card`, `.msg-error`, `.text-muted`, tokeny z Task 1.
- Produces: `.profile-header`, `.channel-card`, `.channel-title`, `.status-dot`, `.cf-row`, `.cf-label`, `.cf-input-row`, `.cf-error`, `.cf-divider`, `.cb-group`, `.cb-row`, `.cf-status`, `.profile-save`, `.tokens-panel`, `.tokens-title`, `.tokens-table`, `.token-label`, `.token-date`, `.token-gen-row`, `.no-tokens`, `.backup-section`, `.backup-section-title`, `.backup-grid`, `.backup-desc`, `.backup-vform`, `.token-modal-overlay`, `.token-modal` — używane wyłącznie w `profile.html`, żaden inny task ich nie konsumuje.

#### Step 1: Dopisz sekcję Profile/2FA do `crt.css`

Na końcu `services/web/static/css/crt.css` dopisz (to jest bezpośrednie przeniesienie `<style>` bloku z `profile.html:6-232` na nowe tokeny, z uproszczeniem floating-label na zwykły panel-title):

```css
/* ============================================================
   PROFILE / 2FA
   ============================================================ */
.profile-header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1rem 1.5rem;
  margin-bottom: 2rem;
  display: flex;
  gap: 3rem;
  align-items: center;
  flex-wrap: wrap;
}
.profile-header .ph-field { display: flex; flex-direction: column; gap: 0.15rem; }
.profile-header .ph-label { font-size: var(--font-size-xs); color: var(--text-dim); letter-spacing: 0.04em; text-transform: uppercase; }
.profile-header .ph-value { color: var(--text); font-size: var(--font-size-lg); font-weight: 600; }
.profile-header .ph-value.small { font-size: var(--font-size-sm); font-weight: 400; }

.profile-grid {
  display: grid;
  grid-template-columns: 1fr 400px;
  gap: 1.5rem;
  align-items: start;
}
@media (max-width: 900px) {
  .profile-grid { grid-template-columns: 1fr; }
}

.channel-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1.25rem;
  margin-bottom: 1.25rem;
  transition: border-color 0.2s var(--ease-standard);
}
.channel-card:hover { border-color: var(--accent-dim); }

.channel-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.status-dot.active {
  background: var(--accent);
  box-shadow: 0 0 6px var(--accent-glow);
  animation: pulse 2s ease-in-out infinite;
}
.status-dot.inactive { background: var(--text-dim); }

.cf-row { margin-bottom: 0.85rem; }
.cf-row:last-child { margin-bottom: 0; }

.cf-label {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  margin-bottom: 0.3rem;
  display: block;
}

.cf-input-row { display: flex; gap: 0.5rem; align-items: center; }
.cf-input-row input[type="text"],
.cf-input-row input[type="email"],
.cf-input-row input[type="url"] { flex: 1; }

.cf-error { color: var(--danger); font-size: var(--font-size-xs); margin-top: 0.25rem; display: block; }

.cb-group { display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.85rem; }
.cb-row { display: flex; align-items: center; gap: 0.6rem; cursor: pointer; }
.cb-row input[type="checkbox"] { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; flex-shrink: 0; }
.cb-row label { font-size: var(--font-size-sm); color: var(--text-muted); cursor: pointer; margin: 0; }
.cb-row:hover label { color: var(--text); }

.cf-divider { border: none; border-top: 1px solid var(--border-subtle); margin: 0.85rem 0; }

.cf-status {
  font-size: var(--font-size-sm);
  color: var(--text-dim);
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-subtle);
}
.cf-status.no-border { border-top: none; padding-top: 0; }
.cf-status .active-val { color: var(--accent); }

.profile-save { margin-top: 0.5rem; padding-top: 1rem; border-top: 1px solid var(--border); }

.tokens-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1.25rem;
}
.tokens-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 1rem;
}

.tokens-table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; font-size: var(--font-size-sm); }
.tokens-table th { color: var(--text-dim); font-size: var(--font-size-xs); padding: 0 0 0.4rem; border-bottom: 1px solid var(--border-subtle); text-align: left; }
.tokens-table td { padding: 0.5rem 0; border-bottom: 1px solid var(--border-subtle); vertical-align: middle; }
.tokens-table tr:hover td { background: var(--surface-raised); }
.token-label { color: var(--text); }
.token-date { color: var(--text-dim); font-size: var(--font-size-xs); }

.token-gen-row { display: flex; gap: 0.5rem; align-items: center; margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--border-subtle); }
.token-gen-row input { flex: 1; font-size: var(--font-size-sm); }

.no-tokens { color: var(--text-dim); font-size: var(--font-size-sm); padding: 0.5rem 0 1rem; }

.backup-section { margin-top: 2rem; }
.backup-section-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 1.5rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}
.backup-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; align-items: start; }
.backup-grid .channel-card { margin-bottom: 0; }
.backup-desc { color: var(--text-dim); font-size: var(--font-size-sm); line-height: 1.5; margin-bottom: 1.1rem; min-height: 3.2em; }
.backup-vform { display: flex; flex-direction: column; gap: 0.9rem; }
.backup-vform .file-name { flex: 1; min-width: 0; }
.backup-vform .btn:not(.btn-small) { align-self: flex-start; margin-top: 0.2rem; }
@media (max-width: 720px) {
  .backup-grid { grid-template-columns: 1fr; }
  .backup-desc { min-height: 0; }
}

.token-modal-overlay {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex; align-items: center; justify-content: center;
}
.token-modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-raised);
  padding: 1.5rem 2rem;
  max-width: 560px;
  width: 90%;
}
.token-modal .token-warn { color: var(--warn); font-size: var(--font-size-sm); margin-bottom: 1rem; }
.token-modal .token-value-box {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.75rem 1rem;
  word-break: break-all;
  margin-bottom: 1rem;
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
}
.token-modal .token-actions { display: flex; gap: 0.75rem; }
```

#### Step 2: Przepisz `accounts/login.html`

```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>LOGIN — TMASK-TRANSPORTER</title>
  {% load static %}
  <link rel="stylesheet" href="{% static 'css/crt.css' %}?v=6">
</head>
<body>
<main class="center-viewport">
  <div class="auth-card">
    <div style="text-align:center; margin-bottom:2rem;">
      <h1 style="font-size:1.4rem; letter-spacing:0.05em;">TMASK-TRANSPORTER</h1>
      <p class="text-dim" style="font-size:0.8rem; margin-top:0.3rem;">File Transfer System</p>
    </div>

    <div class="panel">
      <span class="panel-title">Authentication Required</span>
      <form method="post">
        {% csrf_token %}
        {% if form.non_field_errors %}
        <div class="msg-error">
          {% for error in form.non_field_errors %}{{ error }}{% endfor %}
        </div>
        {% endif %}
        <div class="field">
          <label>Username</label>
          <input type="text" name="username" autofocus autocomplete="username"
                 value="{{ form.username.value|default:'' }}">
        </div>
        <div class="field">
          <label>Password</label>
          <input type="password" name="password" autocomplete="current-password">
        </div>
        <button type="submit" class="btn" style="width:100%;">Login</button>
      </form>
    </div>
  </div>
</main>
</body>
</html>
```

Zmiana istotna: usunięty ASCII-art `<pre>` logo (6 linii blokowego textu `████████╗███╗...`) — to jest najbardziej jaskrawy element starego motywu terminalowego niekompatybilny z "nowoczesny i dynamiczny"; zastąpiony prostym tekstowym nagłówkiem `TMASK-TRANSPORTER` + podtytułem. `style="width:400px;"` na wrapperze → `.auth-card`. `style="display:flex;justify-content:center;align-items:center;min-height:100vh;"` na `<main>` → `.center-viewport`. `[ LOGIN ]` → `Login`. `USERNAME:`/`PASSWORD:` → `Username`/`Password` (label bez dwukropka — dwukropek był częścią terminalowej konwencji `LABEL:`, `<label>` CSS już wizualnie oddziela pole).

#### Step 3: Przepisz `accounts/totp_verify.html`

```html
<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>2FA — TMASK-TRANSPORTER</title>
  {% load static %}
  <link rel="stylesheet" href="{% static 'css/crt.css' %}?v=6">
</head>
<body>
<main class="center-viewport">
  <div class="auth-card">
    <div class="panel">
      <span class="panel-title">Weryfikacja dwuskładnikowa</span>
      <form method="post">
        {% csrf_token %}
        {% if form.non_field_errors %}
        <div class="msg-error">
          {% for error in form.non_field_errors %}{{ error }}{% endfor %}
        </div>
        {% endif %}
        <div class="field">
          <label>Kod z aplikacji lub kod zapasowy</label>
          <input type="text" name="code" autofocus autocomplete="one-time-code">
        </div>
        <button type="submit" class="btn" style="width:100%;">Zatwierdź</button>
      </form>
    </div>
  </div>
</main>
</body>
</html>
```

#### Step 4: Przepisz `accounts/totp_setup.html`

```html
{% extends "base.html" %}
{% block title %}2FA SETUP — TMASK-TRANSPORTER{% endblock %}
{% block content %}

<div class="tokens-panel" style="max-width:480px; margin:2rem auto;">
  <div class="tokens-title">Włącz 2FA</div>

  <p class="text-muted" style="font-size:0.8rem; margin-bottom:1rem;">
    Zeskanuj kod QR w aplikacji (Google Authenticator, Authy) i wpisz wygenerowany kod, aby potwierdzić.
  </p>

  <div style="text-align:center; margin-bottom:1rem;">
    <img src="{{ qr_data_uri }}" alt="QR kod TOTP" style="width:220px; height:220px; border:1px solid var(--border); border-radius:var(--radius-sm);">
  </div>

  <p class="text-dim" style="font-size:0.7rem; word-break:break-all; margin-bottom:1rem;">
    Sekret ręczny: {{ secret }}
  </p>

  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">
      {% for error in form.non_field_errors %}{{ error }}{% endfor %}
    </div>
    {% endif %}
    <div class="cf-row">
      <span class="cf-label">Kod z aplikacji</span>
      <div class="cf-input-row">{{ form.code }}</div>
      {% if form.code.errors %}<span class="cf-error">{{ form.code.errors|join:", " }}</span>{% endif %}
    </div>
    <div class="profile-save">
      <button type="submit" class="btn">Potwierdź i włącz</button>
    </div>
  </form>
</div>

{% endblock %}
```

#### Step 5: Przepisz `accounts/totp_recovery_codes.html`

```html
{% extends "base.html" %}
{% block title %}KODY ZAPASOWE — TMASK-TRANSPORTER{% endblock %}
{% block content %}

<div class="tokens-panel" style="max-width:480px; margin:2rem auto;">
  <div class="tokens-title">Kody zapasowe</div>

  <p class="text-muted" style="font-size:0.8rem; margin-bottom:1rem;">
    2FA włączone. Zapisz te kody offline — każdy działa jednorazowo, gdy stracisz dostęp do aplikacji TOTP. Ta strona pokaże je tylko raz.
  </p>

  <div style="font-family:var(--font-mono); font-size:0.95rem; letter-spacing:0.05em; line-height:2; text-align:center; background:var(--bg); border:1px solid var(--border); border-radius:var(--radius-sm); padding:1rem; margin-bottom:1rem;">
    {% for code in codes %}
    <div>{{ code }}</div>
    {% endfor %}
  </div>

  <div class="profile-save">
    <a href="{% url 'accounts:profile' %}" class="btn">Zapisałem — wróć do profilu</a>
  </div>
</div>

{% endblock %}
```

#### Step 6: Przepisz `accounts/profile.html`

Zastąp **całą** treść pliku (usuwa `<style>` blok z linii 6-232, przenosi go do `crt.css` w Step 1 powyżej; reszta to zamiana `.channel-title`/`div` floating-label na uproszczony flex header, zamiana etykiet przycisków, usunięcie zbędnych inline `style=`):

```html
{% extends "base.html" %}
{% block title %}PROFIL — TMASK-TRANSPORTER{% endblock %}
{% block content %}
{% load static %}

{# ── Header ──────────────────────────────────────── #}
<div class="profile-header">
  <div class="ph-field">
    <span class="ph-label">Użytkownik</span>
    <span class="ph-value">{{ user.username|upper }}</span>
  </div>
  <div class="ph-field">
    <span class="ph-label">Rola</span>
    <span class="ph-value">{{ user.role|upper }}</span>
  </div>
  <div class="ph-field">
    <span class="ph-label">Email</span>
    <span class="ph-value small">
      {% if user.email %}{{ user.email }}{% else %}<span class="text-dim">—</span>{% endif %}
    </span>
  </div>
</div>

{# ── Grid ────────────────────────────────────────── #}
<div class="profile-grid">

  {# ── Lewa kolumna: kanały powiadomień ─────────── #}
  <div>
    <form method="post">
      {% csrf_token %}

      {# EMAIL #}
      <div class="channel-card">
        <div class="channel-title">
          <span class="status-dot {% if user.email %}active{% else %}inactive{% endif %}"></span>
          <span>Email</span>
        </div>
        <div class="cf-row">
          <span class="cf-label">Adres email</span>
          <div class="cf-input-row">{{ form.email }}</div>
          {% if form.email.errors %}<span class="cf-error">{{ form.email.errors|join:", " }}</span>{% endif %}
        </div>
        <div class="cb-group">
          <div class="cb-row">
            {{ form.notify_on_failed }}
            <label for="{{ form.notify_on_failed.id_for_label }}">{{ form.notify_on_failed.label }}</label>
          </div>
          <div class="cb-row">
            {{ form.notify_on_done }}
            <label for="{{ form.notify_on_done.id_for_label }}">{{ form.notify_on_done.label }}</label>
          </div>
        </div>
        {% if not user.email %}
        <div class="cf-status">Brak adresu email — powiadomienia nieaktywne</div>
        {% endif %}
      </div>

      {# SLACK WEBHOOK #}
      <div class="channel-card">
        <div class="channel-title">
          <span class="status-dot {% if user.webhook_url %}active{% else %}inactive{% endif %}"></span>
          <span>Slack / Webhook</span>
        </div>
        <div class="cf-row">
          <span class="cf-label">Webhook URL</span>
          <div class="cf-input-row">
            {{ form.webhook_url }}
            <button type="button" class="btn btn-small"
                    hx-post="{% url 'accounts:test_webhook' %}"
                    hx-include="#id_webhook_url"
                    hx-target="#webhook-test-result"
                    hx-swap="innerHTML">Test</button>
          </div>
          {% if form.webhook_url.errors %}<span class="cf-error">{{ form.webhook_url.errors|join:", " }}</span>{% endif %}
          <div id="webhook-test-result"></div>
        </div>
        <div class="cb-group">
          <div class="cb-row">
            {{ form.webhook_on_failed }}
            <label for="{{ form.webhook_on_failed.id_for_label }}">{{ form.webhook_on_failed.label }}</label>
          </div>
          <div class="cb-row">
            {{ form.webhook_on_done }}
            <label for="{{ form.webhook_on_done.id_for_label }}">{{ form.webhook_on_done.label }}</label>
          </div>
        </div>
        {% if user.webhook_url %}
        <div class="cf-status">Aktywny — <span class="active-val">{{ user.webhook_url|truncatechars:45 }}</span></div>
        {% endif %}
        <div class="cf-status"><a href="{% url 'webhook_deliveries:list' %}">Historia dostarczeń</a></div>
      </div>

      {# TELEGRAM #}
      <div class="channel-card">
        <div class="channel-title">
          <span class="status-dot {% if user.telegram_chat_id %}active{% else %}inactive{% endif %}"></span>
          <span>Telegram</span>
        </div>
        <div class="cf-row">
          <span class="cf-label">Chat ID</span>
          <div class="cf-input-row">{{ form.telegram_chat_id }}</div>
          {% if form.telegram_chat_id.errors %}<span class="cf-error">{{ form.telegram_chat_id.errors|join:", " }}</span>{% endif %}
        </div>
        <div class="cb-group">
          <div class="cb-row">
            {{ form.telegram_on_failed }}
            <label for="{{ form.telegram_on_failed.id_for_label }}">{{ form.telegram_on_failed.label }}</label>
          </div>
          <div class="cb-row">
            {{ form.telegram_on_done }}
            <label for="{{ form.telegram_on_done.id_for_label }}">{{ form.telegram_on_done.label }}</label>
          </div>
        </div>
        {% if user.telegram_chat_id %}
        <div class="cf-status">Aktywny — chat_id: <span class="active-val">{{ user.telegram_chat_id }}</span></div>
        {% endif %}
      </div>

      <div class="profile-save">
        <button type="submit" class="btn">Zapisz ustawienia</button>
      </div>
    </form>
  </div>

  {# ── 2FA ─────────────────────────────────────── #}
  <div class="tokens-panel" style="margin-bottom:1.5rem;">
    <div class="tokens-title">2FA — Weryfikacja dwuskładnikowa</div>
    {% if user.totp_enabled %}
    <div class="cf-status no-border">
      <span class="status-dot active" style="margin-right:0.4rem;"></span>
      <span class="active-val">Włączone</span>
    </div>
    <form method="post" action="{% url 'accounts:2fa_disable' %}" style="margin-top:0.85rem;">
      {% csrf_token %}
      <div class="cf-row">
        <span class="cf-label">Hasło (potwierdź wyłączenie)</span>
        <div class="cf-input-row">{{ totp_disable_form.password }}</div>
      </div>
      <button type="submit" class="btn btn-danger" style="margin-top:0.5rem;">Wyłącz 2FA</button>
    </form>
    {% else %}
    <div class="cf-status no-border">
      <span class="status-dot inactive" style="margin-right:0.4rem;"></span>
      <span>Wyłączone</span>
    </div>
    <a href="{% url 'accounts:2fa_setup' %}" class="btn" style="margin-top:0.85rem; display:inline-block;">Włącz 2FA</a>
    {% endif %}
  </div>

  {# ── Prawa kolumna: API Tokens ─────────────────── #}
  <div class="tokens-panel">
    <div class="tokens-title">API Tokens</div>

    {% if api_tokens %}
    <table class="tokens-table">
      <thead>
        <tr>
          <th>Etykieta</th>
          <th>Utworzony</th>
          <th>Użyty</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for token in api_tokens %}
        <tr>
          <td class="token-label">{{ token.label }}</td>
          <td class="token-date">{{ token.created_at|date:"Y-m-d" }}</td>
          <td class="token-date">{{ token.last_used_at|date:"Y-m-d"|default:"—" }}</td>
          <td style="text-align:right;">
            <form method="post" action="{% url 'accounts:revoke_api_token' token.pk %}"
                  data-confirm="Usunąć token {{ token.label }}?">
              {% csrf_token %}
              <button type="submit" class="btn btn-danger btn-small">Revoke</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="no-tokens">Brak tokenów API</div>
    {% endif %}

    {% if api_tokens.count < 5 %}
    <form method="post" action="{% url 'accounts:generate_api_token' %}">
      {% csrf_token %}
      <div class="token-gen-row">
        <input type="text" id="api-token-label" name="label"
               maxlength="100" placeholder="etykieta tokenu" required>
        <button type="submit" class="btn btn-small">Gen</button>
      </div>
    </form>
    {% else %}
    <div class="cf-status" style="margin-top:0.5rem;">Limit 5 tokenów — usuń aby dodać nowy</div>
    {% endif %}
  </div>

</div>

{# ── Backup / Restore ─────────────────────────────── #}
<div class="backup-section">
  <div class="backup-section-title">Backup / Restore</div>
  <div class="backup-grid">

    <div class="channel-card">
      <div class="channel-title"><span>Eksport</span></div>
      <p class="backup-desc">Pobiera całą konfigurację (połączenia + flows) do pliku JSON na Twój komputer. Sekrety szyfrowane hasłem — zapamiętaj je.</p>
      <form method="post" action="{% url 'connections:export' %}" class="backup-vform">
        {% csrf_token %}
        <div class="cf-row">
          <span class="cf-label">Hasło szyfrowania</span>
          <div class="cf-input-row">
            <input type="password" name="passphrase" required autocomplete="off">
          </div>
        </div>
        <button type="submit" class="btn">Export</button>
      </form>
    </div>

    <div class="channel-card">
      <div class="channel-title"><span>Import</span></div>
      <p class="backup-desc">Wczytuje połączenia i flows z pliku z Twojego komputera. Istniejące (po nazwie) są pomijane — nic nie nadpisuje.</p>
      <form method="post" action="{% url 'connections:import' %}" enctype="multipart/form-data" class="backup-vform">
        {% csrf_token %}
        <div class="cf-row">
          <span class="cf-label">Plik konfiguracji</span>
          <div class="field-with-btn">
            <input type="text" class="file-name" readonly placeholder="nie wybrano pliku" id="import-file-name">
            <label for="import-file" class="btn btn-small">Wybierz</label>
            <input type="file" id="import-file" name="file" accept="application/json,.json"
                   class="file-hidden" data-file-display="import-file-name">
          </div>
        </div>
        <div class="cf-row">
          <span class="cf-label">Hasło z eksportu</span>
          <div class="cf-input-row">
            <input type="password" name="passphrase" required autocomplete="off">
          </div>
        </div>
        <button type="submit" class="btn">Import</button>
      </form>
    </div>

  </div>
</div>

{# ── New token modal ──────────────────────────────── #}
{% if new_token %}
<div id="token-modal" class="token-modal-overlay">
  <div class="token-modal">
    <div class="tokens-title">Nowy token API</div>
    <div class="token-warn">
      Zapisz ten klucz — nie zostanie pokazany ponownie
    </div>
    <div class="token-value-box">
      <code id="new-token-value">{{ new_token }}</code>
    </div>
    <div class="token-actions">
      <button type="button" class="btn" id="copy-token-btn">Copy</button>
      <button type="button" class="btn" id="close-token-modal">Zamknij</button>
    </div>
  </div>
</div>
<script src="{% static 'js/profile.js' %}"></script>
{% endif %}

{% endblock %}
```

**Weryfikacja przed commitem:** sprawdź `services/web/static/js/profile.js` (17 linii) — czy referuje `#token-modal` przez id (tak, `id="token-modal"` zachowany bez zmian) i czy nie referuje klasy `.channel-title`/floating-label pozycjonowania przez JS (nie referuje — plik obsługuje tylko copy-to-clipboard i zamykanie modala przez id, sprawdzone w eksploracji wcześniej).

#### Step 7: Przepisz `users/list.html`

```html
{% extends "base.html" %}
{% block title %}USERS — ADMIN{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">{{ organization.name|upper }} — Członkowie</span>
  <div class="toolbar">
    <a href="{% url 'organization:settings' %}" class="btn btn-small">Edytuj nazwę organizacji</a>
    <a href="{% url 'accounts:user_create' %}" class="btn">+ Dodaj usera</a>
  </div>
  <table>
    <thead>
      <tr><th>Username</th><th>Role</th><th>Email</th><th>Last Login</th><th>Active</th><th>Actions</th></tr>
    </thead>
    <tbody>
      {% for u in users %}
      <tr>
        <td>{{ u.username }}</td>
        <td><span class="{% if u.is_admin %}text-warn{% else %}text-muted{% endif %}">{{ u.role|upper }}</span></td>
        <td>{{ u.email|default:"—" }}</td>
        <td>{{ u.last_login|date:"Y-m-d H:i"|default:"NEVER" }}</td>
        <td>{% if u.is_active %}<span class="glow">● Yes</span>{% else %}<span style="color:var(--danger);">○ No</span>{% endif %}</td>
        <td>
          <form method="post" action="{% url 'accounts:change_user_role' u.pk %}" class="inline-form">
            {% csrf_token %}
            <select name="role">
              {% for value, label in role_choices %}
              <option value="{{ value }}" {% if u.role == value %}selected{% endif %}>{{ label }}</option>
              {% endfor %}
            </select>
            <button type="submit" class="btn btn-small">Zapisz</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

Dodaj brakującą klasę `.text-warn` do `crt.css` (w sekcji `PROFILE / 2FA` z Step 1, na końcu): `.text-warn { color: var(--warn); }` — potrzebna tutaj bo oryginał używał `style="color:{% if u.is_admin %}var(--amber){% else %}var(--green){% endif %}"` inline, warto mieć obie jako klasy (`.text-warn` i istniejące `.text-muted`) zamiast inline conditional style.

#### Step 8: Przepisz `users/create.html`

```html
{% extends "base.html" %}
{% block title %}NOWY USER — ADMIN{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Nowy użytkownik</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}{{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    {% for field in form %}
    <div class="field">
      <label>{{ field.label }}</label>
      {{ field }}
      {% if field.help_text %}<div class="field-hint">{{ field.help_text }}</div>{% endif %}
      {% if field.errors %}<div class="field-error">{{ field.errors }}</div>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn">Utwórz</button>
  </form>
</div>
{% endblock %}
```

#### Step 9: Testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/accounts/ apps/organization/ -q
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: brak regresji, pełny suite `541 passed`. Jeśli którykolwiek test w `apps/accounts/tests/` asercjuje `assertContains(response, "[ LOGIN ]")` lub podobny stary tekst — zaktualizuj asercję na nowy tekst zgodnie z tabelą zamian w tym tasku (Global Constraints potwierdziły wcześniej że taki test nie istnieje, ale sprawdź ponownie po zmianie, na wypadek testu dodanego po dacie tej analizy).

#### Step 10: Manualna weryfikacja

```bash
docker compose up -d --build
```

Sprawdź: `/accounts/login/` (bez ASCII-art, panel logowania wyśrodkowany), `/accounts/profile/` (3 karty kanałów, karta 2FA, karta API tokens, sekcja backup/restore — wszystko jako karty z radius, status-dot pulsuje dla aktywnych kanałów), `/accounts/2fa/setup/` (QR kod w karcie), `/users/` (tabela z akcjami).

#### Step 11: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/accounts/ services/web/templates/users/ services/web/static/css/crt.css
git commit -m "feat(ui): accounts + users na nowym design systemie (task 4/9)"
```

---

### Task 5: Connections

**Files:**
- Modify: `services/web/templates/connections/list.html` (całość, 55 linii)
- Modify: `services/web/templates/connections/form.html` (całość, 93 linie)
- Modify: `services/web/templates/connections/_field.html` (całość, 7 linii)
- Modify: `services/web/templates/connections/browser_fragment.html` (całość, 31 linii)
- No change: `services/web/templates/connections/_test_result.html` (już używa `.test-ok`/`.test-fail`)
- No change: `services/web/templates/connections/_db_tables_options.html` (czysty `<select>`, brak CSS klas do zmiany)

**Interfaces:**
- Consumes: `.panel`, `.panel-nested`, `.panel-title`, `.toolbar`, `.row-actions`, `.col-actions`, `.btn`/`.btn-small`/`.btn-warn`/`.btn-danger`, `.field`, `.field-error`, `.field-grid`, `.field-hint`, `.test-result`, `.msg-error`, `.breadcrumbs`, `.file-list`, `.text-muted` z Task 1/2.
- **Zachowaj bez zmian**: klasy `.ssh-only-field`, `.db-kind-field`, `.db-kind-field` (JS-dependent, patrz Global Constraints), wszystkie `id="known-host-section"`, `id="scan-btn"`, `data-scan-url`, `data-browse-*` atrybuty.

#### Step 1: Przepisz `connections/list.html`

```html
{% extends "base.html" %}
{% block title %}CONNECTIONS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Connections</span>
  <div class="toolbar">
    {% if user.is_admin %}
    <a href="{% url 'connections:create' %}" class="btn">+ New Connection</a>
    {% endif %}
  </div>
  {% if connections %}
  <table>
    <thead>
      <tr>
        <th>Name</th><th>Kind</th><th>Host</th><th>Port</th><th>Proto</th>
        <th>Compress</th><th>Encrypt</th><th>Utworzył</th><th class="col-actions">Actions</th>
      </tr>
    </thead>
    <tbody>
      {% for conn in connections %}
      <tr>
        <td>{{ conn.name }}</td>
        <td>{{ conn.kind|upper }}</td>
        <td>{{ conn.host }}</td>
        <td>{{ conn.port }}</td>
        <td>{{ conn.protocol|upper }}</td>
        <td>{% if conn.compress %}Yes{% else %}—{% endif %}</td>
        <td>{% if conn.encrypt %}Yes{% else %}—{% endif %}</td>
        <td>{{ conn.owner.username }}</td>
        <td class="col-actions">
          <div class="row-actions">
            <button class="btn btn-small btn-warn"
              hx-get="{% url 'connections:test' conn.pk %}"
              hx-target="#test-result-{{ conn.pk }}"
              hx-swap="innerHTML">Test</button>
            {% if user.is_admin %}
            <a href="{% url 'connections:edit' conn.pk %}" class="btn btn-small">Edit</a>
            <form method="post" action="{% url 'connections:delete' conn.pk %}" class="inline-form"
              data-confirm="DELETE {{ conn.name }}?">
              {% csrf_token %}
              <button type="submit" class="btn btn-small btn-danger">Del</button>
            </form>
            {% endif %}
            <span id="test-result-{{ conn.pk }}" class="test-result"></span>
          </div>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">No connections configured — add one above</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 2: Przepisz `connections/_field.html`

```html
<div class="field">
  <label>{{ field.label }}</label>
  {{ field }}
  {% if field.errors %}
  <div class="field-error">{% for e in field.errors %}{{ e }}{% endfor %}</div>
  {% endif %}
</div>
```

#### Step 3: Przepisz `connections/form.html`

```html
{% extends "base.html" %}
{% load static %}
{% block title %}{{ action }} CONNECTION{% endblock %}
{% block content %}
<div class="panel" style="max-width:700px;">
  <span class="panel-title">{{ action }} Connection</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">{% for e in form.non_field_errors %}{{ e }}{% endfor %}</div>
    {% endif %}

    <div class="panel-nested">
      <span class="panel-title">Podstawowe</span>
      {% include "connections/_field.html" with field=form.name %}
      {% include "connections/_field.html" with field=form.kind %}
    </div>

    <div class="panel-nested">
      <span class="panel-title">Połączenie</span>
      <div class="field-grid">
        {% include "connections/_field.html" with field=form.host %}
        {% include "connections/_field.html" with field=form.port %}
      </div>
      <div class="field-grid">
        {% include "connections/_field.html" with field=form.username %}
        {% include "connections/_field.html" with field=form.password %}
      </div>
    </div>

    <div class="panel-nested db-kind-field">
      <span class="panel-title">Database</span>
      {% include "connections/_field.html" with field=form.db_name %}
    </div>

    <div class="panel-nested ssh-only-field">
      <span class="panel-title">SSH</span>
      <div class="field-grid">
        {% include "connections/_field.html" with field=form.protocol %}
        {% include "connections/_field.html" with field=form.compress %}
      </div>
      <div class="field-grid">
        {% include "connections/_field.html" with field=form.encrypt %}
        {% include "connections/_field.html" with field=form.strict_host_key_checking %}
      </div>
      {% include "connections/_field.html" with field=form.ssh_key %}
      {% include "connections/_field.html" with field=form.ssh_key_passphrase %}
      <div class="field" id="known-host-section" style="display:none">
        <label>{{ form.known_host_key.label }}</label>
        {{ form.known_host_key }}
        {% if conn %}
        <div style="margin-top:0.4rem;">
          <button type="button" class="btn btn-warn btn-small" id="scan-btn"
                  data-scan-url="{% url 'connections:scan_hostkey' conn.pk %}">Scan Host Key</button>
          <span id="scan-result" style="font-size:0.8rem; margin-left:0.5rem;"></span>
        </div>
        {% endif %}
        {% if form.known_host_key.errors %}
        <div class="field-error">{% for e in form.known_host_key.errors %}{{ e }}{% endfor %}</div>
        {% endif %}
      </div>
    </div>

    <div class="panel-nested">
      <span class="panel-title">Zaawansowane</span>
      <div class="field-grid">
        <div class="field ssh-only-field">
          <label>{{ form.dry_run_before_transfer.label }}</label>
          {{ form.dry_run_before_transfer }}
          <span class="field-hint">Sprawdza listę plików bez kopiowania. Transfer anulowany jeśli dry-run zakończy się błędem.</span>
          {% if form.dry_run_before_transfer.errors %}
          <div class="field-error">{% for e in form.dry_run_before_transfer.errors %}{{ e }}{% endfor %}</div>
          {% endif %}
        </div>
        <div class="field ssh-only-field">
          <label>{{ form.verify_checksum.label }}</label>
          {{ form.verify_checksum }}
          <span class="field-hint">Wymaga sha256sum na zdalnym hoście. Ignorowane gdy GPG włączone.</span>
          {% if form.verify_checksum.errors %}
          <div class="field-error">{% for e in form.verify_checksum.errors %}{{ e }}{% endfor %}</div>
          {% endif %}
        </div>
      </div>
    </div>

    <div class="form-actions">
      <button type="submit" class="btn">Save</button>
      <a href="{% url 'connections:list' %}" class="btn btn-danger">Cancel</a>
    </div>
  </form>
</div>
<script src="{% static 'js/connections_form.js' %}"></script>
{% endblock %}
```

**Uwaga krytyczna:** `class="box box-nested"` → `class="panel-nested"` (nie `panel panel-nested`! `.panel-nested` w Task 1 już definiuje własne tło/border/radius, nie jest zagnieżdżony wewnątrz `.panel` wizualnie tak jak stary `.box-nested` był wewnątrz `.box` z tym samym obramowaniem — sprawdź w przeglądarce że zagnieżdżone sekcje (Podstawowe/Połączenie/Database/SSH/Zaawansowane) są nadal czytelnie oddzielone od zewnętrznego panelu formularza).

#### Step 4: Przepisz `connections/browser_fragment.html`

```html
{% if error %}
<p class="msg-error">{{ error }}</p>
{% else %}
<div class="breadcrumbs">
  {% for crumb in breadcrumbs %}<a href="#"
    data-browse-open
    data-browse-field="{{ field_id }}"
    data-browse-conn="{{ conn_pk }}"
    data-browse-path="{{ crumb.path }}">{{ crumb.label }}</a>{% if not forloop.last %} / {% endif %}{% endfor %}
</div>
<div class="browse-actions">
  <a href="#" class="btn btn-small" data-browse-select="{{ current_path }}">Użyj tego katalogu: {{ current_path }}</a>
</div>
<ul class="file-list">
  {% for entry in entries %}
  <li>
    {% if entry.is_dir %}
    <a href="#"
      data-browse-open
      data-browse-field="{{ field_id }}"
      data-browse-conn="{{ conn_pk }}"
      data-browse-path="{{ entry.full_path }}">{{ entry.name }}</a>
    {% else %}
    <a href="#" data-browse-select="{{ entry.full_path }}">{{ entry.name }}</a>
    {% endif %}
  </li>
  {% empty %}
  <li class="text-dim">(pusty katalog)</li>
  {% endfor %}
</ul>
{% endif %}
```

Zmiana: `[DIR] {{ entry.name }}` → `{{ entry.name }}` (prefiks `[DIR]` usunięty — folder vs plik rozróżniamy teraz kolorem/kontekstem markupu, nie ASCII-prefiksem; jeśli podczas manualnej weryfikacji w Step 6 okaże się to niejasne wizualnie, dodaj SVG folder-icon zamiast tekstowego prefiksu, nie przywracaj `[DIR]`).

#### Step 5: Testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/connections/ -q
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: brak regresji, `541 passed`.

#### Step 6: Manualna weryfikacja

```bash
docker compose up -d --build
```

Sprawdź `/connections/` (tabela + test connection przez HTMX), `/connections/new/` (formularz z zagnieżdżonymi sekcjami — przełącz `KIND` między `ssh`/`postgres`/`mysql`/`mssql` i sprawdź czy `.ssh-only-field`/`.db-kind-field` nadal poprawnie chowają/pokazują sekcje — to jest test regresji dla `connections_form.js`), przycisk `BROWSE` otwiera modal z nowym stylem breadcrumbs/listy plików.

#### Step 7: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/connections/
git commit -m "feat(ui): connections na nowym design systemie (task 5/9)"
```

---

### Task 6: Transfers + Logs

**Files:**
- Modify: `services/web/templates/transfers/create.html` (całość, 87 linii)
- No change: `services/web/templates/transfers/log_fragment.html` (już zgodny z Task 1)
- Modify: `services/web/templates/transfers/_dry_run_result.html` (całość, 16 linii)
- No change: `services/web/templates/transfers/_progress_bar.html` (już zgodny z Task 1)
- Modify: `services/web/templates/logs/list.html` (całość, 50 linii)

**Interfaces:**
- Consumes: `.panel`, `.panel-title`, `.two-col`, `.field`, `.field-with-btn`, `.field-error`, `.status`, `.status-*`, `.log-terminal`, `.log-line`, `.log-info/.log-warn`, `.progress-wrap`, `.msg-ok`, `.msg-error`, `.btn`/`.btn-small`/`.btn-warn`/`.btn-danger`, `.col-actions`, `.row-actions`, `.inline-form`, `.glow`, `.text-muted` z Task 1/2.

#### Step 1: Sprawdź `transfers/_progress_bar.html` — bez zmian

```html
<div id="progress-bar-wrap"{% if oob %} hx-swap-oob="true"{% endif %}>
{% if job.progress_percent is not None %}
  <div class="progress-wrap">
    <div class="progress-bar"><div class="progress-bar-fill" style="width:{{ job.progress_percent }}%"></div></div>
    <span class="progress-label">{{ job.progress_percent }}%</span>
  </div>
{% endif %}
</div>
```

Ten plik już nie zawiera żadnych CRT-specyficznych klas — treść identyczna jak dziś, żadna zmiana pliku nie jest potrzebna (klasy `.progress-wrap`/`.progress-bar`/`.progress-bar-fill`/`.progress-label` są już reskinowane w `crt.css` od Task 1). Pomiń commit tego pliku — nie modyfikuj go.

#### Step 2: `transfers/log_fragment.html` — bez zmian

Treść pliku (`.log-line`, `.log-info`, include `_progress_bar.html`) jest już w pełni zgodna z klasami zdefiniowanymi w Task 1 — identycznie jak `db_transfers/log_fragment.html` w Task 7. Nie modyfikuj tego pliku, pomiń go w commicie.

#### Step 3: Przepisz `transfers/_dry_run_result.html`

```html
{% if state == 'PENDING' or state == 'STARTED' %}
<div id="dry-run-result" class="msg-ok"
  hx-get="{% url 'transfers:dry_run_status' task_id %}"
  hx-trigger="every 2s"
  hx-swap="outerHTML">
  Dry-run w toku...
</div>
{% elif state == 'SUCCESS' and result.exit_code == 0 %}
<div id="dry-run-result" class="msg-ok">Dry-run OK — poniżej co zostanie przesłane:
{{ result.output }}</div>
{% elif state == 'SUCCESS' %}
<div id="dry-run-result" class="msg-error">Dry-run failed (exit {{ result.exit_code }}):
{{ result.output }}</div>
{% else %}
<div id="dry-run-result" class="msg-error">Dry-run błąd — nie udało się wykonać podglądu.</div>
{% endif %}
```

#### Step 4: Przepisz `transfers/create.html`

```html
{% extends "base.html" %}
{% load static %}
{% block title %}TRANSFER — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="two-col">
  <div class="panel">
    <span class="panel-title">New Transfer</span>
    <form method="post" enctype="multipart/form-data">
      {% csrf_token %}
      {% if form.non_field_errors %}
      <div class="msg-error" style="margin-bottom:1rem;">
        {% for error in form.non_field_errors %}{{ error }}<br>{% endfor %}
      </div>
      {% endif %}
      {% for field in form %}
      <div class="field">
        <label>{{ field.label }}</label>
        {% if field.html_name == 'upload' %}
        <div class="field-with-btn">
          <label for="{{ field.auto_id }}" class="btn btn-small">Wybierz</label>
          <input type="text" class="file-name" readonly placeholder="— brak pliku —" id="upload-file-name">
          <div class="file-hidden">{{ field }}</div>
        </div>
        {% elif field.html_name == 'destination_path' %}
        <div class="field-with-btn">
          {{ field }}
          <button type="button" class="btn btn-small"
            data-browse-open
            data-browse-field="{{ field.auto_id }}"
            data-browse-conn-sel="#id_connection">
            Browse
          </button>
        </div>
        {% else %}
        {{ field }}
        {% endif %}
        {% if field.errors %}<div class="field-error">{{ field.errors }}</div>{% endif %}
      </div>
      {% endfor %}
      <button type="submit" class="btn">Execute Transfer</button>
      <button type="submit" formaction="{% url 'transfers:dry_run' %}" class="btn btn-warn" id="dry-run-btn">Dry Run</button>
    </form>
    {% if dry_run_task_id %}
    <div hx-get="{% url 'transfers:dry_run_status' dry_run_task_id %}" hx-trigger="load" hx-swap="outerHTML"></div>
    {% endif %}
  </div>

  {% if job %}
  <div class="panel">
    <span class="panel-title">Transfer Log — #{{ job.pk }}</span>
    <div style="margin-bottom:0.5rem;">
      Status: <span class="status status-{{ job.status }}">{{ job.status|upper }}</span>
      {% if job.status == 'running' or job.status == 'pending' %}
      {% if user.can_operate %}
      <form method="post" action="{% url 'transfers:stop' job.pk %}" class="inline-form"
        data-confirm="Zatrzymać transfer #{{ job.pk }}?">
        {% csrf_token %}
        <button type="submit" class="btn btn-small btn-danger">Stop</button>
      </form>
      {% endif %}
      {% endif %}
    </div>
    {% if job.flow %}
    <div style="margin-bottom:0.5rem;font-size:0.85rem;">
      Type: Relay &nbsp;|&nbsp; Flow: <span class="glow">{{ job.flow.name }}</span><br>
      Src: {{ job.flow.source_conn.name }} — {{ job.source_path }}<br>
      Dst: {{ job.flow.dest_conn.name }} — {{ job.destination_path }}
    </div>
    {% endif %}
    {% include "transfers/_progress_bar.html" %}
    <div
      id="log-output"
      class="log-terminal"
      {% if job.status == 'running' or job.status == 'pending' %}
        hx-get="{% url 'transfers:log_fragment' job.pk %}"
        hx-trigger="every 2s"
        hx-swap="innerHTML"
      {% endif %}
    >
      {% include "transfers/log_fragment.html" with logs=job.logs.all %}
    </div>
  </div>
  {% endif %}
</div>
{{ connection_protocols|json_script:"connection-protocols" }}
<script src="{% static 'js/transfers_create.js' %}"></script>
{% endblock %}
```

`style="display:grid; grid-template-columns:1fr 1fr; gap:2rem;"` → `.two-col` (Task 1's `.two-col` używa `gap:1.5rem` nie `2rem` — akceptowalna drobna różnica, spójność z resztą layoutu ważniejsza niż dokładne zachowanie 2rem tutaj; jeśli podczas weryfikacji wizualnej różnica rzuca się w oczy negatywnie, można nadpisać punktowo `style="gap:2rem"` obok `class="two-col"` zamiast zmieniać globalny token).

#### Step 5: Przepisz `logs/list.html`

```html
{% extends "base.html" %}
{% block title %}LOGS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Transfer History</span>
  {% if jobs %}
  <table>
    <thead>
      <tr>
        <th>#</th><th>Type</th><th>Source</th><th>Dest</th>
        <th>Status</th><th>Started</th><th>Finished</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {% for job in jobs %}
      <tr>
        <td>{{ job.pk }}</td>
        <td>
          {% if job.flow %}
            Relay: {{ job.flow.name }}
          {% else %}
            {{ job.connection.name }}
          {% endif %}
        </td>
        <td>{{ job.source_path }}</td>
        <td>{{ job.destination_path }}</td>
        <td><span class="status status-{{ job.status }}">{{ job.status|upper }}</span></td>
        <td>{{ job.started_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{{ job.finished_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td class="col-actions">
          <div class="row-actions">
            <a href="{% url 'transfers:detail' job.pk %}" class="btn btn-small">View</a>
            {% if user.is_admin %}
            <form method="post" action="{% url 'transfers:delete' job.pk %}" class="inline-form"
              data-confirm="DELETE transfer #{{ job.pk }}?">
              {% csrf_token %}
              <button type="submit" class="btn btn-small btn-danger">Del</button>
            </form>
            {% endif %}
          </div>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">No transfer history</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 6: Testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/transfers/ -q
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: brak regresji, `541 passed`.

#### Step 7: Manualna weryfikacja

```bash
docker compose up -d --build
```

Uruchom transfer testowy (SFTP/rsync na dowolnym skonfigurowanym połączeniu) — sprawdź: live log w `.log-terminal` (JetBrains Mono, ciemniejsze tło niż karta wokół), progress bar animuje się płynnie, status pill pulsuje przy `running`, dry-run pokazuje wynik w panelu.

#### Step 8: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/transfers/ services/web/templates/logs/
git commit -m "feat(ui): transfers + logs na nowym design systemie (task 6/9)"
```

---

### Task 7: DB Transfers

**Files:**
- Modify: `services/web/templates/db_transfers/list.html` (całość, 50 linii)
- Modify: `services/web/templates/db_transfers/create.html` (całość, 41 linii)
- Modify: `services/web/templates/db_transfers/detail.html` (całość, 35 linii)
- No change: `services/web/templates/db_transfers/log_fragment.html` (identyczna struktura jak `transfers/log_fragment.html` bez progress bar include — już zgodne z klasami z Task 1, zero zmian potrzebnych: `.log-line log-{{ log.level }}` i `still_running` blok są identyczne z tym co już istnieje w `crt.css`)

**Interfaces:**
- Consumes: `.panel`, `.panel-title`, `.toolbar`, `.col-actions`, `.row-actions`, `.status`, `.status-*`, `.log-terminal`, `.btn`/`.btn-small`/`.btn-danger`, `.field`, `.field-error`, `.inline-form`, `.glow`, `.text-muted` z Task 1.

#### Step 1: Przepisz `db_transfers/list.html`

```html
{% extends "base.html" %}
{% block title %}DB TRANSFERS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">DB Transfers</span>
  <div class="toolbar">
    {% if user.can_operate %}
    <a href="{% url 'db_transfers:create' %}" class="btn">+ New DB Transfer</a>
    {% endif %}
  </div>
  {% if jobs %}
  <table>
    <thead>
      <tr>
        <th>#</th><th>Engine</th><th>Source</th><th>Dest</th><th>Scope</th>
        <th>Status</th><th>Started</th><th>Finished</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {% for job in jobs %}
      <tr>
        <td>{{ job.pk }}</td>
        <td><span class="status">{{ job.engine|upper }}</span></td>
        <td>{{ job.source_connection.name }}</td>
        <td>{{ job.dest_connection.name }}</td>
        <td>{% if job.table_name %}{{ job.table_name }}{% else %}Cała baza{% endif %}</td>
        <td><span class="status status-{{ job.status }}">{{ job.status|upper }}</span></td>
        <td>{{ job.started_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{{ job.finished_at|date:"Y-m-d H:i"|default:"—" }}</td>
        <td class="col-actions">
          <div class="row-actions">
            <a href="{% url 'db_transfers:detail' job.pk %}" class="btn btn-small">View</a>
            {% if user.is_admin %}
            <form method="post" action="{% url 'db_transfers:delete' job.pk %}" class="inline-form"
              data-confirm="DELETE transfer #{{ job.pk }}?">
              {% csrf_token %}
              <button type="submit" class="btn btn-small btn-danger">Del</button>
            </form>
            {% endif %}
          </div>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">No DB transfers yet</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 2: Przepisz `db_transfers/create.html`

```html
{% extends "base.html" %}
{% load static %}
{% block title %}NEW DB TRANSFER — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel" style="max-width:600px;">
  <span class="panel-title">New DB Transfer</span>
  <form method="post" id="db-transfer-form" data-db-tables-url="{% url 'connections:db_tables' %}">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}{{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    {% for field in form %}
    {% if field.name == 'engine' %}
    <div class="field">
      <label>{{ field.label }}</label>
      {{ field }}
      {% if field.errors %}<div class="field-error">{{ field.errors }}</div>{% endif %}
    </div>
    {% elif field.name == 'table_name' %}
    <div class="field">
      <label>{{ field.label }}</label>
      <select id="id_table_name" name="table_name">
        <option value="">— wybierz najpierw SOURCE CONNECTION —</option>
      </select>
      {% if field.errors %}<div class="field-error">{{ field.errors }}</div>{% endif %}
    </div>
    {% else %}
    <div class="field">
      <label>{{ field.label }}</label>
      {{ field }}
      {% if field.errors %}<div class="field-error">{{ field.errors }}</div>{% endif %}
    </div>
    {% endif %}
    {% endfor %}
    <button type="submit" class="btn" id="execute-btn">Execute Transfer</button>
  </form>
</div>
<script src="{% static 'js/db_transfers_create.js' %}"></script>
{% endblock %}
```

#### Step 3: Przepisz `db_transfers/detail.html`

```html
{% extends "base.html" %}
{% block title %}DB TRANSFER #{{ job.pk }} — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">DB Transfer Log — #{{ job.pk }}</span>
  <div style="margin-bottom:0.5rem;">
    Status: <span class="status status-{{ job.status }}">{{ job.status|upper }}</span>
    {% if job.status == 'running' or job.status == 'pending' %}
    {% if user.can_operate %}
    <form method="post" action="{% url 'db_transfers:stop' job.pk %}" class="inline-form"
      data-confirm="Zatrzymać transfer #{{ job.pk }}?">
      {% csrf_token %}
      <button type="submit" class="btn btn-small btn-danger">Stop</button>
    </form>
    {% endif %}
    {% endif %}
  </div>
  <div style="margin-bottom:0.5rem;font-size:0.85rem;">
    Source: <span class="glow">{{ job.source_connection.name }}</span> ({{ job.source_connection.db_name }})<br>
    Dest: <span class="glow">{{ job.dest_connection.name }}</span> ({{ job.dest_connection.db_name }})<br>
    Scope: {% if job.table_name %}Table — {{ job.table_name }}{% else %}Cała baza{% endif %}
  </div>
  <div
    id="log-output"
    class="log-terminal"
    {% if job.status == 'running' or job.status == 'pending' %}
      hx-get="{% url 'db_transfers:log_fragment' job.pk %}"
      hx-trigger="every 2s"
      hx-swap="innerHTML"
    {% endif %}
  >
    {% include "db_transfers/log_fragment.html" with logs=job.logs.all %}
  </div>
</div>
{% endblock %}
```

#### Step 4: Testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/db_transfers/ -q
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: brak regresji, `541 passed`.

#### Step 5: Manualna weryfikacja

```bash
docker compose up -d --build
```

Sprawdź `/db-transfers/` (tabela z kolumną ENGINE), `/db-transfers/new/` (wybór silnika przełącza listę połączeń — regresja dla `db_transfers_create.js`), `/db-transfers/<id>/` (live log identyczny wizualnie z transfers).

#### Step 6: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/db_transfers/
git commit -m "feat(ui): db_transfers na nowym design systemie (task 7/9)"
```

---

### Task 8: Flows + Scheduler

**Files:**
- Modify: `services/web/templates/flows/list.html` (całość, 51 linii)
- Modify: `services/web/templates/flows/form.html` (całość, 78 linii)
- Modify: `services/web/templates/scheduler/list.html` (całość, 47 linii)
- Modify: `services/web/templates/scheduler/form.html` (całość, 242 linie — `<style>` blok usunięty, CSS przeniesione)
- Modify: `services/web/static/css/crt.css` (dopisz sekcję `SCHEDULER` na końcu)

**Interfaces:**
- Consumes: `.panel`, `.panel-title`, `.field`, `.field-error`, `.field-hint`, `.two-col`, `.status`, `.btn`/`.btn-warn`/`.btn-danger`, `.inline-form`, `.form-actions`, `.text-muted`, `.glow` z Task 1.
- **Zachowaj bez zmian**: `.cron-ex` (JS-dependent, `scheduler_form.js:4`), `id="sched-form"`.

#### Step 1: Dopisz sekcję Scheduler do `crt.css`

Na końcu `services/web/static/css/crt.css` dopisz (przeniesienie `<style>` z `scheduler/form.html:6-147` na nowe tokeny):

```css
/* ============================================================
   SCHEDULER
   ============================================================ */
.sched-wrap { max-width: 660px; }

.sched-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.sched-card-title {
  font-size: var(--font-size-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  text-transform: uppercase;
  margin-bottom: 1rem;
}

.sf-row { margin-bottom: 1rem; }
.sf-row:last-child { margin-bottom: 0; }

.sf-label {
  font-size: var(--font-size-xs);
  color: var(--text-muted);
  margin-bottom: 0.3rem;
  display: block;
}

.flow-info {
  margin-top: 0.6rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg);
  font-size: var(--font-size-xs);
  color: var(--text-dim);
}
.flow-info .fi-arrow { color: var(--warn); margin: 0 0.4rem; }

.cron-panel {
  margin-top: 0.75rem;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 0.75rem 1rem;
  background: var(--bg);
}

.cron-panel-title {
  font-size: var(--font-size-xs);
  color: var(--text-dim);
  margin-bottom: 0.6rem;
}

.cron-examples { display: grid; grid-template-columns: 1fr 1fr; gap: 0.25rem 1.5rem; }

.cron-ex { display: flex; gap: 0.75rem; align-items: baseline; cursor: pointer; padding: 0.15rem 0; }
.cron-ex:hover .cron-ex-val { color: var(--accent); }
.cron-ex:hover .cron-ex-desc { color: var(--text); }

.cron-ex-val {
  color: var(--warn);
  font-family: var(--font-mono);
  font-size: var(--font-size-xs);
  white-space: nowrap;
  flex-shrink: 0;
  min-width: 110px;
}

.cron-ex-desc { color: var(--text-dim); font-size: var(--font-size-xs); }

.enabled-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-subtle);
}
.enabled-row input[type="checkbox"] { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; flex-shrink: 0; }
.enabled-row label { font-size: var(--font-size-sm); color: var(--text-muted); cursor: pointer; margin: 0; }

.sf-error { color: var(--danger); font-size: var(--font-size-xs); margin-top: 0.25rem; display: block; }

.sched-actions { display: flex; gap: 1rem; padding-top: 0.25rem; }

.sched-breadcrumb {
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
  padding-bottom: 0.75rem;
  font-size: var(--font-size-xs);
  color: var(--text-dim);
}
.sched-breadcrumb .current { color: var(--accent); font-weight: 600; }
```

#### Step 2: Przepisz `flows/list.html`

```html
{% extends "base.html" %}
{% block title %}FLOWS — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Relay Flows</span>
  <div style="margin-bottom:1rem;">
    {% if user.is_admin %}
    <a href="{% url 'flows:create' %}" class="btn">+ New Flow</a>
    {% endif %}
  </div>
  {% if flows %}
  <table>
    <thead>
      <tr>
        <th>Name</th><th>Source</th><th>Source Path</th>
        <th>Dest</th><th>Dest Path</th><th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {% for flow in flows %}
      <tr>
        <td>{{ flow.name }}</td>
        <td>{{ flow.source_conn.name }}</td>
        <td>{{ flow.source_path }}</td>
        <td>{{ flow.dest_conn.name }}</td>
        <td>{{ flow.dest_path }}</td>
        <td>
          {% if user.can_operate %}
          <form method="post" action="{% url 'flows:run' flow.pk %}" class="inline-form">
            {% csrf_token %}
            <button type="submit" class="btn btn-warn btn-small">Run</button>
          </form>
          {% endif %}
          {% if user.is_admin %}
          <a href="{% url 'flows:edit' flow.pk %}" class="btn btn-small">Edit</a>
          <form method="post" action="{% url 'flows:delete' flow.pk %}" class="inline-form"
            data-confirm="DELETE {{ flow.name }}?">
            {% csrf_token %}
            <button type="submit" class="btn btn-danger btn-small">Del</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">No flows configured — add one above</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 3: Przepisz `flows/form.html`

```html
{% extends "base.html" %}
{% block title %}{{ action }} FLOW — TMASK-TRANSPORTER{% endblock %}
{% block content %}
{% if action == 'CREATE' %}
<div class="toolbar">
  <a href="{% url 'flows:create' %}" class="btn">Plik</a>
  <a href="{% url 'db_transfers:create' %}" class="btn">Baza</a>
</div>
{% endif %}
<div class="panel" style="max-width:700px;">
  <span class="panel-title">{{ action }} Relay Flow (Plik)</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error">{% for e in form.non_field_errors %}{{ e }}{% endfor %}</div>
    {% endif %}
    <div class="field">
      <label>Name</label>
      {{ form.name }}
      {% if form.name.errors %}<div class="field-error">{{ form.name.errors }}</div>{% endif %}
    </div>
    <div class="two-col" style="margin-top:1rem;">
      <div>
        <span class="panel-title" style="font-size:0.7rem;">Source</span>
        <div class="field">
          <label>Connection</label>
          {{ form.source_conn }}
          {% if form.source_conn.errors %}<div class="field-error">{{ form.source_conn.errors }}</div>{% endif %}
        </div>
        <div class="field">
          <label>Path</label>
          <div class="field-with-btn">
            {{ form.source_path }}
            <button type="button" class="btn btn-small"
              data-browse-open
              data-browse-field="id_source_path"
              data-browse-conn-sel="#id_source_conn">
              Browse
            </button>
          </div>
          {% if form.source_path.errors %}<div class="field-error">{{ form.source_path.errors }}</div>{% endif %}
        </div>
      </div>
      <div>
        <span class="panel-title" style="font-size:0.7rem;">Destination</span>
        <div class="field">
          <label>Connection</label>
          {{ form.dest_conn }}
          {% if form.dest_conn.errors %}<div class="field-error">{{ form.dest_conn.errors }}</div>{% endif %}
        </div>
        <div class="field">
          <label>Path</label>
          <div class="field-with-btn">
            {{ form.dest_path }}
            <button type="button" class="btn btn-small"
              data-browse-open
              data-browse-field="id_dest_path"
              data-browse-conn-sel="#id_dest_conn">
              Browse
            </button>
          </div>
          {% if form.dest_path.errors %}<div class="field-error">{{ form.dest_path.errors }}</div>{% endif %}
        </div>
      </div>
    </div>
    <div class="field" style="margin-top:1.2rem;">
      <label>Weryfikacja SHA-256</label>
      {{ form.verify_checksum }}
      <span class="field-hint">Po transferze porównuje sha256sum na hoście źródłowym i docelowym. Transfer = błąd przy rozbieżności.</span>
      {% if form.verify_checksum.errors %}<div class="field-error">{{ form.verify_checksum.errors }}</div>{% endif %}
    </div>
    <div class="form-actions">
      <button type="submit" class="btn">Save Flow</button>
      <a href="{% url 'flows:list' %}" class="btn btn-danger">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

#### Step 4: Przepisz `scheduler/list.html`

```html
{% extends "base.html" %}
{% block title %}SCHEDULER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Scheduled Transfers</span>
  <div style="margin-bottom:1rem;">
    {% if user.is_admin %}
    <a href="{% url 'scheduler:create' %}" class="btn">+ New Schedule</a>
    {% endif %}
  </div>
  {% if schedules %}
  <table>
    <thead>
      <tr><th>Flow</th><th>Źródło</th><th>Cel</th><th>Cron</th><th>Last Run</th><th>Status</th><th>Actions</th></tr>
    </thead>
    <tbody>
      {% for s in schedules %}
      <tr>
        <td>{{ s.flow.name|default:"—" }}</td>
        <td>{% if s.flow %}{{ s.flow.source_conn.name }}: {{ s.flow.source_path }}{% else %}—{% endif %}</td>
        <td>{% if s.flow %}{{ s.flow.dest_conn.name }}: {{ s.flow.dest_path }}{% else %}—{% endif %}</td>
        <td>{{ s.cron_expr }}</td>
        <td>{{ s.last_run|date:"Y-m-d H:i"|default:"—" }}</td>
        <td>{% if s.enabled %}<span class="glow">● Active</span>{% else %}<span class="text-dim">○ Paused</span>{% endif %}</td>
        <td>
          {% if user.is_admin %}
          <form method="post" action="{% url 'scheduler:toggle' s.pk %}" class="inline-form">{% csrf_token %}
            <button type="submit" class="btn btn-warn btn-small">{% if s.enabled %}Pause{% else %}Resume{% endif %}</button>
          </form>
          <a href="{% url 'scheduler:edit' s.pk %}" class="btn btn-small">Edit</a>
          <form method="post" action="{% url 'scheduler:delete' s.pk %}" class="inline-form"
            data-confirm="DELETE schedule?">{% csrf_token %}
            <button type="submit" class="btn btn-danger btn-small">Del</button>
          </form>
          {% else %}
          <span class="text-dim">—</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">No schedules — add one above</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 5: Przepisz `scheduler/form.html`

Zastąp **całą** treść pliku (usuwa `<style>` blok z linii 6-147, treniesiony do `crt.css` w Step 1):

```html
{% extends "base.html" %}
{% block title %}{{ action }} SCHEDULE — TMASK-TRANSPORTER{% endblock %}
{% block content %}
{% load static %}

{# ── Page header ──────────────────────────────────── #}
<div class="sched-wrap">
  <div class="sched-breadcrumb">
    Scheduler / <span class="current">{{ action|upper }} Schedule</span>
  </div>

  {% if form.non_field_errors %}
  <div class="msg-error" style="margin-bottom: 1.25rem;">
    {% for e in form.non_field_errors %}{{ e }}{% endfor %}
  </div>
  {% endif %}

  <form method="post" id="sched-form">
    {% csrf_token %}

    {# ── SEKCJA: CEL TRANSFERU ──────────────────────── #}
    <div class="sched-card">
      <div class="sched-card-title">Cel transferu</div>

      <div class="sf-row">
        <span class="sf-label">Flow</span>
        {{ form.flow }}
        {% if form.flow.errors %}<span class="sf-error">{{ form.flow.errors|join:", " }}</span>{% endif %}
      </div>

      {% if form.instance.flow_id %}
      <div class="flow-info">
        <span>{{ form.instance.flow.source_conn.name }}: {{ form.instance.flow.source_path }}</span>
        <span class="fi-arrow">→</span>
        <span>{{ form.instance.flow.dest_conn.name }}: {{ form.instance.flow.dest_path }}</span>
      </div>
      {% endif %}
    </div>

    {# ── SEKCJA: HARMONOGRAM ────────────────────────── #}
    <div class="sched-card">
      <div class="sched-card-title">Harmonogram</div>

      <div class="sf-row">
        <span class="sf-label">Wyrażenie cron</span>
        {{ form.cron_expr }}
        {% if form.cron_expr.errors %}<span class="sf-error">{{ form.cron_expr.errors|join:", " }}</span>{% endif %}
      </div>

      {# CRON quick-reference #}
      <div class="cron-panel">
        <div class="cron-panel-title">Format: min godz dzień miesiąc dzień_tyg — kliknij aby wstawić</div>
        <div class="cron-examples">
          <div class="cron-ex" data-cron="0 3 * * *">
            <span class="cron-ex-val">0 3 * * *</span>
            <span class="cron-ex-desc">codziennie 03:00</span>
          </div>
          <div class="cron-ex" data-cron="0 */6 * * *">
            <span class="cron-ex-val">0 */6 * * *</span>
            <span class="cron-ex-desc">co 6 godzin</span>
          </div>
          <div class="cron-ex" data-cron="*/30 * * * *">
            <span class="cron-ex-val">*/30 * * * *</span>
            <span class="cron-ex-desc">co 30 minut</span>
          </div>
          <div class="cron-ex" data-cron="0 0 * * 1">
            <span class="cron-ex-val">0 0 * * 1</span>
            <span class="cron-ex-desc">co poniedziałek 00:00</span>
          </div>
          <div class="cron-ex" data-cron="0 8 * * 1-5">
            <span class="cron-ex-val">0 8 * * 1-5</span>
            <span class="cron-ex-desc">pon–pt o 08:00</span>
          </div>
          <div class="cron-ex" data-cron="0 0 1 * *">
            <span class="cron-ex-val">0 0 1 * *</span>
            <span class="cron-ex-desc">1. dnia miesiąca</span>
          </div>
        </div>
      </div>

      {# Enabled #}
      <div class="enabled-row">
        {{ form.enabled }}
        <label for="{{ form.enabled.id_for_label }}">{{ form.enabled.label }}</label>
      </div>
    </div>

    {# ── Przyciski ──────────────────────────────────── #}
    <div class="sched-actions">
      <button type="submit" class="btn">Zapisz</button>
      <a href="{% url 'scheduler:list' %}" class="btn btn-danger">Anuluj</a>
    </div>
  </form>
</div>

<script src="{% static 'js/scheduler_form.js' %}"></script>

{% endblock %}
```

**Uwaga krytyczna:** `.cron-ex` class zachowana dokładnie (JS w `scheduler_form.js:4` robi `document.querySelectorAll('.cron-ex')` i czyta `data-cron` atrybut żeby wypełnić pole `cron_expr` po kliknięciu) — nie zmieniaj tej klasy ani `data-cron` atrybutu.

#### Step 6: Testy

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/flows/ apps/scheduler/ -q
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: brak regresji, `541 passed`.

#### Step 7: Manualna weryfikacja

```bash
docker compose up -d --build
```

Sprawdź `/flows/` (tabela + RUN), `/flows/new/` (dwie kolumny source/dest), `/scheduler/` (tabela z toggle pause/resume), `/scheduler/new/` — **kluczowy test regresji**: kliknij dowolny przykład w panelu CRON (`0 3 * * *` itp.) i sprawdź czy pole `WYRAŻENIE CRON` faktycznie się wypełnia (potwierdza że `.cron-ex` + `data-cron` nadal działa z `scheduler_form.js`).

#### Step 8: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/flows/ services/web/templates/scheduler/ services/web/static/css/crt.css
git commit -m "feat(ui): flows + scheduler na nowym design systemie (task 8/9)"
```

---

### Task 9: Organization + Audit Log + Webhook Deliveries + Notifications + finalna weryfikacja

**Files:**
- Modify: `services/web/templates/organization/settings.html` (całość, 23 linie)
- Modify: `services/web/templates/audit_log/list.html` (całość, 37 linii)
- Modify: `services/web/templates/webhook_deliveries/list.html` (całość, 43 linie)
- Modify: `services/web/templates/notifications/transfer_done.html` (całość, 29 linii)
- Modify: `services/web/templates/notifications/transfer_failed.html` (całość, 30 linii)
- No change: `services/web/templates/notifications/transfer_done.txt`, `transfer_failed.txt` (plaintext, brak CSS/HTML do redesignu)

**Interfaces:**
- Consumes: `.panel`, `.panel-title`, `.field`, `.field-error`, `.status`, `.status-*`, `.msg-error`, `.btn` z Task 1.

#### Step 1: Przepisz `organization/settings.html`

```html
{% extends "base.html" %}
{% block title %}ORGANIZACJA — ADMIN{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Ustawienia organizacji</span>
  <form method="post">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="msg-error" style="margin-bottom:1rem;">
      {% for error in form.non_field_errors %}{{ error }}<br>{% endfor %}
    </div>
    {% endif %}
    {% for field in form %}
    <div class="field">
      <label>{{ field.label }}</label>
      {{ field }}
      {% if field.errors %}<div class="field-error">{{ field.errors }}</div>{% endif %}
    </div>
    {% endfor %}
    <button type="submit" class="btn">Zapisz</button>
  </form>
</div>
{% endblock %}
```

#### Step 2: Przepisz `audit_log/list.html`

```html
{% extends "base.html" %}
{% block title %}AUDIT LOG — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Audit Log — zmiany konfiguracji (ostatnie {{ entries|length }})</span>
  {% if entries %}
  <table>
    <thead>
      <tr>
        <th>Data</th><th>User</th><th>Akcja</th><th>Obiekt</th><th>Zmiany</th>
      </tr>
    </thead>
    <tbody>
      {% for entry in entries %}
      <tr>
        <td>{{ entry.created_at|date:"Y-m-d H:i:s" }}</td>
        <td>{{ entry.user.username|default:"—" }}</td>
        <td><span class="status status-{{ entry.action }}">{{ entry.get_action_display|upper }}</span></td>
        <td>{{ entry.model_name }}: {{ entry.object_repr }}</td>
        <td>
          {% if entry.changed_fields %}
            {% for field, values in entry.changed_fields.items %}
              <div><code>{{ field }}</code>: {{ values.0 }} → {{ values.1 }}</div>
            {% endfor %}
          {% else %}
            —
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">Brak wpisów audytu.</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 3: Przepisz `webhook_deliveries/list.html`

```html
{% extends "base.html" %}
{% block title %}WEBHOOK DELIVERIES — TMASK-TRANSPORTER{% endblock %}
{% block content %}
<div class="panel">
  <span class="panel-title">Historia dostarczeń webhooka (ostatnie {{ deliveries|length }})</span>
  {% if circuit_open %}
  <div class="msg-error" style="margin-bottom:1rem;">
    Circuit breaker otwarty — dostarczenia wstrzymane do {{ circuit_open_until|date:"Y-m-d H:i:s" }}
    (zbyt wiele kolejnych błędów pod rząd)
  </div>
  {% endif %}
  {% if deliveries %}
  <table>
    <thead>
      <tr>
        <th>Data</th><th>Transfer</th><th>Status</th><th>URL</th><th>Błąd</th>
      </tr>
    </thead>
    <tbody>
      {% for d in deliveries %}
      <tr>
        <td>{{ d.created_at|date:"Y-m-d H:i:s" }}</td>
        <td>{% if d.job %}<a href="{% url 'transfers:detail' d.job.pk %}">#{{ d.job.pk }}</a>{% else %}—{% endif %}</td>
        <td>
          {% if d.skipped %}
          <span class="status status-pending">Skipped</span>
          {% elif d.success %}
          <span class="status status-done">OK</span>
          {% else %}
          <span class="status status-failed">Failed</span>
          {% endif %}
        </td>
        <td>{{ d.url|truncatechars:45 }}</td>
        <td>{{ d.error_message|default:"—"|truncatechars:80 }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="text-muted">Brak dostarczeń webhooka.</p>
  {% endif %}
</div>
{% endblock %}
```

#### Step 4: Przepisz `notifications/transfer_done.html`

E-maile HTML wymagają CSS inline/w `<style>` w `<head>` (klienci pocztowe nie ładują zewnętrznych arkuszy stylów niezawodnie) — to jedyne dwa szablony w projekcie gdzie `<style>` blok **zostaje**, tylko z nowymi kolorami zamiast starych:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:20px; }
  .header { border:1px solid #22c55e; border-radius:8px; padding:10px 20px; margin-bottom:20px; }
  .header h1 { color:#22c55e; font-size:16px; margin:0; letter-spacing:0.02em; }
  table { border-collapse:collapse; width:100%; }
  td { padding:4px 12px; color:#f8fafc; }
  td:first-child { color:#94a3b8; width:80px; }
  .footer { margin-top:20px; border-top:1px solid #334155; padding-top:10px; font-size:11px; color:#64748b; }
</style>
</head>
<body>
  <div class="header">
    <h1>TMask Transporter — Transfer Done</h1>
  </div>
  <p>Job #{{ job.pk }} zakończony sukcesem.</p>
  <table>
    <tr><td>FROM</td><td>{{ job.source_path }}</td></tr>
    <tr><td>TO</td><td>{{ job.destination_path }}</td></tr>
    <tr><td>START</td><td>{% if job.started_at %}{{ job.started_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}</td></tr>
    <tr><td>END</td><td>{% if job.finished_at %}{{ job.finished_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}</td></tr>
    <tr><td>HOST</td><td>{% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}Relay: {{ job.flow.name }}{% else %}—{% endif %}</td></tr>
  </table>
  <div class="footer">TMask Transporter &mdash; ustawienia powiadomień: /accounts/profile/</div>
</body>
</html>
```

#### Step 5: Przepisz `notifications/transfer_failed.html`

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:20px; }
  .header { border:1px solid #ef4444; border-radius:8px; padding:10px 20px; margin-bottom:20px; }
  .header h1 { color:#ef4444; font-size:16px; margin:0; letter-spacing:0.02em; }
  table { border-collapse:collapse; width:100%; }
  td { padding:4px 12px; color:#f8fafc; }
  td:first-child { color:#94a3b8; width:80px; }
  .error-row td { color:#ef4444; }
  .footer { margin-top:20px; border-top:1px solid #334155; padding-top:10px; font-size:11px; color:#64748b; }
</style>
</head>
<body>
  <div class="header">
    <h1>TMask Transporter — Transfer Failed</h1>
  </div>
  <p>Job #{{ job.pk }} zakończony błędem.</p>
  <table>
    <tr><td>FROM</td><td>{{ job.source_path }}</td></tr>
    <tr><td>TO</td><td>{{ job.destination_path }}</td></tr>
    <tr><td>START</td><td>{% if job.started_at %}{{ job.started_at|date:"Y-m-d H:i" }}{% else %}—{% endif %}</td></tr>
    <tr class="error-row"><td>ERROR</td><td>{{ job.error_message|default:"UNKNOWN ERROR" }}</td></tr>
    <tr><td>HOST</td><td>{% if job.connection %}{{ job.connection.name }} ({{ job.connection.protocol|upper }}){% elif job.flow %}Relay: {{ job.flow.name }}{% else %}—{% endif %}</td></tr>
  </table>
  <div class="footer">TMask Transporter &mdash; ustawienia powiadomień: /accounts/profile/</div>
</body>
</html>
```

#### Step 6: Testy per-app

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/organization/ apps/audit_log/ apps/webhook_deliveries/ apps/notifications/ -q
```

Expected: brak regresji na tych 4 app.

#### Step 7: Finalna weryfikacja całego brancha

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
docker compose --profile test build web-test
docker compose --profile test run --rm web-test python -m pytest apps/ -q
```

Expected: `541 passed, 0 failed` (identyczna liczba jak przed rozpoczęciem redesignu — **zero nowych testów oczekiwane w tym planie poza jednym smoke testem z Task 1 Step 5**, więc finalna liczba to `542 passed`).

Następnie sprawdź że **żaden szablon w całym `templates/` nie referuje już starych CRT-specyficznych klas**:

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt/services/web
grep -rn 'class="box\|box-title\|\[ [A-ZĄĆĘŁŃÓŚŹŻ]' templates/ || echo "CLEAN — brak pozostałości starego motywu"
```

Expected: `CLEAN — brak pozostałości starego motywu`. Jeśli grep coś znajdzie — to pominięty podczas migracji szablon, wróć i popraw go zgodnie z konwencją odpowiedniego taska powyżej (najbliższego pasującego funkcjonalnie).

#### Step 8: Manualna weryfikacja całej aplikacji

```bash
docker compose up -d --build
```

Przejdź przez **wszystkie** strony aplikacji w przeglądarce (`https://localhost`) na 375px i 1440px: login → dashboard → connections (list+form+test) → transfers (create+live log) → db_transfers (list+create+detail) → flows (list+form) → scheduler (list+form, sprawdź klik na przykład CRON) → logs → users → organization settings → audit log → webhook deliveries → profile (wszystkie karty + 2FA setup/verify/recovery codes + backup/restore). Sprawdź też z `prefers-reduced-motion: reduce` włączonym w devtools na dashboardzie i liście statusów `running`.

#### Step 9: Commit

```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
git add services/web/templates/organization/ services/web/templates/audit_log/ services/web/templates/webhook_deliveries/ services/web/templates/notifications/
git commit -m "feat(ui): organization/audit/webhooks/notifications na nowym design systemie + finalna weryfikacja (task 9/9)"
```

---

## Odstępstwo od spec — ikony SVG

Spec (sekcja "Ikony") proponuje wprowadzenie ikon SVG (status badges, akcje w tabelach, nav) zamiast czystego tekstu. Ten plan **celowo tego nie realizuje** jako osobnego zadania: wymagałoby to wyboru zestawu ikon (licencja, self-hosting), dodania markupu do ~15 szablonów i podwoiłoby zakres planu bez zmiany rdzenia designu. Zasada `color-not-only` (WCAG) jest mimo to spełniona bez ikon — każdy status/wskaźnik w tym planie ma tekstowy odpowiednik obok koloru: pill statusu pokazuje słowo (`PENDING`/`RUNNING`/`DONE`...), a binarne stany aktywności używają glifów Unicode `●`/`○` + słowo (`● Active` / `○ Paused`, `● Yes` / `○ No`) — zachowane z oryginalnego designu, nie nowe. Wprowadzenie pełnego systemu ikon SVG pozostaje uzasadnionym, ale osobnym follow-upem, nie blokerem dla tego redesignu.

## Po zakończeniu wszystkich 9 tasków

Użyj **superpowers:finishing-a-development-branch** — standardowa procedura: weryfikacja testów, wybór (merge lokalnie do `main` / PR / zostaw / odrzuć). Zgodnie z ustaloną w tym projekcie zasadą, **nie pushuj do `origin`** bez osobnego, jawnego potwierdzenia (push uruchamia produkcyjny deploy CI/CD) — domyślnie proponuj tylko merge lokalny do `main`.
