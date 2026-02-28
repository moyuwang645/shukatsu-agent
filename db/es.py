"""ES Document CRUD operations."""
from datetime import datetime
from . import get_db


def create_es_document(data: dict) -> int:
    """Create a new ES document record."""
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO es_documents (title, file_path, file_type, raw_text,
                                  parsed_data, is_template, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get('title', ''),
        data.get('file_path'),
        data.get('file_type'),
        data.get('raw_text'),
        data.get('parsed_data'),
        data.get('is_template', 0),
        now, now
    ))
    doc_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return doc_id


def get_es_document(doc_id: int) -> dict | None:
    """Get a single ES document by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM es_documents WHERE id = ?", (doc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_es_documents(templates_only=False) -> list:
    """Get all ES documents, optionally filtered to templates only."""
    conn = get_db()
    query = "SELECT * FROM es_documents"
    if templates_only:
        query += " WHERE is_template = 1"
    query += " ORDER BY updated_at DESC"
    rows = conn.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_es_document(doc_id: int, data: dict) -> bool:
    """Update an ES document."""
    conn = get_db()
    fields = []
    values = []
    for key in ['title', 'file_path', 'file_type', 'raw_text', 'parsed_data', 'is_template']:
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        conn.close()
        return False
    fields.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(doc_id)
    conn.execute(f"UPDATE es_documents SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()
    return True


def delete_es_document(doc_id: int):
    """Delete an ES document."""
    conn = get_db()
    conn.execute("DELETE FROM es_documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()
