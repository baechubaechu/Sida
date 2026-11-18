FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt /srv/
RUN pip install --no-cache-dir -r requirements.txt && mkdir /data && chown nobody /data
COPY __init__.py app.py tokens.py admin.py shares.py /srv/relay/
COPY static /srv/relay/static/
# The app's code for the ground and the 건축물대장 packs (context3d.shared_ground, ledger_pack.lookup):
# the repository's sida/ folder, copied next to this file as relay/sida/ by scripts/relay_bundle.py.
COPY sida /srv/sida/
# The share viewer's screen files (webui/app, only VIEWER_FILES), copied as relay/viewer/ by the same script.
COPY viewer /srv/viewer/
ENV SIDA_RELAY_DB=/data/relay.db
ENV SIDA_LEDGER_DIR=/ledger SIDA_TERRAIN_DIR=/terrain SIDA_VIEWER_DIR=/srv/viewer
VOLUME /data
EXPOSE 8000
USER nobody
CMD ["uvicorn", "relay.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
