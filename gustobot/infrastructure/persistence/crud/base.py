"""
Base CRUD class with generic database operations.
"""

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, Union

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import Base, commit_session

ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Generic CRUD operations for database models.

    Provides standard create, read, update, delete operations that can be
    inherited by specific model CRUD classes.
    """

    def __init__(self, model: Type[ModelType]):
        """Initialize with a SQLAlchemy model class."""
        self.model = model

    def get(self, db: Session, id: Union[int, str]) -> Optional[ModelType]:
        """Get a single record by ID."""
        return db.get(self.model, id)

    def get_multi(self, db: Session, *, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """Get multiple records with pagination."""
        return db.query(self.model).offset(skip).limit(limit).all()

    def create(self, db: Session, *, obj_in: CreateSchemaType) -> ModelType:
        """Create a new record."""
        create_data = jsonable_encoder(obj_in)
        db_obj = self.model(**create_data)
        db.add(db_obj)
        commit_session(db)
        db.refresh(db_obj)
        return db_obj

    def update(
        self, db: Session, *, db_obj: ModelType, obj_in: Union[UpdateSchemaType, Dict[str, Any]]
    ) -> ModelType:
        """Update an existing record."""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for column in self.model.__mapper__.column_attrs:
            if column.key in update_data:
                setattr(db_obj, column.key, update_data[column.key])

        db.add(db_obj)
        commit_session(db)
        db.refresh(db_obj)
        return db_obj

    def delete(self, db: Session, *, id: Union[int, str]) -> Optional[ModelType]:
        """Delete a record by ID."""
        record = db.get(self.model, id)
        if record is None:
            return None
        db.delete(record)
        commit_session(db)
        return record
