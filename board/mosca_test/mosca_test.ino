/*
 * mosca_test.ino -- Bench test for the "Visible Reflex" project
 *
 * Goal: prove that EVERY component of the Eletrogate Kit Start works,
 * BEFORE involving any neuroscience. The brain comes later; here the goal
 * is hardware only.
 *
 * ---------------------------------------------------------------------------
 * WIRING (400-point breadboard)
 * ---------------------------------------------------------------------------
 *  SG90 micro servo
 *      brown  -> GND
 *      red    -> 5V   (preferably an external 5V supply; if powering from the Uno,
 *                      place a 100uF capacitor between 5V and GND)
 *      orange -> pin 9 (signal)
 *
 *  LEDs (330 ohm resistor in series) -- 3 "stages" of the reflex arc
 *      pin 5 -> RED LED    (sensory stage)
 *      pin 6 -> YELLOW LED (interneuron)
 *      pin 7 -> GREEN LED  (motor)
 *      Assembly: pin --[330R]-- anode(long leg) -- LED -- cathode(short leg) -- GND
 *
 *  Active buzzer 5V
 *      (+) -> pin 8      (-) -> GND
 *
 *  LDR Light Sensor (voltage divider)
 *      5V --- LDR --- A0 --- 10k --- GND
 *
 *  NTC Temperature Sensor (voltage divider)
 *      5V --- NTC --- A1 --- 10k --- GND
 *
 *  Potentiometer 10K
 *      ends -> 5V and GND ; wiper (middle pin) -> A2
 *
 *  Tactile switch (push-button)
 *      one side -> pin 2 ; other side -> GND   (uses INPUT_PULLUP)
 *
 * ---------------------------------------------------------------------------
 * SERIAL PROTOCOL -- 115200 baud
 * ---------------------------------------------------------------------------
 *  Arduino -> PC  (50 Hz):
 *      S <ldr> <ntc> <pot> <btn>        values 0..1023 and 0/1
 *
 *  PC -> Arduino:
 *      L <sensory> <inter> <motor> <angle>   0/1, 0/1, 0/1, 0..180
 *      B <freq>                              0 turns the buzzer off
 *      T                                     runs the self-test again
 */

#include <Servo.h>
#include <stdio.h>

const uint8_t PIN_SERVO     = 9;
const uint8_t PIN_LED_SENS  = 5;
const uint8_t PIN_LED_INTER = 6;
const uint8_t PIN_LED_MOTOR = 7;
const uint8_t PIN_BUZZER    = 8;
const uint8_t PIN_BUTTON    = 2;

const uint8_t PIN_LDR = A0;
const uint8_t PIN_NTC = A1;
const uint8_t PIN_POT = A2;

const unsigned long SEND_PERIOD_MS = 20;  // 50 Hz

Servo servo;
unsigned long lastSend = 0;

char    lineBuf[64];
uint8_t lineLen = 0;

void selfTest();
void handleIncoming();
void process(char *line);

void setup() {
  Serial.begin(115200);

  pinMode(PIN_LED_SENS,  OUTPUT);
  pinMode(PIN_LED_INTER, OUTPUT);
  pinMode(PIN_LED_MOTOR, OUTPUT);
  pinMode(PIN_BUZZER,    OUTPUT);
  pinMode(PIN_BUTTON,    INPUT_PULLUP);

  servo.attach(PIN_SERVO);
  servo.write(90);

  selfTest();

  Serial.println("# mosca_test ready -- S <ldr> <ntc> <pot> <btn>");
}

void loop() {
  handleIncoming();

  unsigned long now = millis();
  if (now - lastSend >= SEND_PERIOD_MS) {
    lastSend = now;
    Serial.print("S ");
    Serial.print(analogRead(PIN_LDR));
    Serial.print(' ');
    Serial.print(analogRead(PIN_NTC));
    Serial.print(' ');
    Serial.print(analogRead(PIN_POT));
    Serial.print(' ');
    Serial.println(digitalRead(PIN_BUTTON) == LOW ? 1 : 0);
  }
}

/* Lights everything in sequence to prove that each part responds. */
void selfTest() {
  // 1) servo sweeps end to end
  for (int a = 0; a <= 180; a += 10) { servo.write(a); delay(12); }
  for (int a = 180; a >= 0; a -= 10) { servo.write(a); delay(12); }
  servo.write(90);

  // 2) LEDs in sequence: sensory -> inter -> motor
  const uint8_t leds[3] = { PIN_LED_SENS, PIN_LED_INTER, PIN_LED_MOTOR };
  for (uint8_t i = 0; i < 3; i++) {
    digitalWrite(leds[i], HIGH);
    delay(150);
    digitalWrite(leds[i], LOW);
  }

  // 3) buzzer beeps
  tone(PIN_BUZZER, 880, 120);
  delay(200);
  noTone(PIN_BUZZER);
}

void handleIncoming() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        process(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      lineLen = 0;  // overflow: discard the line
    }
  }
}

void process(char *line) {
  if (line[0] == 'L' || line[0] == 'l') {
    int s = -1, i = -1, m = -1, ang = -1;
    if (sscanf(line, "%*c %d %d %d %d", &s, &i, &m, &ang) == 4) {
      digitalWrite(PIN_LED_SENS,  s ? HIGH : LOW);
      digitalWrite(PIN_LED_INTER, i ? HIGH : LOW);
      digitalWrite(PIN_LED_MOTOR, m ? HIGH : LOW);
      servo.write(constrain(ang, 0, 180));
    }
  } else if (line[0] == 'B' || line[0] == 'b') {
    int f = 0;
    if (sscanf(line, "%*c %d", &f) == 1) {
      if (f <= 0) noTone(PIN_BUZZER);
      else        tone(PIN_BUZZER, f);
    }
  } else if (line[0] == 'T' || line[0] == 't') {
    selfTest();
  }
}
