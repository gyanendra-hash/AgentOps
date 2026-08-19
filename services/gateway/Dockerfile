FROM python:3.11-slim

WORKDIR /srv

COPY libs/agentops_common /srv/libs/agentops_common
COPY services/gateway/requirements.txt /srv/requirements.txt

RUN pip install --no-cache-dir -r /srv/requirements.txt \
    && pip install --no-cache-dir -e /srv/libs/agentops_common

COPY services/gateway/app /srv/app

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
