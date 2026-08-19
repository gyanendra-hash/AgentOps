FROM python:3.11-slim

WORKDIR /srv

COPY libs/agentops_common /srv/libs/agentops_common
COPY services/rate_limiter/requirements.txt /srv/requirements.txt

RUN pip install --no-cache-dir -r /srv/requirements.txt \
    && pip install --no-cache-dir -e /srv/libs/agentops_common

COPY services/rate_limiter/app /srv/app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
