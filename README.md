# Proyecto Pokemon

Este proyecto lo hicimos para usar una pokedex con Python y una ESP32.

Tiene 2 partes:

- una pokedex por voz
- un juego tipo simon con pokemones

La idea general es que la compu haga la mayor parte de la logica y la ESP32 ayude con el display, sonidos y microfono.

## Cosas que tiene

- juego de simon pokemon
- pokedex por voz
- display con la ESP32
- reproduccion de audio
- lectura de `pokedex.json`

## Pokemon que usa ahorita el simon

Por ahorita el juego esta simplificado y solo usa estos 4:

- Bulbasaur
- Charmander
- Squirtle
- Pikachu

## Archivos importantes

- `app/desktop/simon_pokemon.py`
- `app/desktop/pokedex.py`
- `data/pokedex.json`
- `firmware/projects/pokedex-c/pokedex-c.ino`

## Como correr el proyecto

Primero instalar dependencias. No estan todas muy ordenadas pero con esto normalmente jala:

```powershell
pip install pyserial numpy faster-whisper pyttsx3
```

Para correr el juego:

```powershell
python simon_pokemon.py
```

Para correr la pokedex:

```powershell
python pokedex.py
```

## Como funciona el simon

1. Lee los pokemones del json.
2. Escoge pokemones al azar.
3. Los muestra en el display.
4. Reproduce el audio si encuentra el wav.
5. El jugador repite la secuencia por voz.
6. Si se equivoca se acaba el juego.

## Notas

- el puerto serial se cambia directo en el codigo
- ahorita el puerto que esta puesto es `COM11`
- si no esta la ESP32 algunas cosas no van a funcionar igual
- si no esta `faster-whisper` no va a servir la parte de voz

## Estructura medio rapida

```text
pokemon-micropython/
|-- app/
|   `-- desktop/
|       |-- pokedex.py
|       `-- simon_pokemon.py
|-- assets/
|   `-- audio/
|       `-- pokesounds/
|-- data/
|   `-- pokedex.json
|-- firmware/
|   `-- projects/
|       `-- pokedex-c/
|           `-- pokedex-c.ino
|-- pokedex.py
|-- simon_pokemon.py
`-- README.md
```

## Algunas cosas del firmware

- usa comandos por serial
- muestra cosas en el display
- reproduce audio
- tambien puede grabar audio del microfono

## Cosas pendientes o mejorables

- mejorar reconocimiento de voz
- mejorar tiempos del juego
- hacer mejor la documentacion
- limpiar codigo repetido
- agregar mas pokemones si hace falta
