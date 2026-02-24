FROM python:3.13-slim
WORKDIR /app

COPY . .
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN chmod -R 755 /app
CMD ["python", "run.py"]
