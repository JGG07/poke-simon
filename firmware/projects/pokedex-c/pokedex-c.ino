#include <Arduino.h>
#include <driver/i2s.h>
#include <math.h>

#include "DisplayManager.h"
#include "HeroLogos.h"
#include "SpriteRenderer.h"
#include "StartupLogo.h"

DisplayManager displayManager;

int pokemonIndex = 0;
unsigned long lastChange = 0;
const unsigned long changeInterval = 1000;
bool displayLocked = false;
bool displayBlank = false;
bool statusMessageActive = false;
bool heroModeActive = false;
bool startupAnimationActive = true;
bool microphoneStreamingActive = false;
unsigned long startupAnimationStart = 0;
String statusLine1;
String statusLine2;
int heroIndex = -1;

#define SPK_PORT I2S_NUM_1
#define SPK_BCLK 18
#define SPK_LRC 17
#define SPK_DIN 16

#define MIC_PORT I2S_NUM_0
#define MIC_SCK 5
#define MIC_WS 6
#define MIC_SD 7

#define SAMPLE_RATE 16000
#define BUFFER_FRAMES 256
#define SERIAL_BAUDRATE 921600
#define PCM_CHUNK_BYTES 1024
#define MIC_MAX_RECORD_MS 28000
#define TONE_AMPLITUDE 3400
#define AUDIO_LOAD_TIMEOUT_MS 10000

const unsigned long ANIMATION_DURATION_MS = 2600;
const int ANIMATION_LOGO_START_X = 128;
const int ANIMATION_LOGO_END_X = -STARTUP_LOGO_WIDTH;
const int ANIMATION_LOGO_Y = 5;

String serialLine;
uint8_t* audioBuffer = nullptr;
size_t audioBufferSize = 0;

void renderStatusMessage() {
    displayManager.clear();
    displayManager.drawText(0, 8, statusLine1.c_str(), 2);

    if (statusLine2.length() > 0) {
        displayManager.drawText(0, 36, statusLine2.c_str(), 1);
    }

    displayManager.render();
}

void renderHeroCard() {
    displayManager.clear();

    if (heroIndex == 0) {
        displayManager.drawText(18, 20, "Color:", 2);
        displayManager.drawText(24, 48, "Azul", 2);
    } else if (heroIndex == 1) {
        displayManager.drawText(18, 20, "Color:", 2);
        displayManager.drawText(2, 48, "Amarillo", 2);
    } else if (heroIndex == 2) {
        displayManager.drawText(18, 20, "Color:", 2);
        displayManager.drawText(24, 48, "Rojo", 2);
    } else if (heroIndex == 3) {
        displayManager.drawText(18, 20, "Color:", 2);
        displayManager.drawText(16, 48, "Verde", 2);
    }

    displayManager.render();
}

void initSpeaker() {
    const i2s_config_t spkConfig = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = BUFFER_FRAMES,
        .use_apll = false,
        .tx_desc_auto_clear = true,
        .fixed_mclk = 0
    };

    const i2s_pin_config_t spkPins = {
        .bck_io_num = SPK_BCLK,
        .ws_io_num = SPK_LRC,
        .data_out_num = SPK_DIN,
        .data_in_num = I2S_PIN_NO_CHANGE
    };

    i2s_driver_install(SPK_PORT, &spkConfig, 0, NULL);
    i2s_set_pin(SPK_PORT, &spkPins);
    i2s_zero_dma_buffer(SPK_PORT);
}

void initMicrophone() {
    const i2s_config_t micConfig = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = BUFFER_FRAMES,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0
    };

    const i2s_pin_config_t micPins = {
        .bck_io_num = MIC_SCK,
        .ws_io_num = MIC_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = MIC_SD
    };

    i2s_driver_install(MIC_PORT, &micConfig, 0, NULL);
    i2s_set_pin(MIC_PORT, &micPins);
}

void playTone(float freq, int durationMs, int amplitude = TONE_AMPLITUDE) {
    int16_t buffer[BUFFER_FRAMES * 2];
    float phase = 0.0f;
    const float phaseStep = 2.0f * PI * freq / SAMPLE_RATE;
    const int totalFrames = (SAMPLE_RATE * durationMs) / 1000;
    int sentFrames = 0;

    while (sentFrames < totalFrames) {
        const int framesThisChunk = min(BUFFER_FRAMES, totalFrames - sentFrames);

        for (int i = 0; i < framesThisChunk; i++) {
            const int16_t sample = (int16_t)(sinf(phase) * amplitude);
            buffer[i * 2] = sample;
            buffer[i * 2 + 1] = sample;

            phase += phaseStep;
            if (phase >= 2.0f * PI) {
                phase -= 2.0f * PI;
            }
        }

        size_t bytesWritten = 0;
        i2s_write(
            SPK_PORT,
            buffer,
            framesThisChunk * 2 * sizeof(int16_t),
            &bytesWritten,
            portMAX_DELAY
        );

        sentFrames += framesThisChunk;
    }
}

void soundSuccess() {
    playTone(880.0f, 140);
    delay(40);
    playTone(1175.0f, 180);
}

void soundError() {
    playTone(440.0f, 220);
    delay(40);
    playTone(330.0f, 320);
}

void soundStart() {
    playTone(660.0f, 120);
    delay(35);
    playTone(880.0f, 120);
}

void soundRound() {
    playTone(740.0f, 100);
}

void soundGameOver() {
    playTone(520.0f, 150);
    delay(40);
    playTone(420.0f, 150);
    delay(40);
    playTone(320.0f, 260);
}

bool readExactBytes(uint8_t* buffer, size_t totalBytes, uint32_t timeoutMs) {
    size_t bytesRead = 0;
    unsigned long lastDataAt = millis();

    while (bytesRead < totalBytes) {
        while (Serial.available() && bytesRead < totalBytes) {
            buffer[bytesRead++] = (uint8_t)Serial.read();
            lastDataAt = millis();
        }

        if (millis() - lastDataAt > timeoutMs) {
            return false;
        }

        delay(1);
    }

    return true;
}

void clearAudioBuffer() {
    if (audioBuffer != nullptr) {
        free(audioBuffer);
        audioBuffer = nullptr;
        audioBufferSize = 0;
    }
}

bool loadPcmToBuffer(size_t totalBytes) {
    clearAudioBuffer();

    audioBuffer = (uint8_t*)malloc(totalBytes);
    if (audioBuffer == nullptr) {
        return false;
    }

    if (!readExactBytes(audioBuffer, totalBytes, AUDIO_LOAD_TIMEOUT_MS)) {
        clearAudioBuffer();
        return false;
    }

    audioBufferSize = totalBytes;
    return true;
}

bool playBufferedAudio() {
    if (audioBuffer == nullptr || audioBufferSize == 0) {
        return false;
    }

    int16_t stereoBuffer[PCM_CHUNK_BYTES];
    size_t offset = 0;

    while (offset < audioBufferSize) {
        const size_t chunkBytes = min((size_t)PCM_CHUNK_BYTES, audioBufferSize - offset);
        const size_t sampleCount = chunkBytes / 2;

        for (size_t i = 0; i < sampleCount; i++) {
            const uint8_t low = audioBuffer[offset + (i * 2)];
            const uint8_t high = audioBuffer[offset + (i * 2) + 1];
            const int16_t sample = (int16_t)(low | (high << 8));
            stereoBuffer[i * 2] = sample;
            stereoBuffer[i * 2 + 1] = sample;
        }

        size_t bytesWritten = 0;
        i2s_write(
            SPK_PORT,
            stereoBuffer,
            sampleCount * 2 * sizeof(int16_t),
            &bytesWritten,
            portMAX_DELAY
        );

        offset += chunkBytes;
    }

    return true;
}

bool streamMicrophoneAudio(uint32_t durationMs) {
    if (durationMs == 0 || durationMs > MIC_MAX_RECORD_MS) {
        return false;
    }

    const size_t totalFrames = ((size_t)SAMPLE_RATE * durationMs) / 1000;
    const size_t totalBytes = totalFrames * sizeof(int16_t);
    int16_t pcmFrames[BUFFER_FRAMES];
    size_t framesSent = 0;

    Serial.print("!AUDIO ");
    Serial.println(totalBytes);

    while (framesSent < totalFrames) {
        const size_t framesRequested = min((size_t)BUFFER_FRAMES, totalFrames - framesSent);
        const size_t bytesRequested = framesRequested * sizeof(int16_t);
        size_t bytesRead = 0;

        esp_err_t result = i2s_read(
            MIC_PORT,
            pcmFrames,
            bytesRequested,
            &bytesRead,
            pdMS_TO_TICKS(250)
        );

        if (result != ESP_OK || bytesRead == 0) {
            return false;
        }

        const size_t frameCount = bytesRead / sizeof(int16_t);
        if (frameCount == 0) {
            return false;
        }

        Serial.write((const uint8_t*)pcmFrames, frameCount * sizeof(int16_t));
        framesSent += frameCount;
    }

    Serial.println();
    Serial.println("!DONE");
    return true;
}

bool streamMicrophoneChunk() {
    int16_t pcmFrames[BUFFER_FRAMES];
    const size_t bytesRequested = BUFFER_FRAMES * sizeof(int16_t);
    size_t bytesRead = 0;

    esp_err_t result = i2s_read(
        MIC_PORT,
        pcmFrames,
        bytesRequested,
        &bytesRead,
        pdMS_TO_TICKS(250)
    );

    if (result != ESP_OK || bytesRead == 0) {
        return false;
    }

    Serial.print("!PCM ");
    Serial.println(bytesRead);
    Serial.write((const uint8_t*)pcmFrames, bytesRead);
    return true;
}

void processCommand(const String& rawCommand) {
    String command = rawCommand;
    command.trim();

    if (command.startsWith("TEXT ")) {
        const String payload = command.substring(5);
        const int separator = payload.indexOf('|');

        if (separator >= 0) {
            statusLine1 = payload.substring(0, separator);
            statusLine2 = payload.substring(separator + 1);
        } else {
            statusLine1 = payload;
            statusLine2 = "";
        }

        statusLine1.trim();
        statusLine2.trim();
        statusMessageActive = true;
        heroModeActive = false;
        startupAnimationActive = false;
        displayLocked = true;
        displayBlank = false;
        renderStatusMessage();
        Serial.println("ACK:TEXT");
        return;
    }

    if (command.startsWith("SHOW ")) {
        const String numberText = command.substring(5);
        const int pokedexNumber = numberText.toInt();

        if (pokedexNumber >= 1 && pokedexNumber <= 151) {
            pokemonIndex = pokedexNumber - 1;
            statusMessageActive = false;
            heroModeActive = false;
            displayLocked = true;
            displayBlank = false;
            Serial.println("ACK:SHOW");
        } else {
            Serial.println("UNKNOWN:SHOW");
        }
        return;
    }

    if (command.startsWith("HERO ")) {
        const String heroText = command.substring(5);
        const int heroNumber = heroText.toInt();

        if (heroNumber >= 1 && heroNumber <= 4) {
            heroIndex = heroNumber - 1;
            statusMessageActive = false;
            heroModeActive = true;
            displayLocked = true;
            displayBlank = false;
            Serial.println("ACK:HERO");
        } else {
            Serial.println("UNKNOWN:HERO");
        }
        return;
    }

    if (command.startsWith("!LOAD ")) {
        const String sizeText = command.substring(6);
        const int totalBytes = sizeText.toInt();

        if (totalBytes <= 0) {
            Serial.println("!ERROR");
            return;
        }

        Serial.println("!READY");
        const bool ok = loadPcmToBuffer((size_t)totalBytes);
        if (!ok) {
            Serial.println("!ERROR");
            return;
        }

        Serial.println("!BUFFERED");
        return;
    }

    if (command == "!PLAYBUF") {
        const bool ok = playBufferedAudio();
        if (!ok) {
            Serial.println("!ERROR");
            return;
        }

        Serial.println("!DONE");
        return;
    }

    if (command.startsWith("!REC ")) {
        const String durationText = command.substring(5);
        const int durationMs = durationText.toInt();

        if (durationMs <= 0 || durationMs > MIC_MAX_RECORD_MS) {
            Serial.println("!ERROR");
            return;
        }

        const bool ok = streamMicrophoneAudio((uint32_t)durationMs);
        if (!ok) {
            Serial.println("!ERROR");
            return;
        }

        return;
    }

    if (command == "!STREAMON") {
        microphoneStreamingActive = true;
        Serial.println("!STREAMING");
        return;
    }

    if (command == "!STREAMOFF") {
        microphoneStreamingActive = false;
        Serial.println("!STOPPED");
        return;
    }

    if (command == "CLEAR") {
        statusMessageActive = false;
        heroModeActive = false;
        displayBlank = true;
        Serial.println("ACK:CLEAR");
        return;
    }

    if (command == "UNLOCK") {
        statusMessageActive = false;
        heroModeActive = false;
        displayLocked = false;
        displayBlank = false;
        lastChange = millis();
        Serial.println("ACK:UNLOCK");
        return;
    }

    command.toUpperCase();

    if (command == "OK") {
        soundSuccess();
        Serial.println("ACK:OK");
        return;
    }

    if (command == "ERR") {
        soundError();
        Serial.println("ACK:ERR");
        return;
    }

    if (command == "START") {
        soundStart();
        Serial.println("ACK:START");
        return;
    }

    if (command == "ROUND") {
        soundRound();
        Serial.println("ACK:ROUND");
        return;
    }

    if (command == "GAMEOVER") {
        soundGameOver();
        Serial.println("ACK:GAMEOVER");
        return;
    }

    if (command == "TEST") {
        soundStart();
        delay(120);
        soundSuccess();
        delay(120);
        soundError();
        Serial.println("ACK:TEST");
        return;
    }

    Serial.print("UNKNOWN:");
    Serial.println(command);
}

void readSerialCommands() {
    while (Serial.available()) {
        const char c = (char)Serial.read();

        if (c == '\n') {
            processCommand(serialLine);
            serialLine = "";
            return;
        }

        if (c != '\r') {
            serialLine += c;

            if (serialLine.length() > 64) {
                serialLine = "";
            }
        }
    }
}

void renderDisplay() {
    const unsigned long now = millis();

    if (displayBlank) {
        displayManager.clear();
        displayManager.render();
        return;
    }

    if (statusMessageActive) {
        renderStatusMessage();
        return;
    }

    if (heroModeActive) {
        renderHeroCard();
        return;
    }

    if (startupAnimationActive) {
        const unsigned long elapsed = now - startupAnimationStart;
        const unsigned long clampedElapsed = min(elapsed, ANIMATION_DURATION_MS);
        const float progress = (float)clampedElapsed / (float)ANIMATION_DURATION_MS;
        const int logoX =
            ANIMATION_LOGO_START_X +
            (int)((ANIMATION_LOGO_END_X - ANIMATION_LOGO_START_X) * progress);

        displayManager.clear();
        displayManager.drawBitmap(
            logoX,
            ANIMATION_LOGO_Y,
            startup_logo_bitmap,
            STARTUP_LOGO_WIDTH,
            STARTUP_LOGO_HEIGHT
        );
        displayManager.render();

        if (elapsed >= ANIMATION_DURATION_MS) {
            startupAnimationActive = false;
            lastChange = now;
        }
        return;
    }

    if (!displayLocked && now - lastChange >= changeInterval) {
        pokemonIndex++;

        if (pokemonIndex >= 151) {
            pokemonIndex = 0;
        }

        lastChange = now;
    }

    displayManager.clear();
    SpriteRenderer::drawPokemon(pokemonIndex, 0, 4);
    displayManager.drawPokemonInfo(pokemonIndex);
    displayManager.render();
}

void setup() {
    Serial.begin(SERIAL_BAUDRATE);
    delay(1000);

    displayManager.init();
    initSpeaker();
    initMicrophone();
    startupAnimationStart = millis();

    Serial.println("ESP32-S3 Speaker+Mic listo");
    Serial.println("Comandos: START, ROUND, OK, ERR, GAMEOVER, TEST, SHOW, HERO, TEXT, CLEAR, UNLOCK, !LOAD, !PLAYBUF, !REC <ms>, !STREAMON, !STREAMOFF");

    soundStart();
}

void loop() {
    readSerialCommands();
    if (microphoneStreamingActive) {
        if (!streamMicrophoneChunk()) {
            microphoneStreamingActive = false;
            Serial.println("!ERROR");
        }
    }
    renderDisplay();
}
