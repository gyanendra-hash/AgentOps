FROM python:3.11-slim

WORKDIR /srv

COPY libs/agentops_common /srv/libs/agentops_common
COPY services/scheduler/requirements.txt /srv/requirements.txt

RUN pip install --no-cache-dir -r /srv/requirements.txt \
    && pip install --no-cache-dir -e /srv/libs/agentops_common

COPY services/scheduler/app /srv/app
COPY services/scheduler/migrations /srv/migrations

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
