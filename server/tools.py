"""Funciones que Billy puede usar (tool calling de DeepSeek) y la hora de CDMX.

Clima: Open-Meteo (https://open-meteo.com), gratis sin clave para uso personal / automatización del hogar,
hasta 10 000 llamadas al día. Datos bajo licencia CC-BY 4.0: "Weather data by Open-Meteo.com".
"""

import datetime
import functools
import json
import os
import urllib.parse
import urllib.request

# La Ciudad de México no tiene horario de verano desde 2022: UTC-6 todo el año
CDMX = datetime.timezone(datetime.timedelta(hours=-6), "CDMX")

DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
DEFAULT_CITY = os.environ.get("WEATHER_CITY", "Ciudad de México")

# Códigos de clima WMO (los que usa Open-Meteo)
WMO = {
    0: "despejado", 1: "casi despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "con niebla", 48: "con niebla y escarcha",
    51: "con llovizna ligera", 53: "con llovizna", 55: "con llovizna fuerte",
    56: "con llovizna helada", 57: "con llovizna helada fuerte",
    61: "con lluvia ligera", 63: "con lluvia", 65: "con lluvia fuerte",
    66: "con lluvia helada", 67: "con lluvia helada fuerte",
    71: "con nevada ligera", 73: "con nevada", 75: "con nevada fuerte", 77: "con granizo fino",
    80: "con chubascos ligeros", 81: "con chubascos", 82: "con chubascos muy fuertes",
    85: "con chubascos de nieve", 86: "con chubascos de nieve fuertes",
    95: "con tormenta eléctrica", 96: "con tormenta y granizo", 99: "con tormenta y granizo fuerte",
}


def now_cdmx():
    return datetime.datetime.now(CDMX)


def now_in_spanish():
    t = now_cdmx()
    return f"{DAYS[t.weekday()]} {t.day} de {MONTHS[t.month - 1]} de {t.year}, {t:%H:%M} (hora de la Ciudad de México)"


def _get_json(url, **params):
    with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(params), timeout=10) as response:
        return json.load(response)


@functools.lru_cache(maxsize=64)
def _geocode(city):
    results = _get_json(GEOCODING_URL, name=city, count=1, language="es").get("results")
    if not results:
        return None
    r = results[0]
    place = ", ".join(x for x in [r["name"], r.get("admin1"), r.get("country")] if x)
    return r["latitude"], r["longitude"], place


@functools.lru_cache(maxsize=64)
def _forecast(lat, lon, ten_minute_slot):
    """ten_minute_slot solo sirve para que el caché dure 10 minutos: el clima no cambia minuto a minuto."""
    return _get_json(FORECAST_URL, latitude=lat, longitude=lon, timezone="America/Mexico_City", forecast_days=3,
                     current="temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,"
                             "relative_humidity_2m",
                     daily="temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code")


def get_weather(ciudad=None, dia="hoy"):
    """Clima actual (si dia es "hoy") y pronóstico del día pedido, en un diccionario corto para el modelo."""
    location = _geocode(ciudad or DEFAULT_CITY)
    if not location:
        return {"error": f"No encontré la ciudad '{ciudad}'."}
    lat, lon, place = location
    offset = {"hoy": 0, "mañana": 1, "pasado mañana": 2}.get(dia, 0)
    data = _forecast(lat, lon, int(now_cdmx().timestamp() // 600))
    daily = data["daily"]
    result = {
        "lugar": place,
        "dia": dia,
        "pronostico": WMO.get(daily["weather_code"][offset], "variable"),
        "maxima_c": round(daily["temperature_2m_max"][offset]),
        "minima_c": round(daily["temperature_2m_min"][offset]),
        "probabilidad_lluvia_pct": daily["precipitation_probability_max"][offset],
    }
    if offset == 0:
        c = data["current"]
        result["ahora"] = {
            "temperatura_c": round(c["temperature_2m"]),
            "sensacion_c": round(c["apparent_temperature"]),
            "cielo": WMO.get(c["weather_code"], "variable"),
            "humedad_pct": c["relative_humidity_2m"],
            "viento_kmh": round(c["wind_speed_10m"]),
        }
    return result


# Definición para DeepSeek (formato de funciones de OpenAI)
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Clima actual y pronóstico (hoy, mañana o pasado mañana) de una ciudad. Si no se dice "
                       f"ciudad, es {DEFAULT_CITY}, donde vive Billy.",
        "parameters": {
            "type": "object",
            "properties": {
                "ciudad": {"type": "string", "description": "Ciudad, por ejemplo 'Guadalajara'. Omitir para "
                                                            f"{DEFAULT_CITY}."},
                "dia": {"type": "string", "enum": ["hoy", "mañana", "pasado mañana"]},
            },
        },
    },
}]

FUNCTIONS = {"get_weather": get_weather}


def call(name, arguments_json):
    """Ejecuta una función pedida por el modelo; los errores se le devuelven como texto para que los cuente."""
    try:
        args = json.loads(arguments_json or "{}")
        return json.dumps(FUNCTIONS[name](**args), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"No pude consultar: {e}"}, ensure_ascii=False)
