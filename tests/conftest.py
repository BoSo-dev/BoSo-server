import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db, make_engine
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    application = create_app()

    def override_db():
        with Session(engine) as db:
            yield db

    application.dependency_overrides[get_db] = override_db
    with TestClient(application) as test_client:
        yield test_client
    engine.dispose()
