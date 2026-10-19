FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt /srv/
RUN pip install --no-cache-dir -r requirements.txt
COPY __init__.py app.py /srv/collector/
EXPOSE 8000
CMD ["uvicorn", "collector.app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
