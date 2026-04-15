#include "DisplayManager.h"
#include "PokedexData.h"
#include "Config.h"

void DisplayManager::init()
{
    Wire.begin(OLED_SDA, OLED_SCL);   // SDA, SCL

    display.begin(SSD1306_SWITCHCAPVCC, 0x3C);

    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);

    display.setCursor(0,0);
    display.println("Pokedex Boot");

    display.display();
}

void DisplayManager::clear()
{
    display.clearDisplay();
}

void DisplayManager::render()
{
    display.display();
}

void DisplayManager::drawBitmap(
    int x,
    int y,
    const uint8_t* bitmap,
    int w,
    int h
)
{
    display.drawBitmap(x, y, bitmap, w, h, SSD1306_WHITE);
}

void DisplayManager::drawText(int x, int y, const char* text, int size)
{
    display.setTextSize(size);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(x, y);
    display.print(text);
}

void DisplayManager::drawPokemonInfo(int pokemonIndex)
{
    PokemonInfo &p = pokedex[pokemonIndex];

    int x = 64;
    int y = 0;

    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);

    display.setCursor(x, y);
    display.print("#");
    display.print(pokemonIndex + 1);

    y += 10;

    display.setCursor(x, y);
    display.println(p.name);

    y += 10;

    display.setCursor(x, y);
    display.print("H:");
    display.print(p.height);
    display.println("m");

    y += 10;

    display.setCursor(x, y);
    display.print("W:");
    display.print(p.weight);
    display.println("kg");

    y += 10;

    display.setCursor(x, y);
    display.print("T1:");
    display.println(p.type1);

    y += 10;

    display.setCursor(x, y);
    display.print("T2:");
    display.println(p.type2);
}
