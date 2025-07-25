"""Database-backed checkpointing for LangGraph workflows."""

import json
import time
from typing import Any, Dict, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointMetadata

from workflows.models import WorkflowCheckpoint
from backend.core.database import get_db


class DatabaseCheckpointer(BaseCheckpointSaver):
    """Database-backed checkpointer for persistent state management."""
    
    def __init__(self, db_session_factory=None):
        self.db_session_factory = db_session_factory or get_db
    
    async def aget_checkpoint(
        self, 
        config: Dict[str, Any]
    ) -> Optional[Checkpoint]:
        """Retrieve the latest checkpoint for a thread."""
        thread_id = config["configurable"]["thread_id"]
        
        async for db in self.db_session_factory():
            try:
                # Get latest checkpoint for thread
                result = await db.execute(
                    select(WorkflowCheckpoint)
                    .where(WorkflowCheckpoint.thread_id == thread_id)
                    .order_by(WorkflowCheckpoint.created_at.desc())
                    .limit(1)
                )
                checkpoint_record = result.scalar_one_or_none()
                
                if not checkpoint_record:
                    return None
                
                # Convert to LangGraph Checkpoint format
                checkpoint = Checkpoint(
                    v=1,
                    id=checkpoint_record.checkpoint_id,
                    ts=checkpoint_record.created_at.isoformat(),
                    channel_values=checkpoint_record.state_data,
                    channel_versions={},
                    versions_seen={}
                )
                
                return checkpoint
                
            except Exception as e:
                print(f"Error retrieving checkpoint: {e}")
                return None
    
    async def aput_checkpoint(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata
    ) -> None:
        """Save a checkpoint to the database."""
        thread_id = config["configurable"]["thread_id"]
        
        async for db in self.db_session_factory():
            try:
                # Create checkpoint record
                checkpoint_record = WorkflowCheckpoint(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint.id,
                    state_data=checkpoint.channel_values,
                    iteration=metadata.get("iteration", 0),
                    checkpoint_metadata=metadata or {},
                    size_bytes=len(json.dumps(checkpoint.channel_values))
                )
                
                db.add(checkpoint_record)
                await db.commit()
                
            except Exception as e:
                await db.rollback()
                print(f"Error saving checkpoint: {e}")
                raise
    
    async def alist_checkpoints(
        self,
        config: Dict[str, Any],
        limit: Optional[int] = None,
        before: Optional[str] = None
    ) -> List[Checkpoint]:
        """List checkpoints for a thread."""
        thread_id = config["configurable"]["thread_id"]
        
        async for db in self.db_session_factory():
            try:
                query = select(WorkflowCheckpoint).where(
                    WorkflowCheckpoint.thread_id == thread_id
                ).order_by(WorkflowCheckpoint.created_at.desc())
                
                if before:
                    query = query.where(WorkflowCheckpoint.checkpoint_id < before)
                
                if limit:
                    query = query.limit(limit)
                
                result = await db.execute(query)
                checkpoint_records = result.scalars().all()
                
                checkpoints = []
                for record in checkpoint_records:
                    checkpoint = Checkpoint(
                        v=1,
                        id=record.checkpoint_id,
                        ts=record.created_at.isoformat(),
                        channel_values=record.state_data,
                        channel_versions={},
                        versions_seen={}
                    )
                    checkpoints.append(checkpoint)
                
                return checkpoints
                
            except Exception as e:
                print(f"Error listing checkpoints: {e}")
                return []
    
    async def save_workflow_state(
        self,
        thread_id: str,
        state_data: Dict[str, Any],
        iteration: int
    ) -> str:
        """Save workflow state with custom logic."""
        checkpoint_id = f"checkpoint_{thread_id}_{iteration}_{int(time.time())}"
        
        async for db in self.db_session_factory():
            try:
                checkpoint_record = WorkflowCheckpoint(
                    thread_id=thread_id,
                    checkpoint_id=checkpoint_id,
                    state_data=state_data,
                    iteration=iteration,
                    checkpoint_metadata={"custom_save": True},
                    size_bytes=len(json.dumps(state_data))
                )
                
                db.add(checkpoint_record)
                await db.commit()
                
                return checkpoint_id
                
            except Exception as e:
                await db.rollback()
                print(f"Error saving workflow state: {e}")
                raise
    
    async def load_workflow_state(
        self,
        thread_id: str,
        checkpoint_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Load workflow state from database."""
        async for db in self.db_session_factory():
            try:
                query = select(WorkflowCheckpoint).where(
                    WorkflowCheckpoint.thread_id == thread_id
                )
                
                if checkpoint_id:
                    query = query.where(WorkflowCheckpoint.checkpoint_id == checkpoint_id)
                else:
                    query = query.order_by(WorkflowCheckpoint.created_at.desc()).limit(1)
                
                result = await db.execute(query)
                checkpoint_record = result.scalar_one_or_none()
                
                if checkpoint_record:
                    return checkpoint_record.state_data
                
                return None
                
            except Exception as e:
                print(f"Error loading workflow state: {e}")
                return None
    
    async def cleanup_old_checkpoints(
        self,
        thread_id: str,
        keep_last: int = 10
    ) -> int:
        """Clean up old checkpoints, keeping only the most recent ones."""
        async for db in self.db_session_factory():
            try:
                # Get checkpoints to keep
                keep_query = select(WorkflowCheckpoint.id).where(
                    WorkflowCheckpoint.thread_id == thread_id
                ).order_by(
                    WorkflowCheckpoint.created_at.desc()
                ).limit(keep_last)
                
                keep_result = await db.execute(keep_query)
                keep_ids = [row[0] for row in keep_result.fetchall()]
                
                if not keep_ids:
                    return 0
                
                # Delete old checkpoints
                from sqlalchemy import delete
                delete_query = delete(WorkflowCheckpoint).where(
                    WorkflowCheckpoint.thread_id == thread_id,
                    ~WorkflowCheckpoint.id.in_(keep_ids)
                )
                
                result = await db.execute(delete_query)
                deleted_count = result.rowcount
                
                await db.commit()
                return deleted_count
                
            except Exception as e:
                await db.rollback()
                print(f"Error cleaning up checkpoints: {e}")
                return 0