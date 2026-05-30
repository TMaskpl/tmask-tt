---
name: superpowers
description: Plugin z biblioteką skilli dla Claude Code — TDD, debugging, planowanie implementacji, code review, praca z worktrees, równoległe agenty. Aktywuje się automatycznie przed każdą rozmową (using-superpowers). Instalacja jednorazowa.
---

# Plugin: superpowers

Biblioteka skilli dla Claude Code autorstwa Jesse Vincent (obra).
Dostarcza sprawdzone wzorce pracy: TDD, debugowanie, planowanie, review, równoległe agenty.

## Instalacja

```bash
claude plugins install superpowers@claude-plugins-official
```

Weryfikacja:
```bash
claude plugins list | grep superpowers
# Oczekiwany output: superpowers@claude-plugins-official v5.1.0 ✔ enabled
```

Plugin instaluje się raz globalnie (`scope: user`) — działa we wszystkich projektach.

---

## Dostępne skille

### Workflow developerski

| Skill | Komenda | Kiedy używać |
|-------|---------|-------------|
| `brainstorming` | `/brainstorming` | **Przed każdą nową funkcją** — eksploruje wymagania i design zanim dotkniesz kodu |
| `writing-plans` | `/writing-plans` | Gdy masz spec — tworzy plan implementacji krok po kroku |
| `subagent-driven-development` | automatyczny | Wykonuje plan przez dedykowane subagenty z review między taskami |
| `executing-plans` | `/executing-plans` | Wykonuje plan w bieżącej sesji z checkpointami |
| `finishing-a-development-branch` | `/finishing-a-development-branch` | Gdy implementacja gotowa — prezentuje opcje: merge/PR/keep/discard |

### Jakość kodu

| Skill | Komenda | Kiedy używać |
|-------|---------|-------------|
| `test-driven-development` | automatyczny | Przy każdej implementacji — test first, potem kod |
| `requesting-code-review` | `/requesting-code-review` | Przed merge — weryfikuje poprawność i jakość |
| `receiving-code-review` | `/receiving-code-review` | Po otrzymaniu review — jak priorytetyzować uwagi |
| `verification-before-completion` | automatyczny | Przed zgłoszeniem ukończenia — sprawdza czy naprawdę działa |

### Debugging i analiza

| Skill | Komenda | Kiedy używać |
|-------|---------|-------------|
| `systematic-debugging` | `/systematic-debugging` | Przy bugach i błędach testów — zanim zaproponujesz fix |
| `dispatching-parallel-agents` | automatyczny | Przy 2+ niezależnych zadaniach — uruchamia równolegle |

### Meta / infrastruktura

| Skill | Komenda | Kiedy używać |
|-------|---------|-------------|
| `using-superpowers` | automatyczny (session start) | Inicjalizuje bibliotekę skilli — uruchamia się automatycznie |
| `using-git-worktrees` | `/using-git-worktrees` | Przed pracą wymagającą izolacji od bieżącego brancha |
| `writing-skills` | `/writing-skills` | Przy tworzeniu lub edycji nowych skilli |

---

## Jak działają skille superpowers

Skille są ładowane przez `Skill` tool w Claude Code. Wywołanie:
```
/brainstorming nowa funkcja X
```
…powoduje załadowanie pełnej treści skilla do kontekstu i wykonanie instrukcji.

Kluczowa zasada: **`using-superpowers` uruchamia się automatycznie na początku każdej sesji** — wymusza sprawdzenie czy jakiś skill pasuje do zadania zanim zaczniesz.

---

## Typowe sekwencje dla tmask-tt

**Nowa funkcja:**
```
/brainstorming → /writing-plans → /subagent-driven-development → /finishing-a-development-branch
```

**Bug:**
```
/systematic-debugging → fix → /verification-before-completion → /requesting-code-review
```

**Nowy skill:**
```
/writing-skills
```

---

## Źródło i wersja

- Repozytorium: https://github.com/obra/superpowers
- Wersja: 5.1.0
- Licencja: MIT
- Marketplace: `claude-plugins-official`
