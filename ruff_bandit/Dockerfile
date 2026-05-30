# docker build -t tmask-python-linter .

# docker run --rm -v "$(pwd):/code" tmaskpl-python-linter ruff check /code 
# docker run --rm -v "$(pwd):/code" tmaskpl-python-linter bandit -r /code

# Użycie oficjalnego obrazu Bandit jako bazy [4]
FROM ghcr.io/pycqa/bandit/bandit:latest

# Przełączenie na użytkownika root, aby móc instalować pakiety (jeśli obraz bazowy tego wymaga)
USER root

# Instalacja Ruff za pomocą pip [5, 6]
RUN pip install --no-cache-dir ruff

# (Opcjonalnie) Powrót do użytkownika domyślnego, jeśli obraz go posiada
# USER bandit

# Ustawienie domyślnego polecenia (opcjonalnie, zależy od sposobu użycia)
# ENTRYPOINT ["bandit"]