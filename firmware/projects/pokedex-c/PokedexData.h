#pragma once

struct PokemonInfo
{
    const char* name;
    float height;
    float weight;
    const char* type1;
    const char* type2;
};

extern PokemonInfo pokedex[151];