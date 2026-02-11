"""
Screenshot OCR v2.0 — Database Module
SQLite-based history tracking for processing jobs.
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'history.db')

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input_path TEXT,
            output_path TEXT,
            total INTEGER DEFAULT 0,
            success INTEGER DEFAULT 0,
            failed INTEGER DEFAULT 0,
            duration TEXT,
            timestamp TEXT,
            log_file TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER,
            filename TEXT,
            input_path TEXT,
            ocr_text TEXT,
            resolved INTEGER DEFAULT 0,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    ''')
    conn.commit()
    conn.close()

def record_job(input_path, output_path, total, success, failed, duration, log_file):
    """Save a completed job to history."""
    conn = _get_conn()
    cur = conn.execute(
        'INSERT INTO jobs (input_path, output_path, total, success, failed, duration, timestamp, log_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (input_path, output_path, total, success, failed, duration, datetime.now().isoformat(), log_file)
    )
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    return job_id

def record_failure(job_id, filename, input_path, ocr_text):
    """Save a failed image for later review."""
    conn = _get_conn()
    conn.execute(
        'INSERT INTO failures (job_id, filename, input_path, ocr_text) VALUES (?, ?, ?, ?)',
        (job_id, filename, input_path, ocr_text)
    )
    conn.commit()
    conn.close()

def get_history(limit=50):
    """Get recent processing jobs."""
    conn = _get_conn()
    rows = conn.execute(
        'SELECT * FROM jobs ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_failures(job_id=None):
    """Get unresolved failed images."""
    conn = _get_conn()
    if job_id:
        rows = conn.execute(
            'SELECT * FROM failures WHERE job_id = ? AND resolved = 0 ORDER BY id', (job_id,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM failures WHERE resolved = 0 ORDER BY id DESC LIMIT 100'
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def resolve_failure(failure_id):
    """Mark a failure as resolved."""
    conn = _get_conn()
    conn.execute('UPDATE failures SET resolved = 1 WHERE id = ?', (failure_id,))
    conn.commit()
    conn.close()

def get_failure_by_filename(filename):
    """Find an unresolved failure by filename."""
    conn = _get_conn()
    row = conn.execute(
        'SELECT * FROM failures WHERE filename = ? AND resolved = 0 ORDER BY id DESC LIMIT 1',
        (filename,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_job(job_id):
    """Delete a job and its failures."""
    conn = _get_conn()
    conn.execute('DELETE FROM failures WHERE job_id = ?', (job_id,))
    conn.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
    conn.commit()
    conn.close()

# Initialize on import
init_db()
