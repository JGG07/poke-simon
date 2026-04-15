# Simon Pokemon

Este es mi proyecto de un juego tipo Simon hecho con Python y una ESP32.

La computadora corre la logica principal del juego y la ESP32 se encarga del display, audio y microfono cuando esta conectada.

## Que hace

- genera una secuencia aleatoria de Pokemon
- muestra cada Pokemon en el display de la ESP32
- reproduce su sonido
- escucha la respuesta del jugador por voz
- compara la secuencia y termina cuando el jugador falla

## Hardware

- ESP32-S3 de 16mb
- Micrófono INMP441
- Amplificador MAX98357A
- Bocina genérica de 5 volts.


## Archivos importantes

- `simon_pokemon.py`
- `app/desktop/simon_pokemon.py`
- `data/pokedex.json`
- `firmware/projects/pokedex-c/pokedex-c.ino`

## Como correr el proyecto

Instala dependencias:

```powershell
pip install pyserial faster-whisper
```

Ejecuta el juego:

```powershell
python simon_pokemon.py
```

## Como funciona

1. El juego carga los nombres y numeros de Pokemon desde `data/pokedex.json`.
2. En cada ronda agrega un Pokemon aleatorio a la secuencia.
3. La ESP32 muestra la secuencia en pantalla y reproduce el audio.
4. El jugador repite la secuencia hablando al microfono.
5. El programa transcribe la voz y valida el orden.
6. Si hay un error, el juego termina y muestra el puntaje.

## Librerías

1. Faster Whisper: Faster whisper es la librería encargada de pasar el audio en formato wav a texto y así poder hacer que el juego lo entienda.
2. Pyserial: Es el que hace la conexión con la esp32s3 para la transferencia de datos.
3. Wave: Convierte el texto a audio wav.
4. Json: Librería que permite leer archivos json.
5. Random: Libería que se usa para sacar de una lista un dato aleatorio.
6. re: Esta librería proporciona operaciones de coincidencia de expresiones regulares similares a las encontradas en Perl.
7. sys: Esta librería proporciona acceso a algunas variables utilizadas o mantenidas por el intérprete y a funciones que interactúan estrechamente con él.
8. tempfile: Esta librería es para manejar archivos temporales.
9. time: Esta librería provee varias funciones para manipular valores de tiempo.
10. unicodedata: Esta librería proporciona acceso a la base de datos de caracteres Unicode (UCD), que define las propiedades de todos los caracteres.
11. SequenceMatcher: Esta librería se usa para comparar pares de secuencias para encontrar similitudes y diferencias.
12. path: Esta librería se usa para la gestión de rutas de archivos.

## Notas

- El puerto serial actual esta configurado como `COM11` en `app/desktop/simon_pokemon.py`. (Se tiene que configurar conforme al COM que conectó en su sistema).
- Si no hay ESP32 conectada, no funcionaran igual el display, microfono y audio por serial.
- Si falta `faster-whisper`, el reconocimiento por voz no estara disponible.

## Estructura rapida

```text
pokemon-micropython/
|-- app/
|   `-- desktop/
|       `-- simon_pokemon.py
|-- assets/
|   |-- audio/
|   |   `-- pokesounds/
|   `-- display/
|-- data/
|   `-- pokedex.json
|-- firmware/
|   |-- projects/
|   |   `-- pokedex-c/
|   |       `-- pokedex-c.ino
|   `-- releases/
|-- simon_pokemon.py
`-- README.md
```

## Firmware

- Recibe el nombre de los pokemones através del serial.
- Muestra la imagen del Pokemon, su sonido y texto en el display.
- Reproduce audio cargado desde la PC.
- Puede grabar audio del microfono INMP441.

## Pendiente

- Mejorar reconocimiento de voz.
- Ajustar tiempos y dificultad.
- Limpiar nombres heredados del proyecto.
- Mejorar la documentacion.
