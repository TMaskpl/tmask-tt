---
name: frontend-design
description: Plugin Anthropic do tworzenia wyróżniających się interfejsów UI — unika generycznych "AI slop" estetyk. Produkuje działający kod z wyjątkową dbałością o szczegóły wizualne. Dla tmask-tt: zachowuj estetykę CRT/terminal z crt.css.
---

# Plugin: frontend-design

Plugin Anthropic dla Claude Code do implementacji produkcyjnych interfejsów frontend
z wyróżniającą się estetyką. Unika generycznych wzorców — każdy projekt ma własny charakter.

## Instalacja

```bash
claude plugins install frontend-design@claude-plugins-official
```

Weryfikacja:
```bash
claude plugins list | grep frontend-design
# Oczekiwany output: frontend-design@claude-plugins-official ✔ enabled
```

---

## Dostępne skille

### frontend-design

**Komenda:** `/frontend-design <opis komponentu/strony>`

Tworzy kompletny, działający kod UI z:
- Przemyślaną estetyką (nie generyczną)
- Dobraną typografią (nie Arial/Inter/Roboto)
- Spójną paletą kolorów z CSS variables
- Animacjami i micro-interactions
- Responsywnym layoutem

---

## Kontekst estetyczny tmask-tt

Projekt używa własnej estetyki **Terminal/CRT** zdefiniowanej w `retro-style` skill.

**Przy każdym wywołaniu frontend-design dla tmask-tt podaj kontekst:**

```
/frontend-design [opis komponentu] — zachowaj styl CRT/retro terminalowy z crt.css,
zielony tekst na czarnym tle, monospace font, efekty scanlines
```

### Zasady estetyczne tmask-tt

| Element | Wartość |
|---------|---------|
| Font | monospace — `Courier New`, `IBM Plex Mono` lub podobny |
| Kolor tekstu | `#00ff41` (zielony terminal) lub `#33ff33` |
| Tło | `#0a0a0a` / `#000000` |
| Akcenty | `#ffff00` (żółty) dla błędów/alertów |
| Efekty | scanlines przez `crt.css`, glow na aktywnych elementach |
| Framework | Django templates + HTMX (nie React/Vue) |

Patrz skill `retro-style` — pełna specyfikacja CSS klas i wzorców.

---

## Kiedy używać

- Nowy widok Django wymagający niestandardowego layoutu
- Redesign istniejącej strony (np. scheduler, lista połączeń)
- Nowy komponent HTMX z live-update
- Modal, drawer, formularz — gdy domyślny Bootstrap wygląda zbyt generycznie

---

## Czego unikać

| Unikaj | Zamiast |
|--------|---------|
| Gradients fioletowy/niebieski na białym | Czarne tło + zielony tekst |
| Inter, Roboto, system-ui | IBM Plex Mono, Courier New |
| Okrągłe karty z cieniem | Twarde ramki `1px solid #00ff41` |
| Animacje slide/fade | Efekty typing, blink, scanline |
| Bootstrap domyślny | Klasy z `crt.css` + custom CSS |

---

## Przykładowe wywołania dla tmask-tt

```
/frontend-design strona logowania — Terminal/CRT, ASCII art logo TMASK,
pola formularza jako bloki terminala, przycisk LOGIN z efektem blink

/frontend-design panel statusu transferu — live progress bar w stylu
terminala, logi jako scrolling text, status RUNNING/DONE/ERROR w kolorach

/frontend-design modal potwierdzenia usunięcia połączenia — minimalistyczny,
ostrzeżenie żółtym akcentem, dwa przyciski [CONFIRM] [CANCEL] w stylu CRT
```

---

## Źródło i wersja

- Autor: Anthropic
- Marketplace: `claude-plugins-official`
- Wersja: unknown (aktualizowana automatycznie)
