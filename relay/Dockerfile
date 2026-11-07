FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt /srv/
RUN pip install --no-cache-dir -r requirements.txt && mkdir /data && chown nobody /data
COPY __init__.py app.py tokens.py admin.py /srv/relay/
COPY static /srv/relay/static/
ENV SIDA_RELAY_DB=/data/relay.db
VOLUME /data
EXPOSE 8000
USER nobody
CMD ["uvicorn", "relay.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
