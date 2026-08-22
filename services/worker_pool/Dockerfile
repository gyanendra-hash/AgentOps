FROM python:3.11-slim

WORKDIR /srv

COPY libs/agentops_common /srv/libs/agentops_common
COPY services/worker_pool/requirements.txt /srv/requirements.txt

RUN pip install --no-cache-dir -r /srv/requirements.txt \
    && pip install --no-cache-dir -e /srv/libs/agentops_common

COPY services/worker_pool/app /srv/app

EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
