# Fichero: app.py (Corregido y Completo)
from flask import Flask, render_template, request, url_for, jsonify, redirect
from celery_worker import find_routes_task, celery
import pytz
from datetime import datetime
import pandas as pd
import requests
import io
import random

app = Flask(__name__)

# --- Carga inicial de datos para desplegables y frases ---
def cargar_datos_iniciales():
    lugares = []
    frases = ["El esfuerzo de hoy es el éxito de mañana."]
    try:
        GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1QConknaQ2O762EV3701kPtu2zsJBkYW6/export?format=csv&gid=151783393"
        headers = {"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"}
        response = requests.get(GOOGLE_SHEET_URL, headers=headers, timeout=10)
        response.raise_for_status()
        csv_content = response.text
        csv_data_io = io.StringIO(csv_content)
        df = pd.read_csv(csv_data_io)
        if "Origen" in df.columns and "Destino" in df.columns:
             lugares = sorted(pd.concat([df["Origen"], df["Destino"]]).dropna().unique())
    except Exception as e:
        print(f"Error al cargar lugares para el index: {e}")
        lugares = ["Error al cargar datos"]

    try:
        with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
            frases = json.load(f)
    except Exception:
        pass
        
    return lugares, frases

lugares_disponibles, frases_motivadoras = cargar_datos_iniciales()
# --------------------------------------------------------------------------

@app.route("/")
def index():
    frase = random.choice(frases_motivadoras)
    return render_template("index.html", lugares=lugares_disponibles, frase=frase, frases=frases_motivadoras)

@app.route("/buscar", methods=["POST"])
def buscar():
    form_data = request.form.to_dict()
    origen = form_data.get("origen")
    destino = form_data.get("destino")
    dia_seleccionado = form_data.get('dia_semana_selector', 'hoy')
    
    now_iso = datetime.now(pytz.timezone('Europe/Madrid')).isoformat()

    task = find_routes_task.delay(origen, destino, dia_seleccionado, form_data, now_iso)
    
    return redirect(url_for('resultados', task_id=task.id, origen=origen, destino=destino))

@app.route("/resultados/<task_id>")
def resultados(task_id):
    origen = request.args.get('origen')
    destino = request.args.get('destino')
    return render_template("resultado_espera.html", task_id=task_id, origen=origen, destino=destino)

@app.route("/estado/<task_id>")
def task_status(task_id):
    task = find_routes_task.AsyncResult(task_id)
    if task.state == 'PENDING' or task.state == 'STARTED':
        response = {'state': task.state}
    elif task.state == 'SUCCESS':
        resultados_html = render_template("_resultados_list.html", resultados=task.result)
        response = {'state': 'SUCCESS', 'html': resultados_html}
    else: # FAILURE
        response = {'state': 'FAILURE', 'status': str(task.info)}
    return jsonify(response)

if __name__ == "__main__":
    app.run(debug=True)
