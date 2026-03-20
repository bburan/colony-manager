FROM python:3.13
RUN apt-get update && apt-get install -y git

WORKDIR /app/colony-manager/
COPY . .
RUN chmod -R 755 /app/colony-manager/

RUN pip install -e ".[gui]"
CMD ["python", "run.py", "--debug"]
