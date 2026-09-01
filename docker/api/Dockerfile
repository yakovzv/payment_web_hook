FROM python:3.13-slim-bullseye
COPY --from=ghcr.io/astral-sh/uv:0.7.20 /uv /uvx /bin/

ENV TZ='UTC'
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT=400
ENV PIP_REQUESTS_TIMEOUT=400
ENV PIP_RETRIES=30
ENV PIP_TIMEOUT=400

WORKDIR /usr/src/app/

RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir --upgrade setuptools && \
    pip3 install --no-cache-dir future && \
    rm -rf /root/.cache

ADD . /usr/src/app/

# Runtime deps only; test tooling lives in the 'dev' group and is not needed in the image.
RUN uv sync --locked --no-dev
