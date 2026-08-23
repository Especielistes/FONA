/*
 * Arduino Mega 2560 - pulsador de llamada y relé de apertura.
 *
 * El Mega NO toca el audio: solo informa de la pulsación del botón y acciona el
 * relé cuando el PC se lo ordena. El audio va por el micrófono y los altavoces
 * del PC.
 *
 * Protocolo por USB serie a 115200 baudios:
 *   Mega -> PC : "B\n"   botón pulsado
 *   PC  -> Mega: "O\n"   abrir la puerta (pulso de 1,5 s)
 */

static const int PIN_BUTTON = 2;
static const int PIN_RELAY = 3;
static const int PIN_LED = 13;

static const unsigned long RELAY_PULSE_MS = 1500;
static const unsigned long DEBOUNCE_MS = 250;

unsigned long relayOffAt = 0;
unsigned long lastPressMs = 0;
int lastButtonState = HIGH;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_RELAY, LOW);
}

void loop() {
  // --- botón ---
  int state = digitalRead(PIN_BUTTON);
  if (state == LOW && lastButtonState == HIGH && millis() - lastPressMs > DEBOUNCE_MS) {
    lastPressMs = millis();
    Serial.println("B");
  }
  lastButtonState = state;

  // --- órdenes del PC ---
  if (Serial.available() > 0) {
    char command = Serial.read();
    if (command == 'O') {
      digitalWrite(PIN_RELAY, HIGH);
      digitalWrite(PIN_LED, HIGH);
      relayOffAt = millis() + RELAY_PULSE_MS;
    }
  }

  // --- fin del pulso ---
  if (relayOffAt != 0 && millis() > relayOffAt) {
    digitalWrite(PIN_RELAY, LOW);
    digitalWrite(PIN_LED, LOW);
    relayOffAt = 0;
  }
}