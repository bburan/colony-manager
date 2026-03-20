from sqlalchemy_continuum import make_versioned
make_versioned(user_cls='User')
from colony_manager import models
from sqlalchemy.orm import scoped_session, sessionmaker

models.Base.session = scoped_session(sessionmaker())
models.Base.query = Base.session.query_property()
