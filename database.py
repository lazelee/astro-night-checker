import sqlite3

# connect to local db and create logging table
conn = sqlite3.connect('astro_scheduler.db')
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS session_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        city TEXT,
        target TEXT,
        cloud_cover REAL,
        moon_phase TEXT,
        target_alt REAL,
        alert_sent INTEGER
    )
''')

conn.commit()
conn.close()

