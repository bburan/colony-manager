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
# docker-compose bind-mounts the live source tree over /app at run time, so
# the entrypoint has to live outside /app to survive that mount. It
# regenerates the editable installs against the mounted source, then drops
# from root to the unprivileged runtime user.
COPY ./app/colony-manager/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "colony_manager_gui:create_app()"]
