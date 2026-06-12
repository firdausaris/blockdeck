FROM python:3.12-alpine

RUN pip install --no-cache-dir fastapi uvicorn docker

WORKDIR /app
COPY app.py .
COPY static ./static

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
