FROM python:3.13-slim
RUN apt-get update && apt-get install -y git

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir .[gui]
RUN chmod -R 755 /app
CMD ["python", "run.py"]
