"""ES Document CRUD operations."""
from datetime import datetime
from . import get_db_connection, get_db_read


def create_es_document(data: dict) -> int:
    """Create a new ES document record."""
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        # Ensure photo_path column exists (safe migration)
        try:
            conn.execute("ALTER TABLE es_documents ADD COLUMN photo_path TEXT DEFAULT ''")
            conn.commit()
        except Exception:
            pass  # Column already exists

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO es_documents (title, file_path, file_type, raw_text,
                                      parsed_data, is_template, photo_path,
                                      created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('title', ''),
            data.get('file_path'),
            data.get('file_type'),
            data.get('raw_text'),
            data.get('parsed_data'),
            data.get('is_template', 0),
            data.get('photo_path', ''),
            now, now
        ))
        doc_id = cursor.lastrowid
        conn.commit()
    return doc_id


def get_es_document(doc_id: int) -> dict | None:
    """Get a single ES document by ID."""
    with get_db_read() as conn:
        row = conn.execute("SELECT * FROM es_documents WHERE id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def get_all_es_documents(templates_only=False) -> list:
    """Get all ES documents, optionally filtered to templates only."""
    with get_db_read() as conn:
        query = "SELECT * FROM es_documents"
        if templates_only:
            query += " WHERE is_template = 1"
        query += " ORDER BY updated_at DESC"
        rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


def update_es_document(doc_id: int, data: dict) -> bool:
    """Update an ES document."""
    with get_db_connection() as conn:
        fields = []
        values = []
        for key in ['title', 'file_path', 'file_type', 'raw_text', 'parsed_data', 'is_template', 'photo_path']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if not fields:
            return False
        fields.append("updated_at = ?")
        values.append(datetime.now().isoformat())
        values.append(doc_id)
        conn.execute(f"UPDATE es_documents SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    return True


def delete_es_document(doc_id: int):
    """Delete an ES document."""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM es_documents WHERE id = ?", (doc_id,))
        conn.commit()
