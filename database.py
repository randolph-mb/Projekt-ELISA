    # database.py

    import os
    import sqlite3

    # --- DER NEUE, INTELLIGENTE TEIL ---
    # Der Mount Path, den du bei Render für die Disk eingerichtet hast
    RENDER_DATA_DIR = "/var/data"

    # Prüfe, ob wir auf dem Render-Server laufen (indem wir schauen, ob der Ordner existiert)
    if os.path.exists(RENDER_DATA_DIR):
        # Ja, wir sind auf Render: Baue den Pfad zur DB-Datei im persistenten Speicher zusammen
        DB_PATH = os.path.join(RENDER_DATA_DIR, "learning_data.db")
        print(f"INFO: Running on Render. Using database at: {DB_PATH}")
    else:
        # Nein, wir sind lokal: Benutze den lokalen Dateinamen wie bisher
        DB_PATH = "learning_data.db"
        print(f"INFO: Running locally. Using database at: {DB_PATH}")
    # --- ENDE DES NEUEN TEILS ---


    def init_db():
        # Wir benutzen jetzt die neue, intelligente Variable DB_PATH
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Tabelle für die täglichen Einträge und Briefings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS daily_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                student_input TEXT,
                briefing TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Tabelle für die einzelnen Chat-Nachrichten
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER,
                sender TEXT NOT NULL, -- 'user' oder 'lumi'
                message TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (entry_id) REFERENCES daily_entries(id)
            )
        ''')

        conn.commit()
        conn.close()
        print("Database initialized successfully.")

    if __name__ == '__main__':
        init_db()