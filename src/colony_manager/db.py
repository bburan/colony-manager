import os

from sqlalchemy_continuum import make_versioned
make_versioned(user_cls='User')
from colony_manager import models

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

engine = create_engine(os.environ['DATABASE_URL'])
Session = sessionmaker(engine)

# Emulate Flask-like query structure (should move away from this, but keep for
# now).
models.Base.session = scoped_session(Session)
models.Base.session.configure(bind=engine)
models.Base.query = models.Base.session.query_property()
