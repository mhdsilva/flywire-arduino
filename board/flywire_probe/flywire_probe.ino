/*
 * flywire_probe.ino -- wiring diagnostic (temporary).
 *
 * Streams all six analog inputs so we can see which pin a sensor is on.
 * Format @115200:  P <a0> <a1> <a2> <a3> <a4> <a5>
 *
 * A floating pin reads noisy/mid-range; a pin connected to a real sensor
 * reads a different, more stable value. Run it, then compare the columns.
 */

void setup() {
  Serial.begin(115200);
  Serial.println("# probe ready -- P <a0> <a1> <a2> <a3> <a4> <a5>");
}

void loop() {
  Serial.print("P");
  for (uint8_t pin = A0; pin <= A5; pin++) {
    Serial.print(' ');
    Serial.print(analogRead(pin));
  }
  Serial.println();
  delay(20);
}
