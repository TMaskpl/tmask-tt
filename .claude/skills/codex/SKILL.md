---
name: codex
description: Plugin OpenAI Codex dla Claude Code — deleguje zadania kodowania i code review do modelu Codex/GPT. Używaj do drugiej opinii przy bugach, głębokiej analizy kodu, zadań wymagających izolowanego kontekstu. Wymaga klucza API OpenAI.
---

# Plugin: codex

Plugin OpenAI dla Claude Code — umożliwia delegowanie zadań do modelu Codex (GPT).
Przydatny gdy Claude utknął, potrzebna jest druga opinia lub głębsza analiza.

## Instalacja

```bash
# Plugin pochodzi z marketplace openai-codex
claude plugins install codex@openai-codex
```

Weryfikacja:
```bash
claude plugins list | grep codex
# Oczekiwany output: codex@openai-codex v1.0.4 ✔ enabled
```

### Wymagania

| Wymaganie | Opis |
|-----------|------|
| Konto OpenAI | https://platform.openai.com |
| Klucz API | `OPENAI_API_KEY` — zmienna środowiskowa |
| Codex CLI | Instalowany automatycznie przez plugin |

Ustaw klucz API:
```bash
export OPENAI_API_KEY="sk-..."
# lub dodaj do ~/.zshrc / ~/.bashrc
```

---

## Dostępne skille

### Użytkowe (publiczne)

| Skill | Komenda | Kiedy używać |
|-------|---------|-------------|
| `codex:rescue` | `/codex rescue` | Gdy Claude utknął — deleguje diagnozę lub fix do Codex |
| `codex:setup` | `/codex setup` | Sprawdza konfigurację Codex CLI i toggle stop-time review gate |

### Wewnętrzne (używane automatycznie)

| Skill | Opis |
|-------|------|
| `codex:codex-cli-runtime` | Kontrakt pomocniczy dla wywoływania środowiska codex-companion |
| `codex:codex-result-handling` | Instrukcje prezentowania output Codex użytkownikowi |
| `codex:gpt-5-4-prompting` | Wewnętrzne wskazówki komponowania promptów dla Codex/GPT |

---

## Kiedy używać `codex:rescue`

Idealny gdy:
- Claude Code utknął w pętli lub wielokrotnie próbuje tego samego podejścia
- Potrzebna jest niezależna diagnoza buga (świeży kontekst)
- Zadanie jest powtarzalne i dobrze zdefiniowane (refaktor, dodanie testów)
- Chcesz drugiej opinii przed mergem

Wywołanie:
```
/codex rescue <opis zadania lub problemu>
```

Codex działa w izolowanym środowisku z dostępem do kodu — nie widzi historii rozmowy z Claude.

---

## Konfiguracja środowiska

Codex potrzebuje dostępu do plików projektu. Domyślnie działa w bieżącym katalogu roboczym.

Dla tmask-tt upewnij się że Claude Code jest uruchomiony z katalogu projektu:
```bash
cd /Users/dniemczok/Desktop/TMaskPL/tmask-tt
claude
```

---

## Źródło i wersja

- Repozytorium: https://github.com/openai/codex-plugin-cc
- Wersja: 1.0.4
- Autor: OpenAI
- Marketplace: `openai-codex`
