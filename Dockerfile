FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 agent

USER agent
ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "niannian_agent"]
