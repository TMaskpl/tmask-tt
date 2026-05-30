# docker build -t tmask-python-linter .

# docker run --rm --entrypoint ruff -v "$(pwd):/code" tmask-python-linter:latest check /code
# docker run --rm -v "$(pwd):/code" tmask-python-linter:latest -r /code

FROM ghcr.io/pycqa/bandit/bandit:latest

USER root

RUN pip install --no-cache-dir ruff

WORKDIR /code

# bandit.yaml at project root is mounted via -v "$(pwd):/code"
ENTRYPOINT ["bandit", "--config", "/code/bandit.yaml"]