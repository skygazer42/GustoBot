"""Independent candidate generations and transactional publication metadata."""

from sqlalchemy.engine import Connection

from gustobot.infrastructure.core.database import Base
from gustobot.infrastructure.persistence.db.models.semantic_index import (
    SemanticIndexGeneration,
    SemanticIndexPublication,
)

revision = "0003_semantic_index_publication"
description = "Add scoped candidate generations, leases and publication pointers"


def upgrade(connection: Connection) -> None:
    for model in (SemanticIndexGeneration, SemanticIndexPublication):
        Base.metadata.tables[model.__tablename__].create(connection, checkfirst=True)
