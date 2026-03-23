"""
SQLite database module for survey persistence with autosave functionality.

NOTE: On Streamlit Cloud, the database file is ephemeral and will be lost
on app restart. For production, consider:
1. Export draft as JSON download before closing browser
2. Migrate to persistent database (PostgreSQL, Supabase, etc.)
3. Store drafts in browser localStorage as backup
"""

import sqlite3
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from utils.draft_state import has_meaningful_draft_data
from utils.logger import setup_logger

logger = setup_logger(__name__)


class SurveyDatabase:
    """
    Manages SQLite database for survey drafts and completed surveys.
    
    Handles concurrent access gracefully with timeout-based locking.
    All operations are logged for debugging and audit purposes.
    """
    
    def __init__(self, db_path: str = "data/surveys.db"):
        """
        Initialize database connection and create tables if needed.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        
        # Ensure data directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Initialize database schema
        self._init_db()
        logger.info(f"Database initialized at {db_path}")
    
    def _init_db(self) -> None:
        """Create surveys table if it doesn't exist."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS surveys (
                    id TEXT PRIMARY KEY,
                    make TEXT,
                    model TEXT,
                    store_name TEXT,
                    technician_name TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    data TEXT,
                    status TEXT DEFAULT 'draft',
                    pdf_path TEXT,
                    pdf_filename TEXT
                )
            """)
            
            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_status 
                ON surveys(status)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_updated_at 
                ON surveys(updated_at DESC)
            """)
            
            conn.commit()
            conn.close()
            
            logger.info("Database schema initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database schema", extra={"error": str(e)}, exc_info=True)
            raise
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get database connection with proper timeout and isolation settings.
        
        Returns:
            SQLite connection object
        """
        # Use 10 second timeout to handle concurrent access
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        # Use WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _extract_summary_fields(self, data: Dict[str, Any]) -> Tuple[str, str, str, str]:
        form_data = data.get("form_data")
        if not isinstance(form_data, dict):
            form_data = {}

        make = str(data.get("make", "") or "")
        model = str(data.get("model", "") or "")
        store_name = str(data.get("store_name") or form_data.get("store_name") or "")
        technician_name = str(data.get("technician_name") or form_data.get("technician_name") or "")
        return make, model, store_name, technician_name
    
    def save_draft(self, survey_id: str, data: Dict[str, Any]) -> bool:
        """
        Save or update a survey draft.
        
        Uses INSERT OR REPLACE to handle both new and existing surveys.
        Extracts key fields for easy querying while storing full data as JSON.
        
        Args:
            survey_id: Unique survey identifier (UUID)
            data: Complete survey data dictionary
            
        Returns:
            True if save succeeded, False otherwise
        """
        try:
            if not has_meaningful_draft_data(data):
                logger.info("Skipped blank draft save", extra={"survey_id": survey_id})
                return False

            # Extract key fields for database columns
            make, model, store_name, technician_name = self._extract_summary_fields(data)
            
            # Serialize full data as JSON
            data_json = json.dumps(data)
            
            # Get current timestamp
            now = datetime.now().isoformat()
            
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if survey already exists to determine created_at
            cursor.execute("SELECT created_at FROM surveys WHERE id = ?", (survey_id,))
            existing = cursor.fetchone()
            
            if existing:
                created_at = existing[0]
            else:
                created_at = now
            
            # Use INSERT OR REPLACE for upsert behavior
            cursor.execute("""
                INSERT OR REPLACE INTO surveys 
                (id, make, model, store_name, technician_name, created_at, updated_at, data, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """, (survey_id, make, model, store_name, technician_name, created_at, now, data_json))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Draft saved successfully", extra={
                "survey_id": survey_id,
                "make": make,
                "model": model,
                "store_name": store_name
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to save draft", extra={
                "survey_id": survey_id,
                "error": str(e)
            }, exc_info=True)
            return False
    
    def load_draft(self, survey_id: str) -> Optional[Dict[str, Any]]:
        """
        Load a survey draft by ID.
        
        Args:
            survey_id: Unique survey identifier
            
        Returns:
            Survey data dictionary if found, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT data FROM surveys WHERE id = ?", (survey_id,))
            result = cursor.fetchone()
            
            conn.close()
            
            if result:
                data = json.loads(result[0])
                logger.info(f"Draft loaded successfully", extra={"survey_id": survey_id})
                return data
            else:
                logger.warning(f"Draft not found", extra={"survey_id": survey_id})
                return None
                
        except Exception as e:
            logger.error(f"Failed to load draft", extra={
                "survey_id": survey_id,
                "error": str(e)
            }, exc_info=True)
            return None
    
    def list_drafts(self, limit: int = 50) -> List[Tuple]:
        """
        List recent survey drafts.
        
        Args:
            limit: Maximum number of drafts to return
            
        Returns:
            List of tuples: (id, store_name, make, model, updated_at, technician_name)
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, store_name, make, model, updated_at, technician_name, data
                FROM surveys
                WHERE status = 'draft'
                ORDER BY updated_at DESC
            """)
            
            raw_results = cursor.fetchall()
            conn.close()

            results: List[Tuple] = []
            for survey_id, store_name, make, model, updated_at, technician_name, data_json in raw_results:
                try:
                    payload = json.loads(data_json)
                except Exception:
                    payload = {}
                if not has_meaningful_draft_data(payload):
                    continue
                results.append((survey_id, store_name, make, model, updated_at, technician_name))
                if len(results) >= limit:
                    break
            
            logger.info(f"Listed {len(results)} drafts")
            return results
            
        except Exception as e:
            logger.error(f"Failed to list drafts", extra={"error": str(e)}, exc_info=True)
            return []
    
    def mark_complete(self, survey_id: str, pdf_filename: str) -> bool:
        """
        Mark a survey as complete after PDF generation.
        
        Args:
            survey_id: Unique survey identifier
            pdf_filename: Generated PDF filename
            
        Returns:
            True if update succeeded, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            cursor.execute("""
                UPDATE surveys
                SET status = 'complete',
                    pdf_filename = ?,
                    updated_at = ?
                WHERE id = ?
            """, (pdf_filename, now, survey_id))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Survey marked complete", extra={
                "survey_id": survey_id,
                "pdf_filename": pdf_filename
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to mark survey complete", extra={
                "survey_id": survey_id,
                "error": str(e)
            }, exc_info=True)
            return False
    
    def delete_draft(self, survey_id: str) -> bool:
        """
        Delete a survey draft.
        
        Args:
            survey_id: Unique survey identifier
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM surveys WHERE id = ?", (survey_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Draft deleted", extra={"survey_id": survey_id})
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete draft", extra={
                "survey_id": survey_id,
                "error": str(e)
            }, exc_info=True)
            return False
    
    def find_recent_draft(self, make: str, model: str, limit_hours: int = 24) -> Optional[str]:
        """
        Find the most recent draft for a given make/model combination.
        
        Useful for offering "Resume Draft" functionality.
        
        Args:
            make: Equipment make
            model: Equipment model
            limit_hours: Only return drafts from within this many hours
            
        Returns:
            Survey ID if found, None otherwise
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Calculate cutoff time
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(hours=limit_hours)).isoformat()
            
            cursor.execute("""
                SELECT id, data
                FROM surveys
                WHERE make = ? AND model = ? AND status = 'draft' AND updated_at > ?
                ORDER BY updated_at DESC
            """, (make, model, cutoff))
            
            rows = cursor.fetchall()
            conn.close()

            for survey_id, data_json in rows:
                try:
                    payload = json.loads(data_json)
                except Exception:
                    payload = {}
                if not has_meaningful_draft_data(payload):
                    continue
                logger.info(f"Found recent draft", extra={
                    "survey_id": survey_id,
                    "make": make,
                    "model": model
                })
                return survey_id
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to find recent draft", extra={
                "make": make,
                "model": model,
                "error": str(e)
            }, exc_info=True)
            return None
