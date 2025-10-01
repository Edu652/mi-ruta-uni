# Fichero: app.py (Completo y Modificado para Tareas en Segundo Plano)
from flask import Flask, render_template, request, url_for, jsonify, redirect
from celery_worker import find_routes_task, celery
import pytz
from datetime import datetime
import pandas as pd
import requests
import io
import random

app = Flask(__name__)

# --- Carga inicial de datos solo para los desplegables de la página de inicio ---
def cargar_lugares_y_frases():
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
        lugares = sorted(pd.concat([df["Origen"], df["Destino"]]).dropna().unique())
    except Exception as e:
        print(f"Error al cargar lugares para el index: {e}")
        lugares = ["Error al cargar"]

    try:
        with open("frases_motivadoras.json", "r", encoding="utf-8") as f:
            frases = json.load(f)
    except Exception:
        pass # Usamos la frase por defecto si falla
        
    return lugares, frases

lugares_disponibles, frases_motivadoras = cargar_lugares_y_frases()
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

    # Enviamos la tarea al worker y obtenemos el ID
    task = find_routes_task.delay(origen, destino, dia_seleccionado, form_data, now_iso)
    
    # Redirigimos a la página de espera
    return redirect(url_for('resultados', task_id=task.id, origen=origen, destino=destino))

@app.route("/resultados/<task_id>")
def resultados(task_id):
    origen = request.args.get('origen')
    destino = request.args.get('destino')
    # Esta página solo muestra el "avisador" y espera
    return render_template("resultado_espera.html", task_id=task_id, origen=origen, destino=destino)

@app.route("/estado/<task_id>")
def task_status(task_id):
    task = find_routes_task.AsyncResult(task_id)
    if task.state == 'PENDING' or task.state == 'STARTED':
        response = {'state': task.state}
    elif task.state == 'SUCCESS':
        # Cuando la tarea termina, renderizamos el HTML de los resultados
        # Pasamos los filtros del formulario original a la plantilla de resultados
        form_data = task.info.get('form_data', {}) if isinstance(task.info, dict) else {}
        # El resultado de la tarea es la lista de rutas
        resultados_html = render_template("_resultados_list.html", resultados=task.result)
        response = {
            'state': 'SUCCESS',
            'html': resultados_html
        }
    else: # Si algo sale mal
        response = {
            'state': 'FAILURE',
            'status': str(task.info)
        }
    return jsonify(response)

if __name__ == "__main__":
    app.run(debug=True)
