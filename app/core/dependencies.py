from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.db import get_db

# Finish commit/rollback before sending a successful HTTP response.
DbSession = Annotated[Session, Depends(get_db, scope="function")]
