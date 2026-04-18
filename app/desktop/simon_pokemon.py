import json
import os
import random
import re
import sys
import tempfile
import time
import unicodedata
import wave
from array import array
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

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
SIMON_LEARNED_SAMPLES_FILE = PROJECT_ROOT / "data" / "aprendizaje.json"
GAME_HEROES = (
    {"name": "Azul", "display_id": "1"},
    {"name": "Amarillo", "display_id": "2"},
    {"name": "Rojo", "display_id": "3"},
    {"name": "Verde", "display_id": "4"},
)
SERIAL_PORT = "COM4"
SERIAL_BAUDRATE = 921600
SERIAL_TIMEOUT = 1
SERIAL_ACK_TIMEOUT = 2.0
DISPLAY_SHOW_SECONDS = 1.1
DISPLAY_GAP_SECONDS = 0.18
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHUNK_SIZE = 256
PCM_PLAYBACK_GAIN = 0.10
MIC_TEST_DURATION_MS = 5000
ESP32_MAX_RECORD_MS = 28000
SERIAL_AUDIO_RESPONSE_TIMEOUT = 20.0
SERIAL_AUDIO_CHUNK_DELAY = 0.003
DEBUG_SERIAL = False
VOICE_LANGUAGE = "es"
VOICE_MODEL_SIZE = "base"
VOICE_DEVICE = "cpu"
VOICE_COMPUTE_TYPE = "int8"
VOICE_TIMEOUT_BASE_MS = 2500
VOICE_TIMEOUT_PER_POKEMON_MS = 1600
VOICE_READY_DELAY_SECONDS = 0.9
VOICE_MAX_ATTEMPTS = 2
VOICE_MAX_CAPTURE_RETRIES = 4
VOICE_FUZZY_MIN_SCORE = 0.62
STREAM_CHUNK_TIMEOUT_SECONDS = 2.5
STREAM_SPEECH_THRESHOLD = 180
STREAM_MIN_SPEECH_MS = 300
STREAM_INITIAL_SILENCE_MS = 250
STREAM_END_SILENCE_MS = 700
STREAM_END_SILENCE_FAST_MS = 450
STREAM_FAST_CUTOFF_AFTER_SPEECH_MS = 900
STREAM_PREROLL_CHUNKS = 12
STREAM_MIN_FALLBACK_AUDIO_MS = 1200
VOICE_INITIAL_PROMPT = (
    "Azul, amarillo, rojo, verde. "
    "Los colores posibles son azul, amarillo, rojo y verde."
)
VOICE_HOTWORDS = "Azul, amarillo, rojo, verde"
VOICE_FRAGMENT_SEPARATORS = r"(?:,| y | e | luego | despues | despues de | seguido de | entonces )"
EXIT_COMMANDS = ("salir", "regresar", "volver", "menu", "menú")


def abrir_esp32():
    """Abre la conexion serial con el ESP32 si pyserial esta disponible."""
    return _open_serial_connection(
        serial,
        SERIAL_PORT,
        SERIAL_BAUDRATE,
        SERIAL_TIMEOUT,
        unavailable_message="Aviso: pyserial no esta disponible. Se usaran solo sonidos locales.",
        connected_message="ESP32 conectado en {port} a {baudrate} baudios.",
        open_error_message="No se pudo abrir el puerto serial del ESP32: {error}",
    )


def imprimir_debug_serial(mensaje: str) -> None:
    """Imprime mensajes seriales solo cuando la depuracion esta habilitada."""
    _debug_serial_message(DEBUG_SERIAL, mensaje)


def enviar_comando_esp32(ser, comando: str) -> bool:
    """Envia un comando de una linea al ESP32 y valida el ACK esperado."""
    return _send_command_esp32(ser, comando, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL)


def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparar sin acentos, mayusculas ni espacios extra."""
    texto = unicodedata.normalize("NFD", texto.strip().lower())
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    texto = texto.replace("'", "")
    texto = re.sub(r"[^a-z0-9\s()]", " ", texto)
    return " ".join(texto.split())


def es_comando_salida(texto: str) -> bool:
    texto_normalizado = normalizar_texto(texto)
    if not texto_normalizado:
        return False

    tokens = texto_normalizado.split()
    if any(comando in tokens or comando in texto_normalizado for comando in EXIT_COMMANDS):
        return True

    variantes_salida = ("salida", "salido", "salgo", "terminar", "cerrar")
    return any(variante in tokens or variante in texto_normalizado for variante in variantes_salida)


MAX_LEARNED_VARIANTS_PER_POKEMON = 24


def normalizar_nombre_archivo(nombre: str) -> str:
    """Convierte un nombre de Pokemon a un nombre de archivo consistente."""
    nombre_normalizado = normalizar_texto(nombre)
    nombre_normalizado = nombre_normalizado.replace(" ", "_")
    nombre_normalizado = nombre_normalizado.replace("(", "")
    nombre_normalizado = nombre_normalizado.replace(")", "")
    nombre_normalizado = nombre_normalizado.replace(".", "")
    nombre_normalizado = nombre_normalizado.replace("'", "")
    return nombre_normalizado


def generar_variantes_foneticas(texto: str) -> list[str]:
    texto_normalizado = normalizar_texto(texto)
    if not texto_normalizado:
        return []

    variantes = [texto_normalizado]

    def agregar(variante: str) -> None:
        variante_normalizada = normalizar_texto(variante)
        if variante_normalizada and variante_normalizada not in variantes:
            variantes.append(variante_normalizada)

    agregar(texto_normalizado.replace("w", "u"))
    agregar(texto_normalizado.replace("v", "b"))
    agregar(texto_normalizado.replace("qu", "cu"))
    agregar(texto_normalizado.replace("k", "c"))
    agregar(texto_normalizado.replace("sh", "ch"))
    agregar(texto_normalizado.replace("ch", "sh"))
    agregar(texto_normalizado.replace("ee", "i"))
    agregar(texto_normalizado.replace("oo", "u"))

    if "azu" in texto_normalizado:
        agregar("azul")
        agregar("asul")

    if "ama" in texto_normalizado or "amariy" in texto_normalizado:
        agregar("amarillo")
        agregar("amariyo")
        agregar("amariyo")
        agregar("amario")

    if "roj" in texto_normalizado:
        agregar("rojo")
        agregar("roho")

    if "verd" in texto_normalizado or "berd" in texto_normalizado:
        agregar("verde")
        agregar("berde")

    return variantes


def cargar_nombres_juego() -> list[str]:
    return [hero["name"] for hero in GAME_HEROES]


def cargar_id_por_nombre() -> dict[str, str]:
    return {hero["name"]: hero["display_id"] for hero in GAME_HEROES}


def construir_variantes_basicas(nombre: str) -> list[str]:
    """Genera variantes basicas; los aliases manuales viven en aprendizaje.json."""
    normalizado = normalizar_texto(nombre)
    variantes = [normalizado]

    junto = normalizado.replace(" ", "")
    if junto != normalizado:
        variantes.append(junto)

    enriquecidas: list[str] = []
    for variante in variantes:
        enriquecidas.extend(generar_variantes_foneticas(variante))

    return list(dict.fromkeys(enriquecidas))


def cargar_nombres_pokemon(ruta: Path) -> list[str]:
    """Carga los nombres de Pokemon desde el archivo JSON."""
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
    if not isinstance(pokemon, list):
        raise ValueError("El JSON no contiene una lista valida en la clave 'pokemon'.")

    nombres = []
    for entrada in pokemon:
        if isinstance(entrada, dict) and isinstance(entrada.get("name"), str):
            nombre = entrada["name"].strip()
            if nombre:
                nombres.append(nombre)

    if not nombres:
        raise ValueError("No se encontraron nombres de Pokemon validos en el JSON.")

    return nombres


def cargar_num_por_nombre(ruta: Path) -> dict[str, str]:
    """Carga un mapa nombre -> numero de pokedex."""
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
    if not isinstance(pokemon, list):
        raise ValueError("El JSON no contiene una lista valida en la clave 'pokemon'.")

    mapa = {}
    for entrada in pokemon:
        if not isinstance(entrada, dict):
            continue

        nombre = entrada.get("name")
        numero = entrada.get("num")
        if isinstance(nombre, str) and isinstance(numero, str) and nombre.strip() and numero.strip():
            mapa[nombre.strip()] = numero.strip()

    if not mapa:
        raise ValueError("No se encontraron numeros de Pokemon validos en el JSON.")

    return mapa


def cargar_muestras_aprendidas(ruta: Path) -> list[dict[str, str]]:
    if not ruta.exists():
        return []

    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(datos, list):
        return []

    muestras: list[dict[str, str]] = []
    permitidos = {normalizar_texto(hero["name"]) for hero in GAME_HEROES}
    for item in datos:
        if not isinstance(item, dict):
            continue
        texto = item.get("text")
        etiqueta = item.get("label")
        if not isinstance(texto, str) or not isinstance(etiqueta, str):
            continue

        texto_normalizado = normalizar_texto(texto)
        etiqueta_normalizada = normalizar_texto(etiqueta)
        if texto_normalizado and etiqueta_normalizada in permitidos:
            muestras.append({"text": texto_normalizado, "label": etiqueta_normalizada})

    return muestras


def cargar_muestras_aprendidas_crudas(ruta: Path) -> list[dict[str, str]]:
    if not ruta.exists():
        return []

    try:
        with ruta.open("r", encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(datos, list):
        return []

    muestras: list[dict[str, str]] = []
    for item in datos:
        if not isinstance(item, dict):
            continue
        texto = item.get("text")
        etiqueta = item.get("label")
        if not isinstance(texto, str) or not isinstance(etiqueta, str):
            continue
        texto_normalizado = normalizar_texto(texto)
        etiqueta_normalizada = normalizar_texto(etiqueta)
        if texto_normalizado and etiqueta_normalizada:
            muestras.append({"text": texto_normalizado, "label": etiqueta_normalizada})
    return muestras


def guardar_muestras_aprendidas(ruta: Path, muestras: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    etiquetas_juego = {normalizar_texto(hero["name"]) for hero in GAME_HEROES}
    muestras_existentes = cargar_muestras_aprendidas_crudas(ruta)
    muestras_no_juego = [
        muestra
        for muestra in muestras_existentes
        if muestra["label"] not in etiquetas_juego
    ]
    muestras_finales = muestras_no_juego + muestras

    ruta_temporal = ruta.with_suffix(f"{ruta.suffix}.tmp")
    with ruta_temporal.open("w", encoding="utf-8") as archivo:
        json.dump(muestras_finales, archivo, ensure_ascii=False, indent=2)
        archivo.flush()
        os.fsync(archivo.fileno())
    ruta_temporal.replace(ruta)


def construir_aliases_pokemon(
    nombres: list[str],
    muestras_aprendidas: list[dict[str, str]] | None = None,
) -> dict[tuple[str, ...], str]:
    """Construye aliases normalizados para detectar nombres dentro de una transcripcion."""
    aliases: dict[tuple[str, ...], str] = {}
    max_tokens_por_nombre: dict[str, int] = {}

    for nombre in nombres:
        max_tokens = 1
        for variante in construir_variantes_basicas(nombre):
            tokens = tuple(token for token in re.split(r"[^a-z0-9]+", variante) if token)
            if tokens:
                aliases[tokens] = nombre
                max_tokens = max(max_tokens, len(tokens))
        max_tokens_por_nombre[nombre] = max_tokens

    nombre_por_normalizado = {normalizar_texto(nombre): nombre for nombre in nombres}
    for muestra in muestras_aprendidas or []:
        nombre_real = nombre_por_normalizado.get(muestra["label"])
        if nombre_real is None:
            continue
        for variante in generar_variantes_foneticas(muestra["text"]):
            tokens = tuple(token for token in re.split(r"[^a-z0-9]+", variante) if token)
            if (
                tokens
                and len(tokens) <= max_tokens_por_nombre.get(nombre_real, 1)
                and not (len(tokens) > 1 and len(set(tokens)) == 1)
            ):
                aliases[tokens] = nombre_real

    return aliases


def construir_catalogo_pokemon(
    nombres: list[str],
    muestras_aprendidas: list[dict[str, str]] | None = None,
) -> list[tuple[str, str]]:
    """Crea una lista de nombres normalizados para matching difuso."""
    catalogo = []
    max_tokens_por_nombre: dict[str, int] = {}
    for nombre in nombres:
        max_tokens = 1
        for variante in construir_variantes_basicas(nombre):
            variante_normalizada = normalizar_texto(variante)
            catalogo.append((variante_normalizada, nombre))
            max_tokens = max(max_tokens, len([t for t in re.split(r"[^a-z0-9]+", variante_normalizada) if t]))
        max_tokens_por_nombre[nombre] = max_tokens

    nombre_por_normalizado = {normalizar_texto(nombre): nombre for nombre in nombres}
    for muestra in muestras_aprendidas or []:
        nombre_real = nombre_por_normalizado.get(muestra["label"])
        if nombre_real is not None:
            for variante in generar_variantes_foneticas(muestra["text"]):
                tokens = [t for t in re.split(r"[^a-z0-9]+", variante) if t]
                if (
                    tokens
                    and len(tokens) <= max_tokens_por_nombre.get(nombre_real, 1)
                    and not (len(tokens) > 1 and len(set(tokens)) == 1)
                ):
                    catalogo.append((variante, nombre_real))
    return catalogo


def obtener_siguiente_pokemon(nombres: list[str]) -> str:
    """Elige un Pokemon al azar permitiendo repeticiones como en Simon."""
    return random.choice(nombres)


def probar_esp32(ser) -> bool:
    """Hace una prueba corta de comunicacion con la ESP32."""
    if ser is None:
        return False

    print("Probando comunicacion con la ESP32...")
    return enviar_comando_esp32(ser, "TEST")


def mostrar_personaje_en_esp32(ser, personaje_id: str | None) -> bool:
    """Manda a la ESP32 el identificador del heroe para mostrarlo en el display."""
    if ser is None or not personaje_id:
        return False

    return enviar_comando_esp32(ser, f"HERO {personaje_id}")


def limpiar_display_esp32(ser) -> bool:
    """Limpia temporalmente el display de la ESP32."""
    return _clear_display_esp32(ser, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL)


def liberar_display_esp32(ser) -> bool:
    """Libera el display para que vuelva a su comportamiento normal."""
    return _unlock_display_esp32(ser, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL)


def mostrar_mensaje_esp32(ser, linea1: str, linea2: str = "") -> bool:
    """Muestra un mensaje corto en el display de la ESP32."""
    return _show_message_esp32(ser, SERIAL_ACK_TIMEOUT, DEBUG_SERIAL, linea1, linea2)


def buscar_audio_pokemon(nombre: str, sounds_dir: Path) -> Path | None:
    """Busca el archivo de audio asociado a un Pokemon dentro de pokesounds/."""
    nombre_normalizado = normalizar_nombre_archivo(nombre)

    for patron in ("*.wav", "*.WAV"):
        for candidato in sounds_dir.glob(patron):
            stem_normalizado = normalizar_nombre_archivo(candidato.stem)
            if stem_normalizado == nombre_normalizado:
                return candidato

            if " - " not in candidato.stem:
                continue

            _, nombre_archivo = candidato.stem.split(" - ", 1)
            if normalizar_nombre_archivo(nombre_archivo) == nombre_normalizado:
                return candidato

    return None


def wav_a_pcm16_mono_16k(path: Path) -> bytes:
    """Convierte un WAV a PCM mono 16-bit 16 kHz."""
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if sample_width == 1:
        audio = [((muestra - 128) << 8) for muestra in frames]
    elif sample_width == 2:
        audio = [
            int.from_bytes(frames[i:i + 2], byteorder="little", signed=True)
            for i in range(0, len(frames), 2)
        ]
    elif sample_width == 4:
        audio = [
            int.from_bytes(frames[i + 2:i + 4], byteorder="little", signed=True)
            for i in range(0, len(frames), 4)
        ]
    else:
        raise ValueError(f"Formato WAV no soportado: {sample_width * 8} bits.")

    if channels > 1:
        audio_mono = []
        for i in range(0, len(audio), channels):
            frame = audio[i:i + channels]
            if frame:
                audio_mono.append(int(sum(frame) / len(frame)))
        audio = audio_mono

    if sample_rate != AUDIO_SAMPLE_RATE and len(audio) > 1:
        nueva_longitud = max(1, int(len(audio) * AUDIO_SAMPLE_RATE / sample_rate))
        reescalado = []
        for indice in range(nueva_longitud):
            posicion = indice * (len(audio) - 1) / max(1, nueva_longitud - 1)
            base = int(posicion)
            siguiente = min(base + 1, len(audio) - 1)
            fraccion = posicion - base
            muestra = int(audio[base] * (1.0 - fraccion) + audio[siguiente] * fraccion)
            reescalado.append(muestra)
        audio = reescalado

    pcm = bytearray()
    for muestra in audio:
        muestra = int(muestra * PCM_PLAYBACK_GAIN)
        muestra = max(-32768, min(32767, int(muestra)))
        pcm.extend(muestra.to_bytes(2, byteorder="little", signed=True))
    return bytes(pcm)


def leer_linea_serial(ser, timeout: float) -> str:
    """Lee una linea terminada en salto de linea desde el puerto serial."""
    return _read_serial_line(ser, timeout)


def leer_linea_serial_no_vacia(ser, timeout: float) -> str:
    """Lee la siguiente linea no vacia desde el puerto serial."""
    return _read_serial_line_non_empty(ser, timeout)


def leer_bytes_serial(ser, total_bytes: int, timeout: float) -> bytes:
    """Lee una cantidad exacta de bytes desde el puerto serial."""
    return _read_serial_bytes(ser, total_bytes, AUDIO_CHUNK_SIZE, timeout)


def esperar_respuesta_esp32(ser, esperadas: set[str], timeout: float) -> str:
    """Espera una respuesta de texto de la ESP32 e imprime lineas relevantes."""
    return _wait_serial_response(ser, esperadas, timeout, DEBUG_SERIAL)


def guardar_pcm_como_wav(pcm: bytes, destino: Path, sample_rate: int = AUDIO_SAMPLE_RATE) -> Path:
    """Guarda audio PCM mono 16-bit como archivo WAV."""
    destino.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(destino), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)

    return destino


def grabar_microfono_esp32(ser, duracion_ms: int = MIC_TEST_DURATION_MS) -> bytes:
    """Solicita al ESP32 una captura del microfono I2S y devuelve PCM mono 16-bit."""
    if ser is None:
        return b""

    if duracion_ms <= 0:
        print("Aviso: la duracion de grabacion debe ser mayor que cero.")
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
            print("Aviso: la ESP32 no envio la cabecera de audio del microfono.")
            return b""

        try:
            total_bytes = int(cabecera.split()[1])
        except (IndexError, ValueError):
            print(f"Aviso: cabecera de audio invalida: {cabecera}")
            return b""

        if total_bytes <= 0:
            print("Aviso: la ESP32 reporto un tamano de audio invalido.")
            return b""

        imprimir_debug_serial(
            f"[ESP32] Capturando microfono: {duracion_ms} ms ({total_bytes} bytes PCM)"
        )
        pcm = leer_bytes_serial(ser, total_bytes, timeout=max(5.0, duracion_ms / 1000 + 5.0))
        if len(pcm) != total_bytes:
            print(f"Aviso: se recibieron {len(pcm)} de {total_bytes} bytes esperados.")
            return b""

        fin = leer_linea_serial_no_vacia(ser, timeout=5.0)
        if fin != "!DONE":
            print("Aviso: la ESP32 no confirmo el fin de la captura del microfono.")
            return b""

        return pcm
    except Exception as error:
        print(f"Error recibiendo audio del microfono desde la ESP32: {error}")
        return b""


def nivel_audio_pcm(pcm: bytes) -> float:
    """Calcula un nivel simple promedio de amplitud para deteccion de voz."""
    if not pcm:
        return 0.0

    muestras = array("h")
    muestras.frombytes(pcm)
    if not muestras:
        return 0.0

    return sum(abs(muestra) for muestra in muestras) / len(muestras)


def esperar_evento_stream_esp32(ser, esperadas: set[str], timeout: float) -> str:
    """Espera eventos textuales del stream y descarta chunks intermedios si aparecen."""
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
    """Activa el modo de streaming continuo del microfono en la ESP32."""
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
    """Detiene el modo de streaming continuo del microfono en la ESP32."""
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
    """Lee un chunk PCM del stream continuo del microfono."""
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
    """Captura un fragmento de voz desde el stream continuo usando deteccion simple de silencio."""
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
    """Carga el modelo de Whisper si faster-whisper esta disponible."""
    return _load_whisper_model(
        WhisperModel,
        VOICE_MODEL_SIZE,
        device=VOICE_DEVICE,
        compute_type=VOICE_COMPUTE_TYPE,
    )


def transcribir_wav_con_whisper(transcriptor, audio_path: Path, language: str | None = None) -> str:
    """Transcribe un WAV con faster-whisper y devuelve el texto unido."""
    return _transcribe_wav_with_whisper(
        transcriptor,
        audio_path,
        language=VOICE_LANGUAGE if language is None else language,
        vad_filter=True,
        beam_size=5,
        best_of=5,
        temperature=0.0,
        condition_on_previous_text=False,
        initial_prompt=VOICE_INITIAL_PROMPT,
        hotwords=VOICE_HOTWORDS,
        without_timestamps=True,
    )


def similitud_texto(a: str, b: str) -> float:
    """Calcula una similitud simple entre dos textos normalizados."""
    return SequenceMatcher(None, a, b).ratio()


def dividir_fragmentos_pokemon(texto: str) -> list[str]:
    """Separa una frase hablada natural en posibles fragmentos de nombres."""
    texto_normalizado = normalizar_texto(texto)
    if not texto_normalizado:
        return []

    candidatos = re.split(VOICE_FRAGMENT_SEPARATORS, texto_normalizado)
    fragmentos = []
    palabras_ruido = {"its", "it", "is", "es", "the", "a", "an"}
    for candidato in candidatos:
        tokens = [token for token in candidato.split() if token and token not in palabras_ruido]
        if not tokens:
            continue

        limpio = " ".join(tokens)
        fragmentos.append(limpio)

        for inicio in range(len(tokens)):
            for longitud in range(1, min(3, len(tokens) - inicio) + 1):
                fragmento = " ".join(tokens[inicio:inicio + longitud])
                if fragmento not in fragmentos:
                    fragmentos.append(fragmento)
    return fragmentos


def buscar_mejor_pokemon(fragmento: str, catalogo_pokemon: list[tuple[str, str]]) -> tuple[str | None, float]:
    """Busca el nombre de Pokemon mas cercano para un fragmento libre."""
    mejor_nombre = None
    mejor_puntaje = 0.0
    variantes_fragmento = generar_variantes_foneticas(fragmento)
    if not variantes_fragmento:
        return None, 0.0

    for fragmento_normalizado in variantes_fragmento:
        for nombre_normalizado, nombre_real in catalogo_pokemon:
            puntaje = similitud_texto(fragmento_normalizado, nombre_normalizado)

            if fragmento_normalizado in nombre_normalizado or nombre_normalizado in fragmento_normalizado:
                puntaje += 0.12

            if puntaje > mejor_puntaje:
                mejor_puntaje = puntaje
                mejor_nombre = nombre_real

    return mejor_nombre, min(mejor_puntaje, 1.0)


def extraer_pokemon_por_fragmentos(
    texto: str,
    catalogo_pokemon: list[tuple[str, str]],
    longitud_esperada: int,
) -> list[str]:
    """Intenta resolver una lista hablada usando separadores naturales y fuzzy matching."""
    fragmentos = dividir_fragmentos_pokemon(texto)
    if not fragmentos:
        return []

    encontrados: list[str] = []

    for fragmento in fragmentos:
        nombre, puntaje = buscar_mejor_pokemon(fragmento, catalogo_pokemon)
        if nombre is None or puntaje < VOICE_FUZZY_MIN_SCORE:
            continue
        encontrados.append(nombre)

    if longitud_esperada > 0 and len(encontrados) > longitud_esperada:
        return encontrados[:longitud_esperada]

    return encontrados


def extraer_pokemon_desde_texto(
    texto: str,
    aliases_pokemon: dict[tuple[str, ...], str],
    catalogo_pokemon: list[tuple[str, str]],
    longitud_esperada: int,
) -> list[str]:
    """Extrae nombres de Pokemon desde una frase libre, preservando el orden detectado."""
    texto_normalizado = normalizar_texto(texto)
    tokens = [token for token in re.split(r"[^a-z0-9]+", texto_normalizado) if token]
    if not tokens:
        return []

    longitudes = sorted({len(alias) for alias in aliases_pokemon}, reverse=True)
    encontrados: list[str] = []
    i = 0

    while i < len(tokens):
        coincidencia = None

        for longitud in longitudes:
            if i + longitud > len(tokens):
                continue

            candidato = tuple(tokens[i:i + longitud])
            nombre = aliases_pokemon.get(candidato)
            if nombre is not None:
                coincidencia = (nombre, longitud)
                break

        if coincidencia is None:
            i += 1
            continue

        encontrados.append(coincidencia[0])
        i += coincidencia[1]

    if longitud_esperada > 0 and len(encontrados) >= longitud_esperada:
        return encontrados[:longitud_esperada]

    por_fragmentos = extraer_pokemon_por_fragmentos(
        texto,
        catalogo_pokemon=catalogo_pokemon,
        longitud_esperada=longitud_esperada,
    )
    if len(por_fragmentos) > len(encontrados):
        return por_fragmentos

    if encontrados:
        return encontrados

    nombre_unico, puntaje = buscar_mejor_pokemon(texto, catalogo_pokemon)
    if nombre_unico is not None and puntaje >= VOICE_FUZZY_MIN_SCORE:
        return [nombre_unico]

    return encontrados


def escuchar_respuesta_por_voz(
    ser,
    transcriptor,
    aliases_pokemon: dict[tuple[str, ...], str],
    catalogo_pokemon: list[tuple[str, str]],
    longitud_esperada: int,
) -> tuple[list[str], str, bool]:
    """Graba voz desde la ESP32, la transcribe y extrae la secuencia de colores pronunciada."""
    if ser is None or transcriptor is None:
        return [], "", False

    duracion_ms = VOICE_TIMEOUT_BASE_MS + (max(1, longitud_esperada) * VOICE_TIMEOUT_PER_POKEMON_MS)
    duracion_ms = min(duracion_ms, ESP32_MAX_RECORD_MS)
    mostrar_mensaje_esp32(ser, "Tu turno", "Habla ahora")
    print(f"Habla ahora. Tienes aproximadamente {duracion_ms / 1000:.1f} segundos...")
    time.sleep(VOICE_READY_DELAY_SECONDS)

    pcm = grabar_microfono_esp32(ser, duracion_ms=duracion_ms)
    if not pcm:
        return [], "", False

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        audio_path = Path(temp_file.name)

    try:
        guardar_pcm_como_wav(pcm, audio_path)
        texto = transcribir_wav_con_whisper(transcriptor, audio_path, language=VOICE_LANGUAGE)
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass

    if texto:
        mostrar_mensaje_esp32(ser, "Entendi:", texto[:16])
        print(f"Escuche: {texto}")
    else:
        mostrar_mensaje_esp32(ser, "No entendi", "Intenta otra")
        print("Aviso: no se obtuvo texto de la grabacion.")

    return extraer_pokemon_desde_texto(
        texto,
        aliases_pokemon=aliases_pokemon,
        catalogo_pokemon=catalogo_pokemon,
        longitud_esperada=longitud_esperada,
    ), texto, True


def enviar_pcm_a_esp32(ser, pcm: bytes, descripcion: str = "audio PCM") -> bool:
    """Carga un buffer PCM en la ESP32 y ordena reproducirlo."""
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


def enviar_audio_wav_a_esp32(ser, audio_path: Path) -> bool:
    """Convierte un WAV a PCM, lo carga en la ESP32 y luego ordena reproducirlo."""
    if ser is None:
        return False

    try:
        pcm = wav_a_pcm16_mono_16k(audio_path)
    except (wave.Error, ValueError) as error:
        print(f"Aviso: no se pudo convertir {audio_path.name}: {error}")
        return False

    if not pcm:
        print(f"Aviso: el archivo {audio_path.name} no produjo audio PCM.")
        return False

    return enviar_pcm_a_esp32(ser, pcm, descripcion=f"audio {audio_path.name}")


def reproducir_audio_pokemon(nombre: str, sounds_dir: Path, ser=None) -> bool:
    """Reproduce un WAV del Pokemon en ESP32 o, si no hay placa, localmente."""
    audio_path = buscar_audio_pokemon(nombre, sounds_dir)
    if audio_path is None:
        return False

    if ser is not None and enviar_audio_wav_a_esp32(ser, audio_path):
        return True

    try:
        import winsound

        winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
        return True
    except (ImportError, RuntimeError):
        print(f"Aviso: no se pudo reproducir el audio de {nombre}.")
        return False


def mostrar_secuencia_en_display(
    secuencia: list[str],
    id_por_nombre: dict[str, str],
    ser=None,
) -> None:
    """Muestra la secuencia de heroes en el display."""
    for nombre in secuencia:
        mostrar_personaje_en_esp32(ser, id_por_nombre.get(nombre))
        time.sleep(DISPLAY_SHOW_SECONDS)
        limpiar_display_esp32(ser)
        time.sleep(DISPLAY_GAP_SECONDS)


def leer_respuesta_jugador(
    secuencia: list[str],
    ser,
    transcriptor,
    aliases_pokemon: dict[tuple[str, ...], str],
    catalogo_pokemon: list[tuple[str, str]],
    modo_voz: bool,
) -> tuple[list[str], str, bool]:
    """Obtiene la respuesta del jugador, separando fallos de captura de fallos de reconocimiento."""
    if not modo_voz or ser is None or transcriptor is None:
        print("Aviso: no hay reconocimiento por voz disponible.")
        return [], "", False

    ultimo_texto = ""
    intentos_entendimiento = 0
    reintentos_captura = 0

    while intentos_entendimiento < VOICE_MAX_ATTEMPTS and reintentos_captura < VOICE_MAX_CAPTURE_RETRIES:
        if intentos_entendimiento > 0:
            mostrar_mensaje_esp32(ser, "Repitelo", "una vez mas")
            print("No te entendi bien. Intentalo una vez mas.")
        elif reintentos_captura > 0:
            mostrar_mensaje_esp32(ser, "No te oi", "Habla otra vez")
            print("No alcance a captar tu voz. Vamos otra vez.")

        respuesta, texto, captura_valida = escuchar_respuesta_por_voz(
            ser,
            transcriptor=transcriptor,
            aliases_pokemon=aliases_pokemon,
            catalogo_pokemon=catalogo_pokemon,
            longitud_esperada=len(secuencia),
        )
        ultimo_texto = texto
        if es_comando_salida(texto):
            return [], texto, True
        if not captura_valida:
            reintentos_captura += 1
            time.sleep(0.25)
            continue
        if respuesta:
            return respuesta, texto, False
        intentos_entendimiento += 1

    print("No pude entender la secuencia por voz.")
    mostrar_mensaje_esp32(ser, "No entendi", "Fin del juego")
    return [], ultimo_texto, False


def secuencias_iguales(secuencia_correcta: list[str], respuesta_usuario: list[str]) -> bool:
    """Compara dos secuencias de forma tolerante a formato."""
    if len(secuencia_correcta) != len(respuesta_usuario):
        return False

    correcta_normalizada = [normalizar_texto(nombre) for nombre in secuencia_correcta]
    respuesta_normalizada = [normalizar_texto(nombre) for nombre in respuesta_usuario]
    return correcta_normalizada == respuesta_normalizada


def aprender_desde_ronda_correcta(
    texto_detectado: str,
    secuencia_correcta: list[str],
    respuesta_usuario: list[str],
    muestras_aprendidas: list[dict[str, str]],
) -> bool:
    if not texto_detectado or not secuencias_iguales(secuencia_correcta, respuesta_usuario):
        return False

    fragmentos = dividir_fragmentos_pokemon(texto_detectado)
    if len(fragmentos) != len(secuencia_correcta):
        return False

    conteo_por_label: dict[str, int] = {}
    for muestra in muestras_aprendidas:
        conteo_por_label[muestra["label"]] = conteo_por_label.get(muestra["label"], 0) + 1

    agregado = False
    for fragmento, nombre_real in zip(fragmentos, secuencia_correcta):
        texto_normalizado = normalizar_texto(fragmento)
        label = normalizar_texto(nombre_real)
        if not texto_normalizado or texto_normalizado == label:
            continue
        if any(
            muestra["text"] == texto_normalizado and muestra["label"] == label
            for muestra in muestras_aprendidas
        ):
            continue
        if conteo_por_label.get(label, 0) >= MAX_LEARNED_VARIANTS_PER_POKEMON:
            continue

        muestras_aprendidas.append({"text": texto_normalizado, "label": label})
        conteo_por_label[label] = conteo_por_label.get(label, 0) + 1
        agregado = True

    return agregado


def reproducir_sonido_exito() -> None:
    """Reproduce un sonido simple de acierto."""
    try:
        import winsound

        winsound.Beep(880, 180)
        winsound.Beep(1175, 220)
    except (ImportError, RuntimeError):
        print("\a", end="")
        print("Acierto.")


def reproducir_sonido_error() -> None:
    """Reproduce un sonido simple de error."""
    try:
        import winsound

        winsound.Beep(440, 300)
        winsound.Beep(330, 400)
    except (ImportError, RuntimeError):
        print("\a", end="")
        print("Error.")


def notificar_inicio_juego(ser) -> None:
    """Dispara el sonido de inicio de juego."""
    if not enviar_comando_esp32(ser, "START"):
        try:
            import winsound

            winsound.Beep(660, 120)
            winsound.Beep(880, 120)
        except (ImportError, RuntimeError):
            print("\a", end="")


def notificar_inicio_ronda(ser) -> None:
    """Dispara el sonido breve de nueva ronda."""
    if not enviar_comando_esp32(ser, "ROUND"):
        try:
            import winsound

            winsound.Beep(740, 100)
        except (ImportError, RuntimeError):
            print("\a", end="")


def notificar_acierto(ser) -> None:
    """Dispara el sonido de acierto usando ESP32 o fallback local."""
    if ser is not None and enviar_comando_esp32(ser, "OK"):
        return

    reproducir_sonido_exito()


def notificar_error(ser) -> None:
    """Dispara el sonido de error usando ESP32 o fallback local."""
    if ser is not None and enviar_comando_esp32(ser, "ERR"):
        return

    reproducir_sonido_error()


def notificar_fin_juego(ser) -> None:
    """Dispara el sonido de fin de juego en el ESP32."""
    if enviar_comando_esp32(ser, "GAMEOVER"):
        return

    try:
        import winsound

        winsound.Beep(520, 150)
        winsound.Beep(420, 150)
        winsound.Beep(320, 260)
    except (ImportError, RuntimeError):
        print("\a", end="")


def jugar_simon_pokemon(
    nombres: list[str],
    id_por_nombre: dict[str, str],
    aliases_pokemon: dict[tuple[str, ...], str],
    catalogo_pokemon: list[tuple[str, str]],
    muestras_aprendidas: list[dict[str, str]],
    ser=None,
    transcriptor=None,
    modo_voz: bool = False,
) -> None:
    """Ejecuta el ciclo principal del juego."""
    secuencia = []
    puntaje = 0

    print("Bienvenido a Simon de colores.")
    if modo_voz and ser is not None and transcriptor is not None:
        print("Mira la secuencia de colores en el display y luego repitela hablando al microfono.")
        print("El juego escuchara desde el microfono de la ESP32.")
    else:
        print("Aviso: no hay reconocimiento por voz disponible en este momento.")
    print("El juego termina cuando falles.\n")
    notificar_inicio_juego(ser)
    mostrar_mensaje_esp32(ser, "Simon colores", "Preparate")

    while True:
        nuevo_pokemon = obtener_siguiente_pokemon(nombres)
        secuencia.append(nuevo_pokemon)

        print(f"Ronda {len(secuencia)}")
        notificar_inicio_ronda(ser)
        mostrar_mensaje_esp32(ser, f"Ronda {len(secuencia)}", "Memoriza")
        print("Observa la secuencia en el display...")
        mostrar_secuencia_en_display(secuencia, id_por_nombre, ser=ser)

        respuesta, texto_detectado, salir_al_menu = leer_respuesta_jugador(
            secuencia,
            ser=ser,
            transcriptor=transcriptor,
            aliases_pokemon=aliases_pokemon,
            catalogo_pokemon=catalogo_pokemon,
            modo_voz=modo_voz,
        )
        if salir_al_menu:
            mostrar_mensaje_esp32(ser, "Volviendo", "al menu")
            print("\nRegresando al menu principal...")
            liberar_display_esp32(ser)
            return False

        if texto_detectado:
            print(f"Colores detectados: {', '.join(respuesta) if respuesta else '(ninguno)'}")

        if secuencias_iguales(secuencia, respuesta):
            if aprender_desde_ronda_correcta(
                texto_detectado,
                secuencia,
                respuesta,
                muestras_aprendidas,
            ):
                guardar_muestras_aprendidas(SIMON_LEARNED_SAMPLES_FILE, muestras_aprendidas)
                aliases_pokemon = construir_aliases_pokemon(nombres, muestras_aprendidas)
                catalogo_pokemon = construir_catalogo_pokemon(nombres, muestras_aprendidas)
                print("El juego aprendio una nueva variante de voz.")

            puntaje += 1
            notificar_acierto(ser)
            mostrar_mensaje_esp32(ser, "Correcto", f"Puntos {puntaje}")
            print("Correcto. Preparando la siguiente ronda...")
            continue

        notificar_error(ser)
        notificar_fin_juego(ser)
        mostrar_mensaje_esp32(ser, "Perdiste", f"Puntos {puntaje}")
        print("\nFallaste.")
        print(f"Tu respuesta: {', '.join(respuesta) if respuesta else '(vacia)'}")
        print(f"Secuencia correcta: {', '.join(secuencia)}")
        print(f"Puntaje final: {puntaje}")
        liberar_display_esp32(ser)
        return True


def mostrar_menu_principal() -> str:
    """Muestra el menu principal y devuelve la opcion elegida."""
    print("\nMenu Principal")
    print("1. Jugar")
    print("0. Salir")
    return input("Selecciona una opcion: ").strip()


def ejecutar_juego(mostrar_menu: bool = True) -> None:
    """Carga datos y arranca el juego, con o sin menu interno."""
    nombres = cargar_nombres_juego()
    id_por_nombre = cargar_id_por_nombre()
    muestras_aprendidas = cargar_muestras_aprendidas(SIMON_LEARNED_SAMPLES_FILE)
    aliases_pokemon = construir_aliases_pokemon(nombres, muestras_aprendidas)
    catalogo_pokemon = construir_catalogo_pokemon(nombres, muestras_aprendidas)
    ser = abrir_esp32()
    transcriptor = cargar_transcriptor_voz()
    modo_voz = ser is not None and transcriptor is not None

    if transcriptor is None:
        print("Aviso: faster-whisper no esta instalado. El juego no podra usar reconocimiento por voz.")

    try:
        probar_esp32(ser)
        if not mostrar_menu:
            jugar_simon_pokemon(
                nombres,
                id_por_nombre=id_por_nombre,
                aliases_pokemon=aliases_pokemon,
                catalogo_pokemon=catalogo_pokemon,
                muestras_aprendidas=muestras_aprendidas,
                ser=ser,
                transcriptor=transcriptor,
                modo_voz=modo_voz,
            )
            return

        while True:
            opcion = mostrar_menu_principal()
            if opcion == "0":
                return
            if opcion != "1":
                print("Opcion invalida.")
                continue

            jugar_simon_pokemon(
                nombres,
                id_por_nombre=id_por_nombre,
                aliases_pokemon=aliases_pokemon,
                catalogo_pokemon=catalogo_pokemon,
                muestras_aprendidas=muestras_aprendidas,
                ser=ser,
                transcriptor=transcriptor,
                modo_voz=modo_voz,
            )
    finally:
        if ser is not None:
            ser.close()


def main() -> None:
    """Mantiene el comportamiento original del script del juego."""
    ejecutar_juego(mostrar_menu=True)


if __name__ == "__main__":
    main()
