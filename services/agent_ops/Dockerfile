FROM python:3.11-slim

WORKDIR /srv

COPY libs/agentops_common /srv/libs/agentops_common
COPY services/agent_ops/requirements.txt /srv/requirements.txt

RUN pip install --no-cache-dir -r /srv/requirements.txt \
    && pip install --no-cache-dir -e /srv/libs/agentops_common

COPY services/agent_ops/app /srv/app
COPY services/agent_ops/migrations /srv/migrations
COPY services/agent_ops/runbook /srv/runbook

EXPOSE 8004

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
