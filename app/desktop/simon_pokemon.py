import json
import random
import re
import sys
import tempfile
import time
import unicodedata
import wave
from difflib import SequenceMatcher
from pathlib import Path

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
SOUNDS_DIR = PROJECT_ROOT / "assets" / "audio" / "pokesounds"
SERIAL_PORT = "COM11"
SERIAL_BAUDRATE = 921600
SERIAL_TIMEOUT = 1
SERIAL_ACK_TIMEOUT = 2.0
DISPLAY_SHOW_SECONDS = 1.1
DISPLAY_GAP_SECONDS = 0.18
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHUNK_SIZE = 256
PCM_PLAYBACK_GAIN = 0.10
MIC_TEST_DURATION_MS = 5000
SERIAL_AUDIO_RESPONSE_TIMEOUT = 20.0
SERIAL_AUDIO_CHUNK_DELAY = 0.003
DEBUG_SERIAL = False
VOICE_LANGUAGE = "en"
VOICE_MODEL_SIZE = "base"
VOICE_TIMEOUT_BASE_MS = 3500
VOICE_TIMEOUT_PER_POKEMON_MS = 2200
VOICE_READY_DELAY_SECONDS = 0.9
VOICE_MAX_ATTEMPTS = 2
VOICE_FUZZY_MIN_SCORE = 0.72
VOICE_FRAGMENT_SEPARATORS = r"(?:,| y | e | luego | despues | despues de | seguido de | entonces )"


def abrir_esp32():
    """Abre la conexion serial con el ESP32 si pyserial esta disponible."""
    if serial is None:
        print("Aviso: pyserial no esta disponible. Se usaran solo sonidos locales.")
        return None

    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=SERIAL_TIMEOUT)
        time.sleep(2)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(f"ESP32 conectado en {SERIAL_PORT} a {SERIAL_BAUDRATE} baudios.")
        return ser
    except Exception as error:
        print(f"No se pudo abrir el puerto serial del ESP32: {error}")
        return None


def imprimir_debug_serial(mensaje: str) -> None:
    """Imprime mensajes seriales solo cuando la depuracion esta habilitada."""
    if DEBUG_SERIAL:
        print(mensaje)


def enviar_comando_esp32(ser, comando: str) -> bool:
    """Envia un comando de una linea al ESP32 y valida el ACK esperado."""
    if ser is None:
        return False

    comando_limpio = comando.strip().upper()
    ack_esperado = f"ACK:{comando_limpio.split()[0]}"
    limite = time.time() + SERIAL_ACK_TIMEOUT

    try:
        ser.write((comando.strip() + "\n").encode("utf-8"))
        ser.flush()

        while time.time() < limite:
            respuesta = ser.readline().decode("utf-8", errors="ignore").strip()
            if not respuesta:
                continue

            imprimir_debug_serial(f"[ESP32] {respuesta}")
            if respuesta == ack_esperado:
                return True

            if respuesta.startswith("UNKNOWN:"):
                print(f"Aviso: el ESP32 no reconocio el comando '{comando}'.")
                return False

        print(f"Aviso: no se recibio {ack_esperado} desde el ESP32.")
        return False
    except Exception as error:
        print(f"Error enviando comando al ESP32: {error}")
        return False


def normalizar_texto(texto: str) -> str:
    """Normaliza texto para comparar sin acentos, mayusculas ni espacios extra."""
    texto = unicodedata.normalize("NFD", texto.strip().lower())
    texto = "".join(char for char in texto if unicodedata.category(char) != "Mn")
    return " ".join(texto.split())


def normalizar_nombre_archivo(nombre: str) -> str:
    """Convierte un nombre de Pokemon a un nombre de archivo consistente."""
    nombre_normalizado = normalizar_texto(nombre)
    nombre_normalizado = nombre_normalizado.replace(" ", "_")
    nombre_normalizado = nombre_normalizado.replace("(", "")
    nombre_normalizado = nombre_normalizado.replace(")", "")
    nombre_normalizado = nombre_normalizado.replace(".", "")
    nombre_normalizado = nombre_normalizado.replace("'", "")
    return nombre_normalizado


def construir_variantes_basicas(nombre: str) -> list[str]:
    """Hace algunas variantes simples del nombre para ayudar a reconocerlo."""
    normalizado = normalizar_texto(nombre)
    variantes = [normalizado]

    junto = normalizado.replace(" ", "")
    if junto != normalizado:
        variantes.append(junto)

    if nombre == "Bulbasaur":
        variantes.extend([
            "bulba saur",
            "bulbasor",
            "bulbasar",
            "bulbasaur",
            "bulbasor",
            "bulba",
            "bulbazor",
            "bulbasaur",
            "bulbasor",
            "bulbasaurr",
            "bulba sor",
            "bulba sur",
            "bulba saur",
            "bulbasorh",
            "bulvasor",
        ])
    elif nombre == "Charmander":
        variantes.extend([
            "char mander",
            "charmandar",
            "charmender",
            "charmander",
            "charmander",
            "charmanter",
            "charman der",
            "charmander",
            "charmander",
            "charmandar",
            "charmanderh",
            "charmandel",
            "sharmander",
            "charmanter",
            "charman der",
        ])
    elif nombre == "Squirtle":
        variantes.extend([
            "squirtel",
            "squirtul",
            "esquirtle",
            "squirtle",
            "escuirtle",
            "squirtol",
            "squir tle",
            "escuirtel",
            "escuirtul",
            "escuirtol",
            "esquirtel",
            "esquirtul",
            "escuirtle",
            "skuirtle",
            "skuirtel",
            "squirtleh",
        ])
    elif nombre == "Pikachu":
        variantes.extend([
            "pikachu",
            "pikacho",
            "pikatchu",
            "pika chu",
            "pikachuu",
            "picachu",
            "picacho",
            "pika",
            "pikashu",
            "pikasho",
            "picashu",
            "picasho",
            "pikachuu",
            "pikachuh",
            "picachu",
            "pica chu",
            "pika chuu",
        ])

    return list(dict.fromkeys(variantes))


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


def construir_aliases_pokemon(nombres: list[str]) -> dict[tuple[str, ...], str]:
    """Construye aliases normalizados para detectar nombres dentro de una transcripcion."""
    aliases: dict[tuple[str, ...], str] = {}

    for nombre in nombres:
        for variante in construir_variantes_basicas(nombre):
            tokens = tuple(token for token in re.split(r"[^a-z0-9]+", variante) if token)
            if tokens:
                aliases[tokens] = nombre

    return aliases


def construir_catalogo_pokemon(nombres: list[str]) -> list[tuple[str, str]]:
    """Crea una lista de nombres normalizados para matching difuso."""
    catalogo = []
    for nombre in nombres:
        for variante in construir_variantes_basicas(nombre):
            catalogo.append((normalizar_texto(variante), nombre))
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


def mostrar_pokemon_en_esp32(ser, numero_pokemon: str | None) -> bool:
    """Manda a la ESP32 el numero del Pokemon para mostrarlo en el display."""
    if ser is None or not numero_pokemon:
        return False

    return enviar_comando_esp32(ser, f"SHOW {numero_pokemon}")


def limpiar_display_esp32(ser) -> bool:
    """Limpia temporalmente el display de la ESP32."""
    return enviar_comando_esp32(ser, "CLEAR")


def liberar_display_esp32(ser) -> bool:
    """Libera el display para que vuelva a su comportamiento normal."""
    return enviar_comando_esp32(ser, "UNLOCK")


def mostrar_mensaje_esp32(ser, linea1: str, linea2: str = "") -> bool:
    """Muestra un mensaje corto en el display de la ESP32."""
    if ser is None:
        return False

    texto1 = linea1.strip().replace("|", " ")[:16]
    texto2 = linea2.strip().replace("|", " ")[:16]
    return enviar_comando_esp32(ser, f"TEXT {texto1}|{texto2}")


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
    if ser is None:
        return ""

    timeout_original = ser.timeout
    try:
        ser.timeout = timeout
        return ser.readline().decode("utf-8", errors="ignore").strip()
    finally:
        ser.timeout = timeout_original


def leer_linea_serial_no_vacia(ser, timeout: float) -> str:
    """Lee la siguiente linea no vacia desde el puerto serial."""
    limite = time.time() + timeout

    while time.time() < limite:
        restante = max(0.1, limite - time.time())
        linea = leer_linea_serial(ser, timeout=restante)
        if linea:
            return linea

    return ""


def leer_bytes_serial(ser, total_bytes: int, timeout: float) -> bytes:
    """Lee una cantidad exacta de bytes desde el puerto serial."""
    if ser is None or total_bytes <= 0:
        return b""

    limite = time.time() + timeout
    recibido = bytearray()

    while len(recibido) < total_bytes and time.time() < limite:
        chunk = ser.read(min(AUDIO_CHUNK_SIZE, total_bytes - len(recibido)))
        if not chunk:
            continue
        recibido.extend(chunk)

    return bytes(recibido)


def esperar_respuesta_esp32(ser, esperadas: set[str], timeout: float) -> str:
    """Espera una respuesta de texto de la ESP32 e imprime lineas relevantes."""
    limite = time.time() + timeout

    while time.time() < limite:
        restante = max(0.1, limite - time.time())
        linea = leer_linea_serial_no_vacia(ser, timeout=restante)
        if not linea:
            continue

        imprimir_debug_serial(f"[ESP32] {linea}")
        if linea in esperadas:
            return linea

    return ""


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

        cabecera = leer_linea_serial(ser, timeout=5.0)
        if not cabecera.startswith("!AUDIO "):
            if cabecera:
                imprimir_debug_serial(f"[ESP32] {cabecera}")
            else:
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


def cargar_transcriptor_voz():
    """Carga el modelo de Whisper si faster-whisper esta disponible."""
    if WhisperModel is None:
        return None

    try:
        print(f"Cargando modelo de voz '{VOICE_MODEL_SIZE}'...")
        return WhisperModel(VOICE_MODEL_SIZE)
    except Exception as error:
        print(f"Aviso: no se pudo cargar faster-whisper: {error}")
        return None


def transcribir_wav_con_whisper(transcriptor, audio_path: Path, language: str | None = None) -> str:
    """Transcribe un WAV con faster-whisper y devuelve el texto unido."""
    if transcriptor is None:
        return ""

    try:
        segmentos, _ = transcriptor.transcribe(
            str(audio_path),
            language=language or VOICE_LANGUAGE,
            vad_filter=True,
            beam_size=5,
        )
        partes = [segmento.text.strip() for segmento in segmentos if segmento.text.strip()]
        return " ".join(partes).strip()
    except Exception as error:
        print(f"Aviso: no se pudo transcribir el audio: {error}")
        return ""


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
    for candidato in candidatos:
        limpio = " ".join(candidato.split())
        if limpio:
            fragmentos.append(limpio)
    return fragmentos


def buscar_mejor_pokemon(fragmento: str, catalogo_pokemon: list[tuple[str, str]]) -> tuple[str | None, float]:
    """Busca el nombre de Pokemon mas cercano para un fragmento libre."""
    mejor_nombre = None
    mejor_puntaje = 0.0
    fragmento_normalizado = normalizar_texto(fragmento)

    if not fragmento_normalizado:
        return None, 0.0

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
) -> tuple[list[str], str]:
    """Graba voz desde la ESP32, la transcribe y extrae la secuencia de Pokemon pronunciada."""
    if ser is None or transcriptor is None:
        return [], ""

    duracion_ms = VOICE_TIMEOUT_BASE_MS + (max(1, longitud_esperada) * VOICE_TIMEOUT_PER_POKEMON_MS)
    mostrar_mensaje_esp32(ser, "Tu turno", "Habla ahora")
    print(f"Habla ahora. Tienes aproximadamente {duracion_ms / 1000:.1f} segundos...")
    time.sleep(VOICE_READY_DELAY_SECONDS)

    pcm = grabar_microfono_esp32(ser, duracion_ms=duracion_ms)
    if not pcm:
        return [], ""

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
    ), texto


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
    num_por_nombre: dict[str, str],
    sounds_dir: Path,
    ser=None,
) -> None:
    """Muestra la secuencia de Pokemon en el display y prueba el cry en ESP32."""
    for nombre in secuencia:
        mostrar_pokemon_en_esp32(ser, num_por_nombre.get(nombre))
        reproducir_audio_pokemon(nombre, sounds_dir, ser=ser)
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
) -> tuple[list[str], str]:
    """Obtiene la respuesta del jugador, con una segunda oportunidad por voz."""
    if not modo_voz or ser is None or transcriptor is None:
        print("Aviso: no hay reconocimiento por voz disponible.")
        return [], ""

    ultimo_texto = ""
    for intento in range(VOICE_MAX_ATTEMPTS):
        if intento == 1:
            mostrar_mensaje_esp32(ser, "Repitelo", "una vez mas")
            print("No te entendi bien. Intentalo una vez mas.")

        respuesta, texto = escuchar_respuesta_por_voz(
            ser,
            transcriptor=transcriptor,
            aliases_pokemon=aliases_pokemon,
            catalogo_pokemon=catalogo_pokemon,
            longitud_esperada=len(secuencia),
        )
        ultimo_texto = texto
        if respuesta:
            return respuesta, texto

    print("No pude entender la secuencia por voz.")
    mostrar_mensaje_esp32(ser, "No entendi", "Fin del juego")
    return [], ultimo_texto


def secuencias_iguales(secuencia_correcta: list[str], respuesta_usuario: list[str]) -> bool:
    """Compara dos secuencias de forma tolerante a formato."""
    if len(secuencia_correcta) != len(respuesta_usuario):
        return False

    correcta_normalizada = [normalizar_texto(nombre) for nombre in secuencia_correcta]
    respuesta_normalizada = [normalizar_texto(nombre) for nombre in respuesta_usuario]
    return correcta_normalizada == respuesta_normalizada


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
    num_por_nombre: dict[str, str],
    sounds_dir: Path,
    aliases_pokemon: dict[tuple[str, ...], str],
    catalogo_pokemon: list[tuple[str, str]],
    ser=None,
    transcriptor=None,
    modo_voz: bool = False,
) -> None:
    """Ejecuta el ciclo principal del juego."""
    secuencia = []
    puntaje = 0

    print("Bienvenido a Simon Pokemon.")
    if modo_voz and ser is not None and transcriptor is not None:
        print("Mira la secuencia en el display y luego repitela hablando al microfono.")
    else:
        print("Aviso: no hay reconocimiento por voz disponible en este momento.")
    print("El juego termina cuando falles.\n")
    notificar_inicio_juego(ser)
    mostrar_mensaje_esp32(ser, "Simon Pokemon", "Preparate")

    while True:
        nuevo_pokemon = obtener_siguiente_pokemon(nombres)
        secuencia.append(nuevo_pokemon)

        print(f"Ronda {len(secuencia)}")
        notificar_inicio_ronda(ser)
        mostrar_mensaje_esp32(ser, f"Ronda {len(secuencia)}", "Memoriza")
        print("Observa la secuencia en el display...")
        mostrar_secuencia_en_display(secuencia, num_por_nombre, sounds_dir, ser=ser)

        respuesta, texto_detectado = leer_respuesta_jugador(
            secuencia,
            ser=ser,
            transcriptor=transcriptor,
            aliases_pokemon=aliases_pokemon,
            catalogo_pokemon=catalogo_pokemon,
            modo_voz=modo_voz,
        )
        if texto_detectado:
            print(f"Pokemon detectados: {', '.join(respuesta) if respuesta else '(ninguno)'}")

        if secuencias_iguales(secuencia, respuesta):
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


def main() -> None:
    """Carga datos y arranca el juego."""
    try:
        nombres = cargar_nombres_pokemon(POKEDEX_FILE)
        num_por_nombre = cargar_num_por_nombre(POKEDEX_FILE)
    except (FileNotFoundError, ValueError) as error:
        print(f"Error: {error}")
        sys.exit(1)

    aliases_pokemon = construir_aliases_pokemon(nombres)
    catalogo_pokemon = construir_catalogo_pokemon(nombres)
    ser = abrir_esp32()
    transcriptor = cargar_transcriptor_voz()
    modo_voz = ser is not None and transcriptor is not None

    if transcriptor is None:
        print("Aviso: faster-whisper no esta instalado. El juego no podra usar reconocimiento por voz.")

    try:
        probar_esp32(ser)
        while True:
            opcion = mostrar_menu_principal()
            if opcion == "0":
                return
            if opcion != "1":
                print("Opcion invalida.")
                continue

            jugar_simon_pokemon(
                nombres,
                num_por_nombre=num_por_nombre,
                sounds_dir=SOUNDS_DIR,
                aliases_pokemon=aliases_pokemon,
                catalogo_pokemon=catalogo_pokemon,
                ser=ser,
                transcriptor=transcriptor,
                modo_voz=modo_voz,
            )
    finally:
        if ser is not None:
            ser.close()


if __name__ == "__main__":
    main()
