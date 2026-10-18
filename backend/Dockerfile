FROM python:3.12-slim

# Don't write .pyc files; print logs immediately instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dev Compose passes requirements-dev.txt (adds test tools); a production build
# uses the default and gets runtime packages only.
ARG REQUIREMENTS=requirements.txt

# Install dependencies first so this layer is cached until the requirements change.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
