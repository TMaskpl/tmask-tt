# Dark Ops Console — Redesign wizualny tmask-transporter

**Data:** 2026-07-27
**Status:** draft do review

## Cel

Zastąpić obecny motyw "terminal CRT" (fosforyzująca zieleń na czerni, scanlines,
ASCII-ramki, migoczący kursor) nowoczesnym, dynamicznym dark-mode UI w stylu
narzędzi deweloperskich (Linear/Vercel/Raycast), zachowując dziedzictwo
terminala tam, gdzie ma to sens funkcjonalny (live log, dane/monospace), a nie
jako globalny filtr na całej aplikacji.

## Poza zakresem (explicit non-goals)

- Brak trybu jasnego (light mode) — aplikacja zostaje dark-only, tak jak dziś.
- Brak migracji frameworkowej — zostajemy przy plain CSS + Django templates +
  HTMX, zero build stepu (webpack/vite), zero preprocesora (Sass/Less).
- Brak zmian funkcjonalnych/biznesowych — to czysto wizualny redesign. Żadna
  strona nie zyskuje ani nie traci funkcji.
- Brak zmiany struktury nawigacji/IA (informacja architektury) — te same
  strony, te same linki w nav, ta sama hierarchia.

## Zakres

Redesign obejmuje **całą aplikację w jednym cyklu**: wspólny design system
(tokeny, komponenty) + wszystkie 30 szablonów w `services/web/templates/`
(oraz jedyny arkusz stylów `static/css/crt.css`, jedyny plik z Chart.js
theming `static/js/dashboard.js`).

## Stan obecny (inwentaryzacja)

- **CSS**: jeden plik, `services/web/static/css/crt.css` (483 linie), plain
  CSS, brak build stepu, cache-busting ręczny przez `?v=N` w
  `templates/base.html`.
- **Fonty**: `JetBrains Mono` ładowany przez `@import` z Google Fonts CDN
  (jedyne miejsce w projekcie, które NIE jest self-hosted — niespójne z resztą
  projektu, gdzie HTMX i Chart.js są świadomie self-hosted, patrz
  `[[reference-zap-local]]`-style konwencja i funkcja #3/#4 "HTMX self-host").
- **Base template**: `templates/base.html` (62 linii) — bloki `title` /
  `content` / `scripts`, nav server-rendered z podświetleniem aktywnego linku,
  globalny modal file-browsera, brak footera.
- **30 szablonów** w jednym wspólnym katalogu `templates/` (nie per-app),
  pogrupowane funkcjonalnie: accounts (login/profile/2FA/users),
  dashboard (KPI + 3 wykresy Chart.js), connections (SSH/DB), transfers
  (create/detail/live-log/logi), db_transfers (list/create/detail/live-log),
  flows, scheduler, organization, audit_log, webhook_deliveries, notifications
  (e-maile), `500.html` (samodzielny, nie extenduje base.html).
- **Design tokens**: tylko 7 zmiennych CSS w `:root` (`--bg`, `--green`,
  `--green-bright`, `--amber`, `--red`, `--dim`, `--border`). Brak tokenów
  spacing/radius/shadow — wartości hardcodowane inline w całym pliku.
  `border-radius` nie występuje ani razu — zero zaokrągleń w obecnym designie.
- **Sygnatury CRT do zastąpienia**: scanlines (`body::after`,
  `repeating-linear-gradient`), text-glow (`text-shadow` zielony wszędzie),
  `.box`/`.box-title` (ramki ASCII z unoszącą się etykietą), migający kursor
  (`input:focus::after`, `.dash-header h1::after`), literalne `[ LABEL ]` w
  treści przycisków (~15 szablonów).
- **Wielokrotnego użytku, niezależne od motywu (do zachowania jako
  struktura)**: `.field-grid`, `.stat-grid`/`.stat-tile` (layout, nie kolor),
  `.chart-grid`/`.chart-box`/`.chart-canvas`, `.progress-wrap`/`.progress-bar`,
  `.log-terminal` (scroll container), `.file-browser` modal layout,
  breakpointy 900px/600px/560px, `prefers-reduced-motion` handling (już
  istnieje — do zachowania i rozszerzenia).
- **JS**: jeden plik JS per feature, brak frameworka. `dashboard.js` ustawia
  `Chart.defaults.color`/`font.family`/`font.size` programowo — jedyne miejsce
  gdzie redesign dotyka JS, nie tylko CSS.
- **112 wystąpień `style="..."` inline** + kilka bloków `<style>` w
  `scheduler/form.html`, `500.html`, `accounts/profile.html`,
  `notifications/transfer_done.html`, `notifications/transfer_failed.html` —
  te trzeba zaudytować przy okazji, bo hardcodowane inline style'e nie da się
  reskinować przez tokeny.

## Design System — "Dark Ops Console"

### Paleta kolorów (design tokens, `:root`)

```css
:root {
  /* Powierzchnie */
  --bg:            #0f172a;  /* tło strony (slate-900) */
  --surface:       #1e293b;  /* karty/panele (slate-800) */
  --surface-raised:#243244;  /* hover/elevated state kart */
  --border:        #334155;  /* obramowania (slate-600) */
  --border-subtle: #1e293b;  /* separator w tabelach, mniej widoczny */

  /* Tekst */
  --text:          #f8fafc;  /* główny */
  --text-muted:    #94a3b8;  /* pomocniczy/label/caption */
  --text-dim:      #64748b;  /* najmniej istotny (timestamp, meta) */

  /* Akcent — dziedzictwo terminala, użyty punktowo, nie globalnie */
  --accent:        #22c55e;  /* zielony — status running/success, focus, CTA */
  --accent-dim:    #16a34a;
  --accent-glow:   rgba(34, 197, 94, 0.35);

  /* Semantyczne statusy */
  --warn:          #f59e0b;  /* amber — running/pending */
  --danger:        #ef4444;  /* red — failed/destructive */
  --danger-glow:   rgba(239, 68, 68, 0.3);

  /* Skala */
  --radius-sm:  6px;
  --radius-md:  10px;
  --radius-lg:  14px;
  --shadow-card: 0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3);
  --shadow-raised: 0 8px 24px rgba(0,0,0,0.35);
  --ease-standard: cubic-bezier(0.16, 1, 0.3, 1);
}
```

Uzasadnienie: `#0f172a`/`#1e293b` (slate) zamiast `#0a0a0a` — mniej męczące
przy dłuższej pracy (WCAG AAA nadal spełnione, ale bez "czystej czerni" która
w połączeniu z jaskrawą zielenią powodowała najsilniejsze zmęczenie oczu).
Zielony (`--accent`) zostaje jako świadomy pomost do starego motywu — używany
punktowo (status, focus ring, jeden CTA na widok), a nie jako kolor tekstu
całej aplikacji.

### Typografia

- **UI chrome (nav, nagłówki, formularze, przyciski, opisy)**: `Inter` —
  nowoczesny sans-serif, kontrastujący z monospace, to jest główny nośnik
  wrażenia "nowoczesne".
- **Dane/logi/terminal (`.log-terminal`, ID zadań, nazwy hostów/baz, kod
  błędów, tabele z danymi technicznymi)**: `JetBrains Mono` — zostaje jako
  świadomy nośnik "dziedzictwa terminala", ograniczony do miejsc gdzie dane
  faktycznie są tekstem/kodem.
- Oba fonty **self-hosted** (woff2 w `static/fonts/`, `@font-face` lokalny) —
  usuwa jedyną niespójność projektu (dotychczasowy `@import` z Google Fonts
  CDN), spójne z konwencją self-hostingu HTMX/Chart.js. Wagi do pobrania:
  `Inter` 400/500/600/700 (regularny tekst / etykiety / nagłówki mniejsze /
  nagłówki główne), `JetBrains Mono` 400/700 (bez zmian względem obecnego
  zakresu wag).
- Skala: `--font-size-xs: 0.75rem`, `--font-size-sm: 0.85rem`,
  `--font-size-base: 0.95rem` (bazowy tekst UI, każda strona to panel roboczy,
  nie dokument do czytania — trochę mniejszy niż webowe 16px jest tu OK, ale
  nigdy poniżej 12px), `--font-size-lg: 1.25rem`, `--font-size-xl: 1.75rem`
  (nagłówki dashboardu).

### Kluczowe efekty

- **Glow punktowy, nie wszechobecny**: `box-shadow`/`text-shadow` z
  `--accent-glow` tylko na: status "running" (pulsujący), focus ring inputów,
  aktywny link w nav, accent-bar na `stat-tile`. Nie na każdym nagłówku jak
  dziś.
- **Karty zamiast ASCII-ramek**: `.box` → `.panel` — `background: var(--surface)`,
  `border: 1px solid var(--border)`, `border-radius: var(--radius-md)`,
  `box-shadow: var(--shadow-card)`. Tytuł panelu jako zwykły nagłówek nad
  treścią, nie unosząca się etykieta na obramowaniu (ten trik miał sens tylko
  w estetyce ASCII).
- **Animacje 150–300ms**, `--ease-standard` (nie linear) na: hover kart, zmiany
  stanu statusu, wjazd nowego wpisu w live logu, zmianę wartości progress
  bara. Zachowujemy i rozszerzamy istniejący `prefers-reduced-motion` guard.
- **Progress bar**: prawdziwy gradient/fill z `--accent`, bez zmian
  strukturalnych (już dziś oparty o realny % z funkcji #20) — tylko re-skin
  kolorystyczny + zaokrąglenie rogów.
- **Bez scanlines, bez migającego kursora jako dekoracji.** Migający kursor
  zostaje wyłącznie w obrębie `.log-terminal` jako opcjonalny wskaźnik "live
  tailing" (rzeczywista informacja o stanie, nie dekoracja).

### Przyciski — decyzja o `[ LABEL ]`

Usuwamy literalne nawiasy kwadratowe z treści przycisków (`[ LOGIN ]` →
`Login`) na rzecz właściwego stylowania komponentu (tło/obramowanie/hover),
zgodnie z zasadą UI/UX Pro Max "no ASCII-as-UI, use real components". Wyjątek:
komendy/placeholder tekst wewnątrz samego `.log-terminal` mogą zachować surowy,
terminalowy zapis (`$ pg_dump ...`), bo tam to jest treść danych, nie etykieta
UI.

### Komponenty do przeprojektowania (mapowanie stare → nowe)

| Stary element | Nowy komponent | Uwagi |
|---|---|---|
| `.box`/`.box-nested`/`.box-title` | `.panel`/`.panel-title` | karta z radius+shadow, tytuł jako zwykły nagłówek |
| `.btn`/`.btn-danger`/`.btn-warn`/`.btn-small` | te same nazwy klas, nowy wygląd | wypełnione/outline warianty, bez `text-transform: uppercase` + brackets |
| `.status-*` (pending/running/done/failed/cancelled) | te same nazwy, nowa kolorystyka | pill z lekkim tłem + tekst, nie tylko obramowanie |
| `.stat-tile`/`.stat-grid` | zachowane nazwy, nowy skin | karta zamiast obramowania+gradient-linia, radius, glow tylko na accent-bar |
| `.log-terminal`/`.log-line`/`.log-info/.warn/.error` | zachowane, JetBrains Mono, ciemniejsze tło niż otoczenie (`--bg` zamiast `--surface`) — to jedyne miejsce z "prawdziwym terminalem" |
| `.progress-bar`/`.progress-bar-fill` | zachowane, zaokrąglone rogi + gradient fill |
| `#file-browser-modal`/`.breadcrumbs`/`.file-list` | zachowane nazwy, nowy skin (panel + glassmorphism scrim) |
| `.messages`/`.msg-error`/`.msg-ok`/`.msg-success` | zachowane, pill-style z ikoną (SVG, nie tylko kolor — zasada `color-not-only`) |
| nav | sticky, `--surface` tło zamiast `--bg`, subtelny `backdrop-filter: blur()` (glassmorphism), bez text-shadow na każdym linku |
| Chart.js (`dashboard.js`) | `Chart.defaults.color` → `--text-muted`, `font.family` → `Inter`, siatka wykresu w `--border-subtle`, serie danych w `--accent`/`--warn`/`--danger` |
| `500.html` | przechodzi na wspólny design system (dziś ma własny, odrębny CRT skin) |

### Ikony

Obecnie brak ikon w ogóle (czysty tekst/ASCII). Redesign wprowadza SVG ikony
(inline SVG lub jeden sprite `static/icons/`, zestaw stylistycznie spójny —
np. Lucide, licencja MIT, statyczne pliki, self-hosted) tam gdzie poprawiają
skanowalność: status badges, akcje w tabelach (edit/delete/test), nav.
Zgodnie z zasadą `no-emoji-icons` — zero emoji jako ikon.

### Dostępność

- Kontrast: wszystkie pary tekst/tło z nowej palety zweryfikowane pod kątem
  WCAG AA minimum (4.5:1 tekst normalny, 3:1 duży tekst/ikony) — `--text` na
  `--bg`/`--surface` i `--text-muted` na `--surface` to główne pary do
  sprawdzenia w implementacji.
- `prefers-reduced-motion`: rozszerzony o wszystkie nowe animacje (wjazd karty,
  fade statusu, hover transform), nie tylko istniejące dwa przypadki.
- Fokus klawiatury: `outline`/`box-shadow` ring z `--accent`, widoczny na
  wszystkich interaktywnych elementach (dziś jest tylko na inputach).
- Kolor nigdy jedynym nośnikiem znaczenia: statusy dostają ikonę + kolor, nie
  sam kolor.

## Plan migracji szablonów

Ponieważ wszystkie 30 szablonów współdzielą jeden `crt.css` i jeden
`base.html`, kolejność ma znaczenie: najpierw fundament (tokeny + komponenty
współdzielone + base.html), potem strony grupowane po aplikacji Django (żeby
każda grupa była niezależnie testowalna):

1. **Fundament**: nowy `theme.css` (zastępuje `crt.css` zawartościowo, ta sama
   ścieżka + bump `?v=N`), self-hosted fonty, `base.html` (nav, messages,
   file-browser modal chrome).
2. **Dashboard**: `dashboard/index.html` + `dashboard.js` (Chart.js theming) —
   naturalny "dowód koncepcji" bo używa najwięcej komponentów naraz (stat
   tiles, charts, panels).
3. **Accounts + Users**: login, profile, 2FA (setup/verify/recovery-codes),
   users list/create.
4. **Connections**: list, form, fragmenty HTMX (test-result, db-tables-options,
   browser-fragment).
5. **Transfers + Logs**: create/detail (live log), log-fragment, dry-run-result,
   progress-bar fragment, `logs/list.html`.
6. **DB Transfers**: list, create, detail, log-fragment.
7. **Flows + Scheduler**: list/form dla obu.
8. **Organization + Audit Log + Webhook Deliveries**: settings, audit list,
   webhook deliveries list.
9. **500.html + e-maile** (`notifications/*.html`/`*.txt`): przejście na
   wspólny design system; e-maile mają własne ograniczenia (inline CSS
   wymagany dla klientów pocztowych — zostaje inline, ale w nowej palecie).

Podczas migracji każdej grupy: audyt i usunięcie `style="..."` inline oraz
bloków `<style>` w dotykanych szablonach (nie robimy oddzielnego przebiegu
"sprzątania" — czyścimy przy okazji, bo hardcode blokuje reskin).

## Testowanie

Brak testów wizualnych/regresji w projekcie (i nie planujemy ich wprowadzać —
poza zakresem). Weryfikacja per grupa:
- Django unit testy (`views.py`) nie powinny się zepsuć — redesign nie zmienia
  HTML struktury/id/name atrybutów używanych przez testy ani przez JS
  (`querySelector`/`getElementById`), tylko klasy CSS i markup wewnątrz
  komponentów. Tam gdzie trzeba zmienić strukturę (np. `.box-title` →
  nagłówek), sprawdzić czy testy Django asercjące treść HTML (`assertContains`)
  nie łamią się na zmienionym markupie.
- Manualna weryfikacja w przeglądarce (`docker compose up`, `https://localhost`)
  każdej grupy stron po migracji — zgodnie z ogólną zasadą projektu dla zmian
  UI (uruchomić i przejrzeć, nie tylko polegać na testach jednostkowych).
- Sprawdzenie obu skrajnych szerokości (375px, 1440px) i przynajmniej jednej
  strony z `prefers-reduced-motion: reduce` włączonym w devtools.

## Ryzyka

- **112 inline style + kilka `<style>` bloków** mogą kolidować z nowymi
  tokenami jeśli przeoczone — mitygacja: jawny krok audytu w każdej grupie
  migracji (patrz wyżej), nie osobna faza na końcu.
- **Testy Django asercjące fragmenty HTML** (`assertContains(response, "...")`)
  mogące złapać stary tekst/klasy — do wyłapania per grupa przy uruchamianiu
  testów `web`/`worker` po każdej migrowanej grupie.
- **Self-hosting fontów** wymaga pobrania i wstawienia plików woff2 do repo
  (nowy katalog `static/fonts/`) — jednorazowy krok w Fundamencie, zero
  ryzyka bieżącego (fonty open-source, stabilne wersje).
- **Brak testów wizualnych** oznacza że regresje wizualne (nie funkcjonalne)
  zostaną złapane tylko manualnie — akceptowalne ryzyko biorąc pod uwagę brak
  takiej infrastruktury w projekcie dziś i brak żądania jej budowy.
