# Simon Pokemon

Este proyecto es un juego tipo Simon hecho con Python y una ESP32.

La computadora corre la logica principal del juego y la ESP32 se encarga del display, audio y microfono cuando esta conectada.

## Que hace

- genera una secuencia aleatoria de Pokemon
- muestra cada Pokemon en el display de la ESP32
- reproduce su sonido
- escucha la respuesta del jugador por voz
- compara la secuencia y termina cuando el jugador falla

## Archivos importantes

- `simon_pokemon.py`
- `app/desktop/simon_pokemon.py`
- `data/pokedex.json`
- `firmware/projects/pokedex-c/pokedex-c.ino`

Nota: algunos archivos conservan nombres viejos como `pokedex.json` o `pokedex-c`, pero el proyecto actual es solo el juego Simon Pokemon.

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

## Notas

- el puerto serial actual esta configurado como `COM11` en `app/desktop/simon_pokemon.py`
- si no hay ESP32 conectada, no funcionaran igual el display, microfono y audio por serial
- si falta `faster-whisper`, el reconocimiento por voz no estara disponible

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

- recibe comandos por serial
- muestra Pokemon y texto en el display
- reproduce audio cargado desde la PC
- puede grabar audio del microfono

## Pendiente

- mejorar reconocimiento de voz
- ajustar tiempos y dificultad
- limpiar nombres heredados del proyecto
- mejorar la documentacion
