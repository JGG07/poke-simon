#pragma once

#include <Adafruit_SSD1306.h>
#include "PokedexData.h"

class DisplayManager
{
public:

    void init();

    void clear();

    void render();

    void drawBitmap(int x, int y, const uint8_t* bitmap, int w, int h);

    void drawPokemonInfo(int pokemonIndex);

    void drawText(int x, int y, const char* text, int size = 1);

private:

    Adafruit_SSD1306 display = Adafruit_SSD1306(128, 64, &Wire, -1);
};
