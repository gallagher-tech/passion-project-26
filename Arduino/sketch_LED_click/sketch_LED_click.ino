const int BUTTON_PIN = 2;
 
int lastButtonState = LOW; // remembers what we printed last time
 
void setup() {
  Serial.begin(9600);
  pinMode(BUTTON_PIN, INPUT); // switch: D2 -> one leg of switch -> other leg to 5V,
                               // plus a 10k resistor from D2 to GND (external pull-down)
}
 
void loop() {
  int buttonState = digitalRead(BUTTON_PIN);
 
  // only print when it just changed from not-pressed to pressed
  if (buttonState == HIGH && lastButtonState == LOW) {
    Serial.println("click");
  }
 
  lastButtonState = buttonState;
}