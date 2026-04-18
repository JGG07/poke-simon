import json
import os
import re
import tempfile
import time
import unicodedata
import wave
from array import array
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.sparse import spmatrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.desktop.common_runtime import (
    clear_display_esp32 as _clear_display_esp32,
    debug_serial_message as _debug_serial_message,
    load_whisper_model as _load_whisper_model,
    open_serial_connection as _open_serial_connection,
    read_serial_bytes as _read_serial_bytes,
    read_serial_line as _read_serial_line,
    read_serial_line_non_empty as _read_serial_line_non_empty,
    send_command_esp32 as _send_command_esp32,
    show_message_esp32 as _show_message_esp32,
    show_pokemon_esp32 as _show_pokemon_esp32,
    transcribe_wav_with_whisper as _transcribe_wav_with_whisper,
    unlock_display_esp32 as _unlock_display_esp32,
    wait_serial_response as _wait_serial_response,
)

try:
    import serial
except ImportError:
    serial = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POKEDEX_FILE = PROJECT_ROOT / "data" / "pokedex.json"
LEARNED_SAMPLES_FILE = PROJECT_ROOT / "data" / "aprendizaje.json"

SERIAL_PORT = "COM4"
SERIAL_BAUDRATE = 921600
SERIAL_TIMEOUT = 1
SERIAL_ACK_TIMEOUT = 2.0
SERIAL_AUDIO_RESPONSE_TIMEOUT = 20.0
SERIAL_AUDIO_CHUNK_DELAY = 0.003
SERIAL_READY_DELAY_SECONDS = 0.9
DEBUG_SERIAL = False

AUDIO_SAMPLE_RATE = 16000
AUDIO_CHUNK_SIZE = 256

VOICE_MODEL_SIZE = "base"
VOICE_DEVICE = "cpu"
VOICE_COMPUTE_TYPE = "int8"
VOICE_LANGUAGE = "es"
QUESTION_TIMEOUT_MS = 15000
VOICE_MAX_ATTEMPTS = 2
STREAM_CHUNK_TIMEOUT_SECONDS = 2.5
STREAM_SPEECH_THRESHOLD = 180
STREAM_MIN_SPEECH_MS = 300
STREAM_INITIAL_SILENCE_MS = 250
STREAM_END_SILENCE_MS = 700
STREAM_END_SILENCE_FAST_MS = 450
STREAM_FAST_CUTOFF_AFTER_SPEECH_MS = 900
STREAM_PREROLL_CHUNKS = 12
STREAM_MIN_FALLBACK_AUDIO_MS = 1200

NAME_MAX_NGRAM_TOKENS = 4
NAME_MIN_SCORE = 0.50
NAME_MIN_MARGIN = 0.08
SELF_LEARNING_MIN_SCORE = 0.72
SELF_LEARNING_MIN_MARGIN = 0.12
MAX_SAMPLES_PER_POKEMON = 24

TTS_RATE = 170
WELCOME_MESSAGE = (
    "Hola. Bienvenido a la Pokedex. "
    "Que quieres saber?"
)
EXIT_COMMANDS = ("salir", "salida", "regresar", "volver", "menu", "menú")

TIPOS_ES = {
    "Normal": "Normal",
    "Fire": "Fuego",
    "Water": "Agua",
    "Electric": "Electrico",
    "Grass": "Planta",
    "Ice": "Hielo",
    "Fighting": "Lucha",
    "Poison": "Veneno",
    "Ground": "Tierra",
    "Flying": "Volador",
    "Psychic": "Psiquico",
    "Bug": "Bicho",
    "Rock": "Roca",
    "Ghost": "Fantasma",
    "Dragon": "Dragon",
    "Dark": "Siniestro",
    "Steel": "Acero",
    "Fairy": "Hada",
}

UNIDADES_NUMERO_ES = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
}

ESPECIALES_NUMERO_ES = {
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
}

DECENAS_NUMERO_ES = {
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
}

CENTENAS_NUMERO_ES = {
    "cien": 100,
    "ciento": 100,
}


@dataclass
class NamePrediction:
    label: str | None
    fragment: str
    score: float
    margin: float


@dataclass
class PokemonNameModel:
    vectorizer: TfidfVectorizer
    matrix: spmatrix
    sample_texts: list[str]
    sample_labels: list[str]


def imprimir_debug_serial(mensaje: str) -> None:
    _debug_serial_message(DEBUG_SERIAL, mensaje)


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.strip().lower())
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    texto = texto.replace("'", "")
    texto = re.sub(r"[^a-z0-9\s()]", " ", texto)
    return " ".join(texto.split())


def traducir_lista(lista: list[str]) -> list[str]:
    return [TIPOS_ES.get(str(valor), str(valor)) for valor in lista]


def obtener_lista_str(valor) -> list[str]:
    if isinstance(valor, list):
        return [str(elemento) for elemento in valor]
    return []


def cargar_pokedex(ruta: Path) -> list[dict]:
    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"No se encontro el archivo '{ruta.name}' en {ruta.parent}."
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"El archivo '{ruta.name}' no contiene un JSON valido."
        ) from exc

    pokemon = datos.get("pokemon")
    if not isinstance(pokemon, list) or not pokemon:
        raise ValueError("El JSON no contiene una lista valida en la clave 'pokemon'.")

    return pokemon


def cargar_muestras_aprendidas(ruta: Path) -> list[dict[str, str]]:
    if not ruta.exists():
        guardar_muestras_aprendidas(ruta, [])
        return []

    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, json.JSONDecodeError):
        guardar_muestras_aprendidas(ruta, [])
        return []

    if not isinstance(datos, list):
        return []

    muestras = []
    for item in datos:
        if not isinstance(item, dict):
            continue
        texto = item.get("text")
        etiqueta = item.get("label")
        if not isinstance(texto, str) or not isinstance(etiqueta, str):
            continue

        texto = normalizar_texto(texto)
        etiqueta = normalizar_texto(etiqueta)
        if texto and etiqueta:
            muestras.append({"text": texto, "label": etiqueta})

    return muestras


def guardar_muestras_aprendidas(ruta: Path, muestras: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta_temporal = ruta.with_suffix(f"{ruta.suffix}.tmp")
    with ruta_temporal.open("w", encoding="utf-8") as archivo:
        json.dump(muestras, archivo, ensure_ascii=False, indent=2)
        archivo.flush()
        os.fsync(archivo.fileno())
    ruta_temporal.replace(ruta)


def contar_muestras_por_label(muestras: list[dict[str, str]]) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for muestra in muestras:
        label = muestra["label"]
        conteo[label] = conteo.get(label, 0) + 1
    return conteo


def generar_variantes_foneticas(texto: str) -> list[str]:
    texto_normalizado = normalizar_texto(texto)
    if not texto_normalizado:
        return []

    variantes = [texto_normalizado]
    tokens = texto_normalizado.split()

    def agregar(variante: str) -> None:
        variante_normalizada = normalizar_texto(variante)
        if variante_normalizada and variante_normalizada not in variantes:
            variantes.append(variante_normalizada)

    agregar(texto_normalizado.replace("ew", "iu"))
    agregar(texto_normalizado.replace("w", "u"))
    agregar(texto_normalizado.replace("oo", "u"))

    if len(tokens) == 1 and len(texto_normalizado) <= 4 and texto_normalizado.endswith("l"):
        agregar(texto_normalizado[:-1] + "u")

    return variantes


def generar_aliases_nombre(nombre: str) -> list[str]:
    nombre_normalizado = normalizar_texto(nombre)
    if not nombre_normalizado:
        return []

    aliases = generar_variantes_foneticas(nombre_normalizado)

    if nombre_normalizado.startswith("mr "):
        aliases.append(nombre_normalizado[3:].strip())

    return list(dict.fromkeys(alias for alias in aliases if alias))


def construir_indice_pokemon(lista_pokemon: list[dict]) -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for pokemon in lista_pokemon:
        nombre = pokemon.get("name")
        if isinstance(nombre, str) and nombre.strip():
            indice[normalizar_texto(nombre)] = pokemon

    if not indice:
        raise ValueError("No se encontraron Pokemon validos en la pokedex.")

    return indice


def construir_indice_numero(lista_pokemon: list[dict]) -> dict[str, dict]:
    indice: dict[str, dict] = {}
    for pokemon in lista_pokemon:
        numero = pokemon.get("num")
        if isinstance(numero, str) and numero.strip():
            indice[numero.strip()] = pokemon
            indice[numero.strip().lstrip("0") or "0"] = pokemon

    return indice


def construir_modelo_nombres(
    lista_pokemon: list[dict],
    muestras_aprendidas: list[dict[str, str]],
) -> PokemonNameModel:
    sample_texts: list[str] = []
    sample_labels: list[str] = []
    labels_validos: set[str] = set()

    for pokemon in lista_pokemon:
        nombre = pokemon.get("name")
        if not isinstance(nombre, str) or not nombre.strip():
            continue

        nombre_normalizado = normalizar_texto(nombre)
        labels_validos.add(nombre_normalizado)
        for alias in generar_aliases_nombre(nombre_normalizado):
            sample_texts.append(alias)
            sample_labels.append(nombre_normalizado)

    for muestra in muestras_aprendidas:
        if muestra["label"] not in labels_validos:
            continue
        for variante in generar_variantes_foneticas(muestra["text"]):
            sample_texts.append(variante)
            sample_labels.append(muestra["label"])

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))
    matrix = vectorizer.fit_transform(sample_texts)
    return PokemonNameModel(
        vectorizer=vectorizer,
        matrix=matrix,
        sample_texts=sample_texts,
        sample_labels=sample_labels,
    )


def construir_fragmentos_candidatos(texto: str) -> list[str]:
    texto_normalizado = normalizar_texto(texto)
    tokens = [token for token in texto_normalizado.split() if token]
    candidatos: list[str] = []

    if texto_normalizado:
        candidatos.extend(generar_variantes_foneticas(texto_normalizado))

    for inicio in range(len(tokens)):
        for longitud in range(1, NAME_MAX_NGRAM_TOKENS + 1):
            fin = inicio + longitud
            if fin > len(tokens):
                continue
            fragmento = " ".join(tokens[inicio:fin])
            candidatos.extend(generar_variantes_foneticas(fragmento))

    return list(dict.fromkeys(candidatos))


def predecir_nombre_pokemon(texto: str, modelo: PokemonNameModel) -> NamePrediction:
    candidatos = construir_fragmentos_candidatos(texto)
    if not candidatos:
        return NamePrediction(label=None, fragment="", score=0.0, margin=0.0)

    mejor = NamePrediction(label=None, fragment="", score=0.0, margin=0.0)

    for fragmento in candidatos:
        vector = modelo.vectorizer.transform([fragmento])
        similitudes = cosine_similarity(vector, modelo.matrix)[0]
        puntajes_por_label: dict[str, float] = {}

        for indice, similitud in enumerate(similitudes):
            label = modelo.sample_labels[indice]
            mejor_label = puntajes_por_label.get(label, 0.0)
            if float(similitud) > mejor_label:
                puntajes_por_label[label] = float(similitud)

        if not puntajes_por_label:
            continue

        ranking = sorted(
            puntajes_por_label.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        label, score = ranking[0]
        segundo = ranking[1][1] if len(ranking) > 1 else 0.0
        margin = score - segundo

        if score > mejor.score or (score == mejor.score and margin > mejor.margin):
            mejor = NamePrediction(label=label, fragment=fragmento, score=score, margin=margin)

    return mejor


def aprender_desde_prediccion(
    prediccion: NamePrediction,
    muestras_aprendidas: list[dict[str, str]],
) -> bool:
    label = prediccion.label
    if label is None:
        return False

    # Si la prediccion fue lo bastante confiable para responder al usuario,
    # tambien la consideramos valida para aprendizaje incremental.
    if prediccion.score < NAME_MIN_SCORE or prediccion.margin < NAME_MIN_MARGIN:
        return False

    if prediccion.fragment == label:
        return False

    for muestra in muestras_aprendidas:
        if muestra["text"] == prediccion.fragment and muestra["label"] == label:
            return False

    conteo = contar_muestras_por_label(muestras_aprendidas)
    if conteo.get(label, 0) >= MAX_SAMPLES_PER_POKEMON:
        return False

    muestras_aprendidas.append({"text": prediccion.fragment, "label": label})
    return True


def detectar_intencion(pregunta: str) -> str | None:
    pregunta_normalizada = normalizar_texto(pregunta)

    if any(frase in pregunta_normalizada for frase in ("debilidad", "debilidades", "contra que es debil")):
        return "weaknesses"

    if any(frase in pregunta_normalizada for frase in ("tipo", "tipos")):
        return "type"

    if any(frase in pregunta_normalizada for frase in ("peso", "pesa", "cuanto pesa")):
        return "weight"

    if any(frase in pregunta_normalizada for frase in ("altura", "mide", "cuanto mide")):
        return "height"

    if any(frase in pregunta_normalizada for frase in ("evolucion", "evoluciona", "siguiente evolucion")):
        return "next_evolution"

    if any(frase in pregunta_normalizada for frase in ("evolucion anterior", "pre evolucion", "evolucion previa")):
        return "prev_evolution"

    if any(frase in pregunta_normalizada for frase in ("numero", "num", "pokedex")):
        return "num"

    if any(
        frase in pregunta_normalizada
        for frase in (
            "quien es",
            "quien es ese pokemon",
            "hablame de",
            "habla de",
            "dime de",
            "que sabes de",
            "como es",
        )
    ):
        return "summary"

    return None


def es_comando_salida(texto: str) -> bool:
    texto_normalizado = normalizar_texto(texto)
    if not texto_normalizado:
        return False

    tokens = texto_normalizado.split()
    return any(comando in tokens or comando in texto_normalizado for comando in EXIT_COMMANDS)


def extraer_nombres_evolucion(valor) -> list[str]:
    if not isinstance(valor, list):
        return []

    nombres = []
    for evolucion in valor:
        if isinstance(evolucion, dict) and evolucion.get("name"):
            nombres.append(str(evolucion["name"]))
    return nombres


def convertir_tokens_a_numero(tokens: list[str]) -> int | None:
    if not tokens:
        return None

    total = 0
    actual = 0
    usados = False

    for token in tokens:
        if token == "y":
            continue
        if token in CENTENAS_NUMERO_ES:
            actual += CENTENAS_NUMERO_ES[token]
            usados = True
            continue
        if token in DECENAS_NUMERO_ES:
            actual += DECENAS_NUMERO_ES[token]
            usados = True
            continue
        if token in ESPECIALES_NUMERO_ES:
            actual += ESPECIALES_NUMERO_ES[token]
            usados = True
            continue
        if token in UNIDADES_NUMERO_ES:
            actual += UNIDADES_NUMERO_ES[token]
            usados = True
            continue
        return None

    total += actual
    if not usados or total < 0 or total > 999:
        return None
    return total


def extraer_numero_pokedex(pregunta: str) -> str | None:
    pregunta_normalizada = normalizar_texto(pregunta)
    coincidencia = re.search(r"\b0*(\d{1,3})\b", pregunta_normalizada)
    if coincidencia is None:
        tokens = pregunta_normalizada.split()
        inicio = 0

        for indice, token in enumerate(tokens):
            if token in ("numero", "num"):
                inicio = indice + 1
                break

        candidatos = tokens[inicio:] if inicio < len(tokens) else tokens
        numero_palabras = convertir_tokens_a_numero(candidatos)
        if numero_palabras is None:
            return None
        return str(numero_palabras)

    return coincidencia.group(1)


def es_consulta_por_numero(pregunta: str, intencion: str | None) -> bool:
    if intencion == "num":
        return True

    pregunta_normalizada = normalizar_texto(pregunta)
    if extraer_numero_pokedex(pregunta_normalizada) is None:
        return False

    return any(palabra in pregunta_normalizada for palabra in ("pokemon", "pokemones"))


def responder_pregunta(
    pregunta: str,
    indice: dict[str, dict],
    indice_numero: dict[str, dict],
    modelo_nombres: PokemonNameModel,
) -> tuple[str, NamePrediction]:
    intencion = detectar_intencion(pregunta)
    if es_consulta_por_numero(pregunta, intencion):
        numero_pedido = extraer_numero_pokedex(pregunta)
        if numero_pedido is not None:
            pokemon_por_numero = indice_numero.get(numero_pedido)
            if pokemon_por_numero is not None:
                nombre = str(pokemon_por_numero.get("name", "desconocido"))
                numero_real = str(pokemon_por_numero.get("num", numero_pedido))
                prediccion_numero = NamePrediction(
                    label=normalizar_texto(nombre),
                    fragment=numero_pedido,
                    score=1.0,
                    margin=1.0,
                )
                return f"El Pokemon numero {numero_real} es {nombre}.", prediccion_numero
            return (
                f"No encontre un Pokemon con el numero {numero_pedido} en la pokedex.",
                NamePrediction(label=None, fragment=numero_pedido, score=0.0, margin=0.0),
            )

    prediccion = predecir_nombre_pokemon(pregunta, modelo_nombres)
    if prediccion.label is None:
        return "No pude identificar el nombre del Pokemon en tu pregunta.", prediccion

    if prediccion.score < NAME_MIN_SCORE or prediccion.margin < NAME_MIN_MARGIN:
        return "No pude identificar con suficiente confianza el Pokemon de tu pregunta.", prediccion

    pokemon = indice.get(prediccion.label)
    if pokemon is None:
        return "No encontre ese Pokemon dentro de la pokedex.", prediccion

    nombre = str(pokemon.get("name", "desconocido"))
    tipos = traducir_lista(obtener_lista_str(pokemon.get("type", [])))
    debilidades = traducir_lista(obtener_lista_str(pokemon.get("weaknesses", [])))
    altura = str(pokemon.get("height", "desconocida"))
    peso = str(pokemon.get("weight", "desconocido"))
    numero = str(pokemon.get("num", "desconocido"))

    if not intencion:
        return f"Encontre a {nombre}. Es tipo {', '.join(tipos)}, mide {altura} y pesa {peso}.", prediccion

    if intencion == "summary":
        return f"{nombre} es un Pokemon de tipo {', '.join(tipos)}, mide {altura} y pesa {peso}.", prediccion

    if intencion == "type":
        return f"{nombre} es de tipo {', '.join(tipos)}.", prediccion

    if intencion == "weaknesses":
        if debilidades:
            return f"Las debilidades de {nombre} son {', '.join(debilidades)}.", prediccion
        return f"No encontre debilidades registradas para {nombre}.", prediccion

    if intencion == "weight":
        return f"{nombre} pesa {peso}.", prediccion

    if intencion == "height":
        return f"{nombre} mide {altura}.", prediccion

    if intencion == "num":
        return f"El numero de {nombre} en la pokedex es {numero}.", prediccion

    if intencion == "next_evolution":
        evoluciones = extraer_nombres_evolucion(pokemon.get("next_evolution"))
        if evoluciones:
            return f"La siguiente evolucion de {nombre} es {', '.join(evoluciones)}.", prediccion
        return f"{nombre} no tiene siguiente evolucion.", prediccion

    if intencion == "prev_evolution":
        evoluciones = extraer_nombres_evolucion(pokemon.get("prev_evolution"))
        if evoluciones:
            return f"La evolucion anterior de {nombre} es {', '.join(evoluciones)}.", prediccion
        return f"{nombre} no tiene una evolucion anterior.", prediccion

    return "No pude responder esa pregunta.", prediccion


def abrir_esp32():
    return _open_serial_connection(
        serial,
        SERIAL_PORT,
        SERIAL_BAUDRATE,
        SERIAL_TIMEOUT,
        unavailable_message="Aviso: pyserial no esta disponible. No se podra usar la ESP32.",
        connected_message="ESP32 conectada en {port} a {baudrate} baudios.",
        open_error_message="No se pudo abrir el puerto serial del ESP32: {error}",
    )


def enviar_comando_esp32(ser, comando: str) -> bool:
    return _send_command_esp32(ser, comando, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL)


def mostrar_mensaje_esp32(ser, linea1: str, linea2: str = "") -> bool:
    return _show_message_esp32(ser, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL, linea1, linea2)


def mostrar_pokemon_en_esp32(ser, numero_pokemon: str | None) -> bool:
    return _show_pokemon_esp32(ser, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL, numero_pokemon)


def leer_linea_serial(ser, timeout: float) -> str:
    return _read_serial_line(ser, timeout)


def leer_linea_serial_no_vacia(ser, timeout: float) -> str:
    return _read_serial_line_non_empty(ser, timeout)


def leer_bytes_serial(ser, total_bytes: int, timeout: float) -> bytes:
    return _read_serial_bytes(ser, total_bytes, AUDIO_CHUNK_SIZE, timeout)


def esperar_respuesta_esp32(ser, esperadas: set[str], timeout: float) -> str:
    return _wait_serial_response(ser, esperadas, timeout, DEBUG_SERIAL)


def guardar_pcm_como_wav(path: Path, pcm: bytes, sample_rate: int = AUDIO_SAMPLE_RATE) -> Path:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)
    return path


def grabar_microfono_esp32(ser, duracion_ms: int = QUESTION_TIMEOUT_MS) -> bytes:
    if ser is None or duracion_ms <= 0:
        return b""

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(f"!REC {duracion_ms}\n".encode("utf-8"))
        ser.flush()

        cabecera = ""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            linea = leer_linea_serial(ser, timeout=max(0.1, deadline - time.time()))
            if not linea:
                continue
            if linea.startswith("!AUDIO "):
                cabecera = linea
                break
            imprimir_debug_serial(f"[ESP32] Ignorando antes de audio: {linea}")

        if not cabecera:
            return b""

        try:
            total_bytes = int(cabecera.split()[1])
        except (IndexError, ValueError):
            return b""

        pcm = leer_bytes_serial(ser, total_bytes, timeout=max(5.0, duracion_ms / 1000 + 5.0))
        if len(pcm) != total_bytes:
            return b""

        fin = leer_linea_serial_no_vacia(ser, timeout=5.0)
        if fin != "!DONE":
            return b""

        return pcm
    except Exception as error:
        print(f"Error recibiendo audio del microfono desde la ESP32: {error}")
        return b""


def nivel_audio_pcm(pcm: bytes) -> float:
    if not pcm:
        return 0.0

    muestras = array("h")
    muestras.frombytes(pcm)
    if not muestras:
        return 0.0

    return sum(abs(muestra) for muestra in muestras) / len(muestras)


def esperar_evento_stream_esp32(ser, esperadas: set[str], timeout: float) -> str:
    deadline = time.time() + timeout

    while time.time() < deadline:
        linea = leer_linea_serial(ser, timeout=max(0.1, deadline - time.time()))
        if not linea:
            continue

        if linea.startswith("!PCM "):
            try:
                total_bytes = int(linea.split()[1])
            except (IndexError, ValueError):
                continue
            leer_bytes_serial(ser, total_bytes, timeout=STREAM_CHUNK_TIMEOUT_SECONDS)
            continue

        imprimir_debug_serial(f"[ESP32] {linea}")
        if linea in esperadas:
            return linea

    return ""


def iniciar_stream_microfono_esp32(ser) -> bool:
    if ser is None:
        return False

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(b"!STREAMON\n")
        ser.flush()
        return esperar_evento_stream_esp32(ser, {"!STREAMING", "!ERROR"}, timeout=3.0) == "!STREAMING"
    except Exception as error:
        print(f"Error iniciando stream del microfono: {error}")
        return False


def detener_stream_microfono_esp32(ser) -> bool:
    if ser is None:
        return False

    try:
        ser.write(b"!STREAMOFF\n")
        ser.flush()
        return esperar_evento_stream_esp32(ser, {"!STOPPED", "!ERROR"}, timeout=3.0) == "!STOPPED"
    except Exception as error:
        print(f"Error deteniendo stream del microfono: {error}")
        return False


def leer_chunk_stream_microfono_esp32(ser, timeout: float = STREAM_CHUNK_TIMEOUT_SECONDS) -> bytes | None:
    if ser is None:
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        linea = leer_linea_serial(ser, timeout=max(0.1, deadline - time.time()))
        if not linea:
            continue

        if linea.startswith("!PCM "):
            try:
                total_bytes = int(linea.split()[1])
            except (IndexError, ValueError):
                continue

            if total_bytes <= 0:
                continue

            chunk = leer_bytes_serial(ser, total_bytes, timeout=timeout)
            if len(chunk) == total_bytes:
                return chunk
            return None

        if linea in {"!STREAMING", "!STOPPED"}:
            continue

        imprimir_debug_serial(f"[ESP32] {linea}")

    return None


def capturar_fragmento_streaming_esp32(ser, duracion_ms: int) -> bytes:
    if ser is None or duracion_ms <= 0:
        return b""

    if not iniciar_stream_microfono_esp32(ser):
        print("Aviso: no se pudo iniciar el stream del microfono en la ESP32.")
        return b""

    preroll: deque[bytes] = deque(maxlen=STREAM_PREROLL_CHUNKS)
    pcm = bytearray()
    audio_total_ms = 0.0
    speech_started = False
    escucha_armada = False
    initial_silence_ms = 0.0
    speech_ms = 0.0
    silence_ms = 0.0
    started_at = time.time()

    try:
        while (time.time() - started_at) * 1000 < duracion_ms:
            chunk = leer_chunk_stream_microfono_esp32(ser)
            if not chunk:
                break

            chunk_ms = (len(chunk) / 2 / AUDIO_SAMPLE_RATE) * 1000.0
            audio_total_ms += chunk_ms
            nivel = nivel_audio_pcm(chunk)

            if not speech_started:
                if not escucha_armada:
                    if nivel < STREAM_SPEECH_THRESHOLD:
                        initial_silence_ms += chunk_ms
                        if initial_silence_ms >= STREAM_INITIAL_SILENCE_MS:
                            escucha_armada = True
                    else:
                        initial_silence_ms = 0.0
                    continue

                preroll.append(chunk)
                if nivel >= STREAM_SPEECH_THRESHOLD:
                    speech_started = True
                    for previo in preroll:
                        pcm.extend(previo)
                    preroll.clear()
                    speech_ms += chunk_ms
                continue

            pcm.extend(chunk)
            if nivel >= STREAM_SPEECH_THRESHOLD:
                speech_ms += chunk_ms
                silence_ms = 0.0
            else:
                silence_ms += chunk_ms
                silencio_objetivo = STREAM_END_SILENCE_MS
                if speech_ms >= STREAM_FAST_CUTOFF_AFTER_SPEECH_MS:
                    silencio_objetivo = STREAM_END_SILENCE_FAST_MS
                if speech_ms >= STREAM_MIN_SPEECH_MS and silence_ms >= silencio_objetivo:
                    break
    finally:
        detener_stream_microfono_esp32(ser)

    if speech_ms < STREAM_MIN_SPEECH_MS:
        audio_respaldo = b"".join(preroll) + bytes(pcm)
        if audio_total_ms >= STREAM_MIN_FALLBACK_AUDIO_MS and len(audio_respaldo) >= AUDIO_SAMPLE_RATE:
            return audio_respaldo
        return b""

    return bytes(pcm)


def cargar_transcriptor_voz():
    return _load_whisper_model(
        WhisperModel,
        VOICE_MODEL_SIZE,
        device=VOICE_DEVICE,
        compute_type=VOICE_COMPUTE_TYPE,
    )


def transcribir_wav_con_whisper(transcriptor, audio_path: Path) -> str:
    return _transcribe_wav_with_whisper(
        transcriptor,
        audio_path,
        language=VOICE_LANGUAGE,
        vad_filter=True,
        beam_size=5,
        best_of=5,
        temperature=0.0,
        condition_on_previous_text=False,
        without_timestamps=True,
    )


def tts_a_wav(texto: str) -> str:
    import pyttsx3

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp.close()

    engine = pyttsx3.init()
    engine.setProperty("rate", TTS_RATE)
    engine.save_to_file(texto, temp.name)
    engine.runAndWait()
    engine.stop()

    limite = time.time() + 6
    while time.time() < limite:
        if os.path.exists(temp.name) and os.path.getsize(temp.name) > 44:
            return temp.name
        time.sleep(0.05)

    raise RuntimeError("No se pudo generar el WAV del TTS.")


def wav_a_pcm16_mono_16k(path: Path | str) -> bytes:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width == 1:
        audio = np.frombuffer(frames, dtype=np.uint8).astype(np.int16)
        audio = (audio - 128) << 8
    elif sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16)
    elif sample_width == 4:
        audio32 = np.frombuffer(frames, dtype=np.int32)
        audio = (audio32 >> 16).astype(np.int16)
    else:
        raise ValueError(f"Formato WAV no soportado: {sample_width * 8} bits.")

    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)

    if sample_rate != AUDIO_SAMPLE_RATE and len(audio) > 1:
        old_idx = np.arange(len(audio), dtype=np.float32)
        new_len = max(1, int(len(audio) * AUDIO_SAMPLE_RATE / sample_rate))
        new_idx = np.linspace(0, len(audio) - 1, new_len, dtype=np.float32)
        audio = np.interp(new_idx, old_idx, audio.astype(np.float32)).astype(np.int16)

    return audio.tobytes()


def enviar_pcm_a_esp32(ser, pcm: bytes, descripcion: str = "audio PCM") -> bool:
    if ser is None:
        return False

    if not pcm:
        print("Aviso: no hay datos PCM para enviar.")
        return False

    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        imprimir_debug_serial(f"[ESP32] Cargando {descripcion} ({len(pcm)} bytes PCM)")

        ser.write(f"!LOAD {len(pcm)}\n".encode("utf-8"))
        ser.flush()

        respuesta = esperar_respuesta_esp32(ser, {"!READY", "!ERROR"}, timeout=5.0)
        if respuesta != "!READY":
            print("Aviso: la ESP32 no acepto la carga de audio.")
            return False

        for inicio in range(0, len(pcm), AUDIO_CHUNK_SIZE):
            ser.write(pcm[inicio:inicio + AUDIO_CHUNK_SIZE])
            ser.flush()
            time.sleep(SERIAL_AUDIO_CHUNK_DELAY)

        respuesta = esperar_respuesta_esp32(ser, {"!BUFFERED", "!ERROR"}, timeout=10.0)
        if respuesta != "!BUFFERED":
            print("Aviso: la ESP32 no confirmo el buffer de audio.")
            return False

        ser.write(b"!PLAYBUF\n")
        ser.flush()

        respuesta = esperar_respuesta_esp32(
            ser,
            {"!DONE", "!ERROR"},
            timeout=SERIAL_AUDIO_RESPONSE_TIMEOUT,
        )
        if respuesta != "!DONE":
            print("Aviso: la ESP32 no confirmo la reproduccion del audio.")
            return False

        return True
    except Exception as error:
        print(f"Error enviando audio al ESP32: {error}")
        return False


def enviar_tts_a_esp32(ser, texto: str) -> bool:
    try:
        wav_path = tts_a_wav(texto)
    except Exception as error:
        print(f"No se pudo generar la voz: {error}")
        return False

    try:
        pcm = wav_a_pcm16_mono_16k(wav_path)
        return enviar_pcm_a_esp32(ser, pcm, descripcion="respuesta TTS")
    except Exception as error:
        print(f"No se pudo preparar el audio TTS: {error}")
        return False
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


def escuchar_pregunta(ser, transcriptor) -> str:
    if ser is None or transcriptor is None:
        return ""

    mostrar_mensaje_esp32(ser, "Pregunta:", "Habla ahora")
    time.sleep(SERIAL_READY_DELAY_SECONDS)

    pcm = capturar_fragmento_streaming_esp32(ser, duracion_ms=QUESTION_TIMEOUT_MS)
    if not pcm:
        return ""

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        audio_path = Path(temp_file.name)

    try:
        guardar_pcm_como_wav(audio_path, pcm)
        return transcribir_wav_con_whisper(transcriptor, audio_path)
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass


def responder_por_voz(
    ser,
    pregunta: str,
    respuesta: str,
    nombre_pokemon: str | None = None,
    numero_pokemon: str | None = None,
) -> None:
    print(f"Dijiste: {pregunta}")
    print(f"POKEDEX -> {respuesta}")
    if numero_pokemon:
        mostrar_pokemon_en_esp32(ser, numero_pokemon)
    elif nombre_pokemon:
        mostrar_mensaje_esp32(ser, "Pokemon:", nombre_pokemon)
        time.sleep(1.2)
        mostrar_mensaje_esp32(ser, "Respuesta:", respuesta[:16])
    else:
        mostrar_mensaje_esp32(ser, "Respuesta:", respuesta[:16])
    enviar_tts_a_esp32(ser, respuesta)


def reproducir_bienvenida(ser) -> None:
    if ser is None:
        return

    time.sleep(SERIAL_READY_DELAY_SECONDS)
    responder_por_voz(ser, "Inicio", WELCOME_MESSAGE)


def probar_esp32(ser) -> bool:
    if ser is None:
        return False

    print("Probando comunicacion con la ESP32...")
    return enviar_comando_esp32(ser, "TEST")


def main() -> None:
    try:
        pokedex = cargar_pokedex(POKEDEX_FILE)
        indice_nombre = construir_indice_pokemon(pokedex)
        indice_numero = construir_indice_numero(pokedex)
        muestras_aprendidas = cargar_muestras_aprendidas(LEARNED_SAMPLES_FILE)
        modelo_nombres = construir_modelo_nombres(pokedex, muestras_aprendidas)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}")
        return

    ser = abrir_esp32()
    transcriptor = cargar_transcriptor_voz()

    if transcriptor is None:
        print("Aviso: faster-whisper no esta instalado o no se pudo cargar.")
        return

    if ser is None:
        print("Aviso: no hay ESP32 conectada. Este flujo requiere la placa para microfono y audio.")
        return

    try:
        probar_esp32(ser)
        reproducir_bienvenida(ser)
        print("Pokedex por voz lista con scikit-learn.")
        print("Haz una pregunta sobre un Pokemon usando el microfono de la ESP32.\n")

        while True:
            pregunta = ""
            for intento in range(VOICE_MAX_ATTEMPTS):
                pregunta = escuchar_pregunta(ser, transcriptor)
                if pregunta:
                    break

                if intento == 0:
                    print("No entendi la pregunta. Intentare una vez mas.")
                    mostrar_mensaje_esp32(ser, "No entendi", "Intenta otra")

            if not pregunta:
                print("No se obtuvo ninguna pregunta valida.")
                mostrar_mensaje_esp32(ser, "Sin pregunta", "Intenta otra")
                continue

            if es_comando_salida(pregunta):
                print("Regresando al menu principal...")
                mostrar_mensaje_esp32(ser, "Volviendo", "al menu")
                responder_por_voz(ser, pregunta, "Volviendo al menu principal.")
                return

            respuesta, prediccion = responder_pregunta(
                pregunta,
                indice=indice_nombre,
                indice_numero=indice_numero,
                modelo_nombres=modelo_nombres,
            )
            nombre_pokemon_display = None
            numero_pokemon_display = None
            if (
                prediccion.label is not None
                and prediccion.score >= NAME_MIN_SCORE
                and prediccion.margin >= NAME_MIN_MARGIN
            ):
                pokemon_predicho = indice_nombre.get(prediccion.label)
                if pokemon_predicho is not None:
                    nombre_pokemon_display = str(
                        pokemon_predicho.get("name", prediccion.label)
                    )
                    numero_pokemon_display = str(
                        pokemon_predicho.get("num", "")
                    ).strip() or None

            if aprender_desde_prediccion(prediccion, muestras_aprendidas):
                guardar_muestras_aprendidas(LEARNED_SAMPLES_FILE, muestras_aprendidas)
                modelo_nombres = construir_modelo_nombres(pokedex, muestras_aprendidas)
                label_aprendido = prediccion.label
                if label_aprendido is not None:
                    nombre_real = indice_nombre[label_aprendido]["name"]
                else:
                    nombre_real = "desconocido"
                print(
                    f"Scikit-learn aprendio un nuevo ejemplo para {nombre_real}: "
                    f"'{prediccion.fragment}'"
                )

            responder_por_voz(
                ser,
                pregunta,
                respuesta,
                nombre_pokemon_display,
                numero_pokemon_display,
            )
            print(
                f"Prediccion nombre -> label={prediccion.label}, "
                f"fragmento='{prediccion.fragment}', score={prediccion.score:.3f}, "
                f"margin={prediccion.margin:.3f}"
            )
            print("-" * 60)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nCerrando conexion...")
    finally:
        if ser is not None:
            ser.close()


if __name__ == "__main__":
    main()
