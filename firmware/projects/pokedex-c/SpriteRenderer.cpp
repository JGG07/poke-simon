#include "SpriteRenderer.h"
#include "PokedexSprites.h"
#include "DisplayManager.h"

extern DisplayManager displayManager;

static uint8_t spriteBuffer[(SPRITE_WIDTH * SPRITE_HEIGHT) / 8];

void SpriteRenderer::drawPokemon(int index, int x, int y)
{

    int row = index / SPRITES_PER_ROW;
    int col = index % SPRITES_PER_ROW;

    int spriteX = col * SPRITE_WIDTH;
    int spriteY = row * SPRITE_HEIGHT;

    int bytesPerRowSheet = POKEDEX_WIDTH / 8;
    int bytesPerRowSprite = SPRITE_WIDTH / 8;

    for(int r = 0; r < SPRITE_HEIGHT; r++)
    {

        int sheetOffset =
            (spriteY + r) * bytesPerRowSheet +
            (spriteX / 8);

        int bufferOffset =
            r * bytesPerRowSprite;

        memcpy_P(
            spriteBuffer + bufferOffset,
            pokedex_compact + sheetOffset,
            bytesPerRowSprite
        );
    }

    displayManager.drawBitmap(
        x,
        y,
        spriteBuffer,
        SPRITE_WIDTH,
        SPRITE_HEIGHT
    );
}