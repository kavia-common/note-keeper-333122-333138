#!/usr/bin/env python3
"""Initialize SQLite database for notes_database.

This script is the canonical entrypoint for creating/upgrading the local SQLite schema
used by the notes application.

Contract:
- Inputs:
  - Uses a local SQLite file named "myapp.db" in the current working directory.
- Outputs:
  - Ensures the DB file exists and has the expected tables + indexes.
  - Ensures app metadata exists in app_info.
  - Inserts a small seed dataset (idempotent).
  - Writes/updates db_connection.txt with the correct connection info.
  - Writes/updates db_visualizer/sqlite.env for the DB viewer.
- Errors:
  - Raises sqlite3.Error if schema creation fails (printed to console by default).
- Side effects:
  - Creates/updates myapp.db, db_connection.txt, and db_visualizer/sqlite.env.
"""

import os
import sqlite3
from typing import Iterable

DB_NAME = "myapp.db"
DB_USER = "kaviasqlite"  # Not used for SQLite, but kept for consistency
DB_PASSWORD = "kaviadefaultpassword"  # Not used for SQLite, but kept for consistency
DB_PORT = "5000"  # Not used for SQLite, but kept for consistency


def _execute_statements(cursor: sqlite3.Cursor, statements: Iterable[str]) -> None:
    """Execute SQL statements sequentially, adding context on failure."""
    for stmt in statements:
        try:
            cursor.execute(stmt)
        except sqlite3.Error as e:
            # Add useful context for debugging schema issues.
            raise sqlite3.Error(f"Failed executing SQL: {stmt}\nOriginal error: {e}") from e


def _ensure_pragmas(cursor: sqlite3.Cursor) -> None:
    """Ensure SQLite pragmas we rely on."""
    cursor.execute("PRAGMA foreign_keys = ON")


def _create_schema(cursor: sqlite3.Cursor) -> None:
    """Create tables and indexes for the notes app.

    Schema overview:
    - notes: primary entity (title/content + timestamps).
    - tags: optional tag dictionary.
    - note_tags: many-to-many join between notes and tags.

    Search support:
    - Indexes on notes.title, notes.updated_at, tags.name, join table columns.
    - NOTE: For advanced full-text search, consider adding SQLite FTS5 virtual tables.
            This implementation keeps portability and simplicity, using LIKE-based search
            with basic indexes.
    """
    ddl = [
        # App metadata
        """
        CREATE TABLE IF NOT EXISTS app_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # Notes table
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # Tags table (optional feature)
        """
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # Join table for note <-> tags
        """
        CREATE TABLE IF NOT EXISTS note_tags (
            note_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (note_id, tag_id),
            FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
        """,
        # Keep the template-provided users table if it exists in older DBs; harmless to keep.
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        # Indexes for common operations
        "CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title)",
        "CREATE INDEX IF NOT EXISTS idx_notes_updated_at ON notes(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name)",
        "CREATE INDEX IF NOT EXISTS idx_note_tags_note_id ON note_tags(note_id)",
        "CREATE INDEX IF NOT EXISTS idx_note_tags_tag_id ON note_tags(tag_id)",
        # Trigger to auto-update updated_at on note updates
        """
        CREATE TRIGGER IF NOT EXISTS trg_notes_updated_at
        AFTER UPDATE ON notes
        FOR EACH ROW
        BEGIN
            UPDATE notes
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = OLD.id;
        END
        """,
    ]
    _execute_statements(cursor, ddl)


def _seed_data(conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> None:
    """Insert an idempotent seed dataset useful for demos and smoke tests."""
    # App info metadata
    app_info_rows = [
        ("project_name", "notes_database"),
        ("version", "1.0.0"),
        ("author", "Kavia"),
        ("description", "Local SQLite database for the Note Keeper app."),
    ]
    for key, value in app_info_rows:
        cursor.execute(
            "INSERT OR REPLACE INTO app_info (key, value) VALUES (?, ?)",
            (key, value),
        )

    # If notes already exist, don't add duplicates.
    cursor.execute("SELECT COUNT(1) FROM notes")
    notes_count = int(cursor.fetchone()[0])
    if notes_count > 0:
        return

    # Insert seed notes
    seed_notes = [
        (
            "Welcome to Note Keeper",
            "This is a sample note. You can create, edit, search, and delete notes.",
        ),
        (
            "Search tips",
            "Try searching by keywords in the title or content. Tag filtering is optional.",
        ),
        (
            "Markdown?",
            "If the frontend supports it, you can write in Markdown style, but the DB stores plain text.",
        ),
    ]
    note_ids = []
    for title, content in seed_notes:
        cursor.execute(
            "INSERT INTO notes (title, content) VALUES (?, ?)",
            (title, content),
        )
        note_ids.append(cursor.lastrowid)

    # Insert seed tags + mappings (optional tags feature)
    seed_tags = ["getting-started", "tips", "demo"]
    tag_ids = {}
    for name in seed_tags:
        cursor.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        cursor.execute("SELECT id FROM tags WHERE name = ?", (name,))
        tag_ids[name] = int(cursor.fetchone()[0])

    # Map tags to notes
    mappings = [
        (note_ids[0], tag_ids["getting-started"]),
        (note_ids[1], tag_ids["tips"]),
        (note_ids[2], tag_ids["demo"]),
        (note_ids[1], tag_ids["demo"]),
    ]
    for note_id, tag_id in mappings:
        cursor.execute(
            "INSERT OR IGNORE INTO note_tags (note_id, tag_id) VALUES (?, ?)",
            (note_id, tag_id),
        )

    conn.commit()


def _write_connection_files(db_path: str) -> None:
    """Write db_connection.txt and db_visualizer/sqlite.env in the existing format."""
    current_dir = os.getcwd()
    connection_string = f"sqlite:////{db_path}" if db_path.startswith("/") else f"sqlite:///{db_path}"

    # db_connection.txt is treated as the canonical documentation for connections.
    try:
        with open("db_connection.txt", "w", encoding="utf-8") as f:
            f.write("# SQLite connection methods:\n")
            f.write(f"# Python: sqlite3.connect('{DB_NAME}')\n")
            f.write(f"# Connection string: {connection_string}\n")
            f.write(f"# File path: {current_dir}/{DB_NAME}\n")
        print("Connection information saved to db_connection.txt")
    except Exception as e:
        print(f"Warning: Could not save connection info: {e}")

    # Create environment variables file for Node.js viewer
    if not os.path.exists("db_visualizer"):
        os.makedirs("db_visualizer", exist_ok=True)
        print("Created db_visualizer directory")

    try:
        with open("db_visualizer/sqlite.env", "w", encoding="utf-8") as f:
            f.write(f'export SQLITE_DB="{db_path}"\n')
        print("Environment variables saved to db_visualizer/sqlite.env")
    except Exception as e:
        print(f"Warning: Could not save environment variables: {e}")


def main() -> None:
    """Run schema initialization/upgrade and seed data."""
    print("Starting SQLite setup...")

    db_exists = os.path.exists(DB_NAME)
    if db_exists:
        print(f"SQLite database already exists at {DB_NAME}")
        try:
            conn = sqlite3.connect(DB_NAME)
            conn.execute("SELECT 1")
            conn.close()
            print("Database is accessible and working.")
        except Exception as e:
            print(f"Warning: Database exists but may be corrupted: {e}")
    else:
        print("Creating new SQLite database...")

    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        _ensure_pragmas(cursor)
        _create_schema(cursor)
        _seed_data(conn, cursor)
        conn.commit()
    finally:
        conn.close()

    # Stats for debugging
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        table_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM notes")
        notes_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM tags")
        tags_count = int(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM note_tags")
        note_tags_count = int(cursor.fetchone()[0])
    finally:
        conn.close()

    db_path = os.path.abspath(DB_NAME)
    _write_connection_files(db_path)

    print("\nSQLite setup complete!")
    print(f"Database: {DB_NAME}")
    print(f"Location: {db_path}")
    print("")
    print("To use with Node.js viewer, run: source db_visualizer/sqlite.env")
    print("\nTo connect to the database, use one of the following methods:")
    print(f"1. Python: sqlite3.connect('{DB_NAME}')")
    print(f"2. File path: {db_path}")
    print("")
    print("Database statistics:")
    print(f"  Tables: {table_count}")
    print(f"  Notes: {notes_count}")
    print(f"  Tags: {tags_count}")
    print(f"  Note-Tag links: {note_tags_count}")

    # If sqlite3 CLI is available, show how to use it
    try:
        import subprocess

        result = subprocess.run(["which", "sqlite3"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            print("")
            print("SQLite CLI is available. You can also use:")
            print(f"  sqlite3 {DB_NAME}")
    except Exception:
        pass

    print("\nScript completed successfully.")


if __name__ == "__main__":
    main()
