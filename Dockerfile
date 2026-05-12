FROM python:3.13
RUN apt-get update && apt-get install -y git

RUN mkdir -p /app
RUN mkdir -p /volume1/data
RUN groupadd -g 100 -o synousers
RUN useradd -m -u 1027 -g 100 -o -s /bin/bash mmm

COPY ./app /app
RUN chmod -R 755 /app
WORKDIR /app
RUN pip install -e "./colony-manager[gui]" -e "./mmm-db" gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "colony_manager_gui:create_app()"]
