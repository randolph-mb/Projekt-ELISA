
# main.py

import os
import sqlite3
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from openai import OpenAI
from dotenv import load_dotenv

# Lade Umgebungsvariablen
load_dotenv()

# --- ÄNDERUNG 1: Importiere den intelligenten Pfad und die init-Funktion ---
from database import DB_PATH, init_db

# --- Initialisierung ---
app = Flask(__name__)
app.secret_key = os.urandom(24) # Wichtig für Session-Management

# --- ÄNDERUNG 2: Stelle sicher, dass die DB beim App-Start existiert ---
# Dieser Code wird einmal ausgeführt, wenn die App auf Render startet.
init_db()

# OpenAI Client initialisieren
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Importiere LUMIs System-Prompt
from prompts import LUMI_SYSTEM_PROMPT

# --- Datenbank-Helferfunktionen ---
def get_db_connection():
    # --- ÄNDERUNG 3: Benutze den importierten, intelligenten Pfad ---
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- Login-Management & Decorator (Keine Änderungen hier) ---
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# --- Routen & API Endpunkte (Keine Änderungen hier, alles funktioniert automatisch) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form['password']
        if password == os.environ.get('APP_PASSWORD'):
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            error = 'Falsches Passwort. Versuch es nochmal.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    conn = get_db_connection()
    last_entry = conn.execute('SELECT date FROM daily_entries ORDER BY date DESC LIMIT 1').fetchone()
    conn.close()

    missed_day_prompt = None
    if last_entry:
        last_date = datetime.datetime.strptime(last_entry['date'], '%Y-%m-%d').date()
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        if last_date < yesterday:
            missed_day_prompt = f"Hey Elisa, ich sehe, dein letzter Eintrag war am {last_date.strftime('%d.%m')}. Gestern warst du nicht da. Alles okay bei dir? Was hast du stattdessen gemacht? Erzähl mal, dann überlegen wir, wie wir das gemeinsam aufholen."

    return render_template('index.html', missed_day_prompt=missed_day_prompt)


@app.route('/api/active_dates', methods=['GET'])
@login_required
def get_active_dates():
    conn = get_db_connection()
    dates = conn.execute('SELECT DISTINCT date FROM daily_entries').fetchall()
    conn.close()
    return jsonify([d['date'] for d in dates])


@app.route('/api/entry_for_date', methods=['GET'])
@login_required
def get_entry_for_date():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'error': 'Date parameter is missing'}), 400

    conn = get_db_connection()
    entry = conn.execute('SELECT id, briefing FROM daily_entries WHERE date = ?', (date_str,)).fetchone()

    if not entry:
        conn.close()
        return jsonify({'chat': [], 'briefing': ''})

    chat_history = conn.execute(
        'SELECT sender, message, timestamp FROM chat_messages WHERE entry_id = ? ORDER BY timestamp ASC', 
        (entry['id'],)
    ).fetchall()
    conn.close()

    return jsonify({
        'chat': [dict(row) for row in chat_history],
        'briefing': entry['briefing']
    })


@app.route('/api/chat', methods=['POST'])
@login_required
def handle_chat():
    data = request.json
    user_input = data.get('message')
    date_str = data.get('date', datetime.date.today().strftime('%Y-%m-%d'))

    conn = get_db_connection()
    entry = conn.execute('SELECT id FROM daily_entries WHERE date = ?', (date_str,)).fetchone()

    if not entry:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO daily_entries (date, student_input) VALUES (?, ?)', (date_str, user_input))
        conn.commit()
        entry_id = cursor.lastrowid
        conn.execute('INSERT INTO chat_messages (entry_id, sender, message) VALUES (?, ?, ?)', (entry_id, 'user', user_input))
        conn.commit()
    else:
        entry_id = entry['id']
        conn.execute('INSERT INTO chat_messages (entry_id, sender, message) VALUES (?, ?, ?)', (entry_id, 'user', user_input))
        conn.commit()

    history_rows = conn.execute('SELECT sender, message FROM chat_messages WHERE entry_id = ? ORDER BY timestamp ASC', (entry_id,)).fetchall()

    messages_for_api = [{"role": "system", "content": LUMI_SYSTEM_PROMPT}]
    for row in history_rows:
        role = "assistant" if row['sender'] == 'lumi' else "user"
        messages_for_api.append({"role": role, "content": row['message']})

    lumi_response = ""
    briefing_text = ""
    try:
        completion = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=messages_for_api
        )
        full_response = completion.choices[0].message.content
        lumi_response = full_response

        if "[BRIEFING_START]" in full_response:
            parts = full_response.split("[BRIEFING_START]")
            lumi_response = parts[0].strip()
            if "[BRIEFING_END]" in parts[1]:
                briefing_text = parts[1].split("[BRIEFING_END]")[0].strip()
                conn.execute('UPDATE daily_entries SET briefing = ? WHERE id = ?', (briefing_text, entry_id))
                conn.commit()

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        lumi_response = "Oh, da ist gerade was schiefgelaufen. Mein KI-Gehirn hat kurz Schluckauf. Können wir es gleich nochmal versuchen?"

    conn.close()

    return jsonify({'reply': lumi_response, 'briefing': briefing_text})


@app.route('/api/export', methods=['GET'])
@login_required
def export_briefings():
    conn = get_db_connection()
    entries = conn.execute('SELECT date, briefing FROM daily_entries WHERE briefing IS NOT NULL AND briefing != "" ORDER BY date ASC').fetchall()
    conn.close()

    export_data = "Lern-Briefings für Elisa\n==========================\n\n"
    for entry in entries:
        date_obj = datetime.datetime.strptime(entry['date'], '%Y-%m-%d')
        formatted_date = date_obj.strftime("%A, %d. %B %Y")
        export_data += f"--- {formatted_date} ---\n"
        export_data += f"{entry['briefing']}\n\n"

    return Response(
        export_data,
        mimetype="text/plain",
        headers={"Content-disposition": "attachment; filename=Lern-Briefings-Elisa.txt"}
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
