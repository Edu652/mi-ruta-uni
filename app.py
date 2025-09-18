
from flask import Flask, render_template, request
import pandas as pd
import random

app = Flask(__name__)
rutas = pd.read_excel('rutas.xlsx', engine='openpyxl')

frases = [
    '¡Cada paso te acerca a tu meta! 🧠',
    'Confía en tu proceso, estás aprendiendo. 💪',
    'La motivación viene del propósito. ¿Cuál es el tuyo? 🎯',
    'Respira, enfócate y sigue adelante. 🌿',
    'Tu esfuerzo de hoy es tu éxito de mañana. 🚀',
    'La mente es poderosa, úsala a tu favor. 🧘‍♀️',
    '¡Vamos, que tú puedes! 💥',
    'No hay camino sin tropiezos, pero sí sin rendirse. 🛤️'
]

@app.route('/')
def index():
    origenes = sorted(rutas['Origen'].dropna().unique())
    destinos = sorted(rutas['Destino'].dropna().unique())
    transportes = sorted(rutas['Transporte'].dropna().unique())
    frase = random.choice(frases)
    return render_template('index.html', origenes=origenes, destinos=destinos, transportes=transportes, frase=frase)

@app.route('/buscar', methods=['POST'])
def buscar():
    origen = request.form['origen']
    destino = request.form['destino']
    filtro = request.form.getlist('transporte')
    resultados = rutas[(rutas['Origen'] == origen) & (rutas['Destino'] == destino)]
    if filtro:
        resultados = resultados[resultados['Transporte'].isin(filtro)]
    resultados = resultados.sort_values(by='Llegada')
    frase = random.choice(frases)
    return render_template('resultados.html', resultados=resultados, frase=frase)

if __name__ == '__main__':
    app.run(debug=True)
