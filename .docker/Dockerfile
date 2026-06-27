ARG QGIS_TEST_VERSION=latest
FROM qgis/qgis:${QGIS_TEST_VERSION}

RUN apt update \
    && apt install -y \
        glibc-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV LANG=C.UTF-8

ENV LD_PRELOAD="/lib/x86_64-linux-gnu/libSegFault.so"
ENV SEGFAULT_SIGNALS="abrt segv"
ENV LIBC_FATAL_STDERR_=1

ENV UV_PROJECT_ENVIRONMENT=/venv

WORKDIR /usr/src

COPY requirements.txt /usr/src
COPY pyproject.toml /usr/src

RUN uv venv --system-site-packages
RUN uv add -r /usr/src/requirements.txt

COPY . /usr/src

RUN rm -rf .venv
