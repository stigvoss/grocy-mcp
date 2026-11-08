# syntax=docker/dockerfile:1

# ---- build: turn the source tree into a wheel -------------------------------------------------
FROM python:3.12-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

# ---- runtime: only the wheel and its dependencies ---------------------------------------------
FROM python:3.12-slim

# Linked to the repository by the workflow (org.opencontainers.image.* labels are added there).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --create-home --uid 10001 --shell /usr/sbin/nologin grocy

COPY --from=build /dist/*.whl /tmp/wheels/
RUN pip install /tmp/wheels/*.whl && rm -rf /tmp/wheels

USER grocy
WORKDIR /home/grocy

# GROCY_URL and GROCY_API_KEY are read from the environment (see the README).
EXPOSE 8000
ENTRYPOINT ["grocy-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000", "--path", "/mcp"]
