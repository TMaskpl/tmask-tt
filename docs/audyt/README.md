# Historia audytów bezpieczeństwa

| Data       | Narzędzia               | Wynik końcowy                                              | Plik                            |
|------------|-------------------------|------------------------------------------------------------|----------------------------------|
| 2026-05-21 | Statyczny (Explore)     | 5 krytycznych → wszystkie naprawione tego samego dnia      | [2026-05-21.md](2026-05-21.md)  |
| 2026-05-25 | SonarQube + ZAP + Codex | Django CVE-2025-64459 CVSS 9.1 → naprawione natychmiast   | [2026-05-25.md](2026-05-25.md)  |
| 2026-05-26 | SonarQube + ZAP + Codex | Path traversal CWE-22, SSRF CWE-918 → naprawione           | [2026-05-26.md](2026-05-26.md)  |
| 2026-05-27 | Codex                   | MITM fail-closed (CWE-295) → naprawione commit `949d73e`   | [2026-05-27.md](2026-05-27.md)  |

## Metodologia

Każdy audyt przeprowadzony w trzech warstwach:

- **SAST** — SonarQube (statyczna analiza kodu) lub ręczny przegląd przez agenta
- **DAST** — OWASP ZAP (dynamiczne skanowanie uruchomionej aplikacji)
- **Code Review** — Codex security review (OWASP Top 10, CWE patterns)

## Otwarte znaleziska (backlog)

| CWE      | Opis                                          | Priorytet | Audyt  |
|----------|-----------------------------------------------|-----------|--------|
| CWE-312  | GPG passphrase w plaintext w kolejce Celery/Redis | HIGH   | #25, #26 |
| CWE-306  | Redis bez autentykacji (`requirepass`)         | MEDIUM    | #26    |
| CWE-319  | Brak HSTS (`SECURE_HSTS_SECONDS`)             | MEDIUM    | #26    |
| CWE-307  | Brak rate-limiting na endpoint logowania       | LOW       | #26    |
| CWE-362  | Race condition na limit tokenów API (`select_for_update`) | LOW | #27 |
