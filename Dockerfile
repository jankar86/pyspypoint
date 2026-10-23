FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m pip install --no-cache-dir requests

COPY spypoint/ ./spypoint/
COPY smoke_test.py ./smoke_test.py
COPY archive.py ./archive.py
COPY poller.py ./poller.py

USER 65532:65532

CMD ["python", "poller.py"]
