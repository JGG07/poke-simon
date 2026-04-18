from app.desktop.pokedex import main as pokedex_main
from app.desktop.simon_pokemon import ejecutar_juego


def mostrar_menu() -> str:
    print("\nMenu de Inicio")
    print("1. Juego Simon de colores")
    print("2. Pokedex por voz")
    print("0. Salir")
    return input("Elige una opcion: ").strip()


def main() -> None:
    while True:
        opcion = mostrar_menu()

        if opcion == "0":
            print("Hasta luego.")
            return

        if opcion == "1":
            ejecutar_juego(mostrar_menu=False)
            continue

        if opcion == "2":
            pokedex_main()
            continue

        print("Opcion invalida.")


if __name__ == "__main__":
    main()
