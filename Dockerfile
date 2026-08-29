FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY app ./app
RUN python -m pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 insightforge \
    && mkdir -p /app/data \
    && chown -R insightforge:insightforge /app
USER insightforge
EXPOSE 8000
CMD ["python", "-m", "app"]
