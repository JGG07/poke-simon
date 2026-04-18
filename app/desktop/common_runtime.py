import time
from pathlib import Path


def open_serial_connection(
    serial_module,
    port: str,
    baudrate: int,
    timeout: float,
    unavailable_message: str,
    connected_message: str,
    open_error_message: str,
):
    if serial_module is None:
        print(unavailable_message)
        return None

    try:
        ser = serial_module.Serial(port, baudrate, timeout=timeout)
        time.sleep(2)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        print(connected_message.format(port=port, baudrate=baudrate))
        return ser
    except Exception as error:
        print(open_error_message.format(error=error))
        return None


def debug_serial_message(enabled: bool, message: str) -> None:
    if enabled:
        print(message)


def send_command_esp32(
    ser,
    command: str,
    ack_timeout: float,
    debug_enabled: bool = False,
) -> bool:
    if ser is None:
        return False

    command_clean = command.strip().upper()
    ack_expected = f"ACK:{command_clean.split()[0]}"
    deadline = time.time() + ack_timeout

    try:
        ser.write((command.strip() + "\n").encode("utf-8"))
        ser.flush()

        while time.time() < deadline:
            response = ser.readline().decode("utf-8", errors="ignore").strip()
            if not response:
                continue

            debug_serial_message(debug_enabled, f"[ESP32] {response}")
            if response == ack_expected:
                return True

            if response.startswith("UNKNOWN:"):
                print(f"Aviso: el ESP32 no reconocio el comando '{command}'.")
                return False

        print(f"Aviso: no se recibio {ack_expected} desde el ESP32.")
        return False
    except Exception as error:
        print(f"Error enviando comando al ESP32: {error}")
        return False


def show_message_esp32(ser, ack_timeout: float, debug_enabled: bool, line1: str, line2: str = "") -> bool:
    if ser is None:
        return False

    text1 = line1.strip().replace("|", " ")[:16]
    text2 = line2.strip().replace("|", " ")[:16]
    return send_command_esp32(ser, f"TEXT {text1}|{text2}", ack_timeout, debug_enabled)


def show_pokemon_esp32(ser, ack_timeout: float, debug_enabled: bool, pokemon_number: str | None) -> bool:
    if ser is None or not pokemon_number:
        return False

    return send_command_esp32(ser, f"SHOW {pokemon_number}", ack_timeout, debug_enabled)


def clear_display_esp32(ser, ack_timeout: float, debug_enabled: bool) -> bool:
    return send_command_esp32(ser, "CLEAR", ack_timeout, debug_enabled)


def unlock_display_esp32(ser, ack_timeout: float, debug_enabled: bool) -> bool:
    return send_command_esp32(ser, "UNLOCK", ack_timeout, debug_enabled)


def read_serial_line(ser, timeout: float) -> str:
    if ser is None:
        return ""

    original_timeout = ser.timeout
    try:
        ser.timeout = timeout
        return ser.readline().decode("utf-8", errors="ignore").strip()
    finally:
        ser.timeout = original_timeout


def read_serial_line_non_empty(ser, timeout: float) -> str:
    deadline = time.time() + timeout

    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        line = read_serial_line(ser, timeout=remaining)
        if line:
            return line

    return ""


def read_serial_bytes(ser, total_bytes: int, chunk_size: int, timeout: float) -> bytes:
    if ser is None or total_bytes <= 0:
        return b""

    deadline = time.time() + timeout
    received = bytearray()

    while len(received) < total_bytes and time.time() < deadline:
        chunk = ser.read(min(chunk_size, total_bytes - len(received)))
        if not chunk:
            continue
        received.extend(chunk)

    return bytes(received)


def wait_serial_response(ser, expected: set[str], timeout: float, debug_enabled: bool = False) -> str:
    deadline = time.time() + timeout

    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        line = read_serial_line_non_empty(ser, timeout=remaining)
        if not line:
            continue

        debug_serial_message(debug_enabled, f"[ESP32] {line}")
        if line in expected:
            return line

    return ""


def load_whisper_model(whisper_model_cls, model_size: str, device: str | None = None, compute_type: str | None = None):
    if whisper_model_cls is None:
        return None

    try:
        print(f"Cargando modelo de voz '{model_size}'...")
        kwargs = {}
        if device is not None:
            kwargs["device"] = device
        if compute_type is not None:
            kwargs["compute_type"] = compute_type
        return whisper_model_cls(model_size, **kwargs)
    except Exception as error:
        print(f"Aviso: no se pudo cargar faster-whisper: {error}")
        return None


def transcribe_wav_with_whisper(transcriber, audio_path: Path, language: str | None = None, **kwargs) -> str:
    if transcriber is None:
        return ""

    try:
        transcribe_kwargs = dict(kwargs)
        if language is not None:
            transcribe_kwargs["language"] = language
        segments, _ = transcriber.transcribe(str(audio_path), **transcribe_kwargs)
        parts = [segment.text.strip() for segment in segments if segment.text.strip()]
        return " ".join(parts).strip()
    except Exception as error:
        print(f"Aviso: no se pudo transcribir el audio: {error}")
        return ""
