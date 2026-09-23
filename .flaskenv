# Read by the flask CLI via python-dotenv (already a dependency) when a
# command is run from this directory, so `flask data refresh` works without
# repeating `--app colony_manager_gui:create_app`. The container gets the
# same value from ENV in the Dockerfile, since its workdir is /app rather
# than this repo and it would not find this file.
FLASK_APP=colony_manager_gui:create_app
