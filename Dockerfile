FROM python:3.13
RUN apt-get update && apt-get install -y git

WORKDIR /app/colony-manager/
COPY . .
RUN chmod -R 755 /app/colony-manager/

RUN pip install -e ".[gui]" gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "colony_manager_gui:create_app()"]
