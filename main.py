import os
import sqlite3
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, Response
from openai import OpenAI
from dotenv import load_dotenv

# Lade Umgebungsvariablen (für lokale Entwicklung) und Secrets (für Replit)
load_dotenv()

# --- Initialisierung ---
app = Flask(__name__)
app.secret_key = os.urandom(24) # Wichtig für Session-Management
DB_NAME = 'learning_data.db'

# OpenAI Client initialisieren
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

# Importiere LUMIs System-Prompt
from prompts import LUMI_SYSTEM_PROMPT

# --- Datenbank-Helferfunktionen ---
def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# --- Login-Management & Decorator ---
def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# --- Routen ---
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

# --- API Endpunkte für das Frontend ---

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

    # Wenn kein Eintrag für den Tag existiert, erstelle einen
    if not entry:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO daily_entries (date, student_input) VALUES (?, ?)', (date_str, user_input))
        conn.commit()
        entry_id = cursor.lastrowid
        # Speichere die erste Nachricht des Nutzers
        conn.execute('INSERT INTO chat_messages (entry_id, sender, message) VALUES (?, ?, ?)', (entry_id, 'user', user_input))
        conn.commit()
    else:
        entry_id = entry['id']
        # Speichere die neue Nachricht des Nutzers
        conn.execute('INSERT INTO chat_messages (entry_id, sender, message) VALUES (?, ?, ?)', (entry_id, 'user', user_input))
        conn.commit()

    # Hole die komplette Chat-Historie für den Kontext
    history_rows = conn.execute('SELECT sender, message FROM chat_messages WHERE entry_id = ? ORDER BY timestamp ASC', (entry_id,)).fetchall()

    messages_for_api = [{"role": "system", "content": LUMI_SYSTEM_PROMPT}]
    for row in history_rows:
        role = "assistant" if row['sender'] == 'lumi' else "user"
        messages_for_api.append({"role": role, "content": row['message']})

    # Rufe die OpenAI API auf
    try:
        completion = client.chat.completions.create(
            model="gpt-4-turbo",
            messages=messages_for_api
        )
        lumi_response = completion.choices[0].message.content

        # Speichere LUMIs Antwort
        conn.execute('INSERT INTO chat_messages (entry_id, sender, message) VALUES (?, ?, ?)', (entry_id, 'lumi', lumi_response))
        conn.commit()

        # Prüfe, ob ein Briefing generiert wurde und speichere es
        if "[BRIEFING_START]" in lumi_response:
            # Extrahiere das Briefing sauber
            briefing_text = lumi_response.split("[BRIEFING_START]")[1].split("[BRIEFING_END]")[0].strip()
            conn.execute('UPDATE daily_entries SET briefing = ? WHERE id = ?', (briefing_text, entry_id))
            conn.commit()

            # Sende nur die Antwort ohne die Briefing-Tags an das Frontend
            lumi_response = lumi_response.split("[BRIEFING_START]")[0].strip()

    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        lumi_response = "Oh, da ist gerade was schiefgelaufen. Mein KI-Gehirn hat kurz Schluckauf. Können wir es gleich nochmal versuchen?"

    conn.close()

    # Lade das finale Briefing, falls es gerade erstellt wurde
    final_briefing = ""
    if "[BRIEFING_START]" in completion.choices[0].message.content:
         final_briefing = completion.choices[0].message.content.split("[BRIEFING_START]")[1].split("[BRIEFING_END]")[0].strip()

    return jsonify({'reply': lumi_response, 'briefing': final_briefing})


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

# --- App Start ---
if __name__ == '__main__':
    from database import init_db
    init_db() # Stellt sicher, dass die DB existiert
    app.run(host='0.0.0.0', port=5000, debug=True)