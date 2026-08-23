/*
 * Videoportero accesible - firmware ESP32-S3 (OPCIONAL)
 *
 * Solo necesario si se quiere un dispositivo físico. La demo funciona
 * íntegramente con el portátil sin este firmware.
 *
 * El ESP32 NO toma ninguna decisión: captura audio, lo transmite, reproduce lo
 * que le llega y acciona el relé cuando el servidor se lo ordena.
 *
 * Librerías (Arduino IDE / PlatformIO):
 *   - Arduino core ESP32 3.x  (aporta ESP_I2S.h)
 *   - ArduinoWebsockets (gilmaimon)
 *
 * Hardware:
 *   INMP441 (I2S in):    SCK=GPIO4  WS=GPIO5   SD=GPIO6   L/R a GND
 *   MAX98357A (I2S out): BCLK=GPIO15 LRC=GPIO16 DIN=GPIO7
 *   Pulsador de llamada: GPIO10 a GND (pull-up interno)
 *   Relé (abrepuertas):  GPIO11
 */

#include <WiFi.h>
#include <ESP_I2S.h>
#include <ArduinoWebsockets.h>

// ---------------------------------------------------------------- configuración
static const char *WIFI_SSID = "TU_RED";
static const char *WIFI_PASS = "TU_CONTRASENA";
static const char *WS_URL = "ws://192.168.1.50:8080/portero";

static const int PIN_MIC_SCK = 4;
static const int PIN_MIC_WS = 5;
static const int PIN_MIC_SD = 6;

static const int PIN_SPK_BCLK = 15;
static const int PIN_SPK_LRC = 16;
static const int PIN_SPK_DIN = 7;

static const int PIN_BUTTON = 10;
static const int PIN_RELAY = 11;

static const uint32_t SAMPLE_RATE = 16000;
static const size_t MIC_CHUNK_SAMPLES = 320;      // 20 ms
static const size_t PLAYBACK_BUFFER = 64 * 1024;  // ~2 s de margen contra el jitter
static const uint32_t RELAY_PULSE_MS = 1500;
static const uint32_t DEBOUNCE_MS = 250;

// ---------------------------------------------------------------- estado global
using namespace websockets;

I2SClass i2sMic;
I2SClass i2sSpk;
WebsocketsClient ws;

static volatile bool sessionActive = false;
static volatile bool micEnabled = false;  // silenciado mientras el asistente habla
static StreamBufferHandle_t playbackBuffer = nullptr;
static uint32_t relayOffAt = 0;
static uint32_t lastButtonMs = 0;

// ---------------------------------------------------------------- audio

void micTask(void *param) {
  int16_t samples[MIC_CHUNK_SAMPLES];

  for (;;) {
    if (!sessionActive || !micEnabled) {
      vTaskDelay(pdMS_TO_TICKS(20));
      continue;
    }

    size_t bytesRead = i2sMic.readBytes(reinterpret_cast<char *>(samples), sizeof(samples));
    if (bytesRead > 0 && sessionActive) {
      ws.sendBinary(reinterpret_cast<const char *>(samples), bytesRead);
    }
  }
}

void speakerTask(void *param) {
  uint8_t chunk[1024];

  for (;;) {
    size_t received = xStreamBufferReceive(playbackBuffer, chunk, sizeof(chunk), pdMS_TO_TICKS(50));
    if (received > 0) {
      i2sSpk.write(chunk, received);
    }
  }
}

// ---------------------------------------------------------------- WebSocket

void handleControl(const String &text) {
  if (text.indexOf("\"speaking\"") >= 0) {
    micEnabled = false;
    return;
  }
  if (text.indexOf("\"listening\"") >= 0) {
    // Vaciamos lo que quede del micrófono para no enviar nuestro propio audio.
    micEnabled = true;
    return;
  }
  if (text.indexOf("open_door") >= 0) {
    digitalWrite(PIN_RELAY, HIGH);
    relayOffAt = millis() + RELAY_PULSE_MS;
    Serial.println("Rele activado");
    return;
  }
  if (text.indexOf("bye") >= 0) {
    Serial.println("El servidor ha cerrado la conversacion");
    sessionActive = false;
  }
}

void onMessage(WebsocketsMessage message) {
  if (message.isBinary()) {
    xStreamBufferSend(playbackBuffer,
                      message.c_str(),
                      message.length(),
                      pdMS_TO_TICKS(200));
  } else {
    handleControl(message.data());
  }
}

void onEvent(WebsocketsEvent event, String data) {
  if (event == WebsocketsEvent::ConnectionClosed) {
    Serial.println("WebSocket cerrado");
    sessionActive = false;
    micEnabled = false;
  }
}

void startSession() {
  if (sessionActive) {
    return;
  }

  Serial.println("Abriendo sesion...");
  xStreamBufferReset(playbackBuffer);

  if (!ws.connect(WS_URL)) {
    Serial.println("No se ha podido conectar con el servidor");
    return;
  }

  sessionActive = true;
  micEnabled = true;
}

// ---------------------------------------------------------------- ciclo de vida

void setup() {
  Serial.begin(115200);

  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_RELAY, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);

  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.printf("\nWiFi: %s\n", WiFi.localIP().toString().c_str());

  i2sMic.setPins(PIN_MIC_SCK, PIN_MIC_WS, -1, PIN_MIC_SD);
  if (!i2sMic.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("Error inicializando el microfono I2S");
    while (true) delay(1000);
  }

  i2sSpk.setPins(PIN_SPK_BCLK, PIN_SPK_LRC, PIN_SPK_DIN);
  if (!i2sSpk.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("Error inicializando el altavoz I2S");
    while (true) delay(1000);
  }

  playbackBuffer = xStreamBufferCreate(PLAYBACK_BUFFER, 1);

  ws.onMessage(onMessage);
  ws.onEvent(onEvent);

  xTaskCreatePinnedToCore(micTask, "mic", 4096, nullptr, 5, nullptr, 1);
  xTaskCreatePinnedToCore(speakerTask, "spk", 4096, nullptr, 5, nullptr, 1);

  Serial.println("Listo. Pulsa el boton para iniciar la conversacion.");
}

void loop() {
  ws.poll();

  if (relayOffAt != 0 && millis() > relayOffAt) {
    digitalWrite(PIN_RELAY, LOW);
    relayOffAt = 0;
  }

  if (digitalRead(PIN_BUTTON) == LOW && millis() - lastButtonMs > DEBOUNCE_MS) {
    lastButtonMs = millis();
    if (sessionActive) {
      ws.send("{\"type\":\"hangup\"}");
      sessionActive = false;
      ws.close();
    } else {
      startSession();
    }
  }

  delay(5);
}