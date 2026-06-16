/* =====================================================================
   Thermal Management of a Battery-Powered Medical Payload Pod
   MEP 311s/212s - Heat Transfer Term Project (Spring 2026)

   Team   : __________________________________   (fill in)
   Module : 3-module thermal control system (Power / Control / Plant)
   Date   : __________

   One Arduino Uno reads THREE temperature sensors (one per module),
   modulates a single resistive heating plant (2x 8 ohm || = 4 ohm,
   driven by an IRF530 N-MOSFET via PWM), monitors battery voltage and
   estimated current/power, and drives one indicator LED.

   Control is driven by the PLANT sensor in four temperature bands
   (Power & Control sensors are read/logged only — not expected to rise):
     plant < 30 C   : heater 100%, LED off,        fan off
     30..35 C       : heater 100%, LED steady on,  fan off
     35..40 C       : heater 50%,  LED slow blink, fan on
     plant >= 40 C  : heater off,  LED fast blink, fan on  (hard cut-off)
   Safety overrides: battery under-voltage -> heater off, LED slow blink;
   plant sensor fault -> heater off, LED fast blink.
   ===================================================================== */

#include <DHT.h>

// ---------------- Pin map ----------------
#define DHT_PLANT_PIN   2      // Plant module (cargo bay, on the resistors)
#define DHT_POWER_PIN   3      // Power module (battery enclosure)
#define DHT_CONTROL_PIN 4      // Control module (Arduino enclosure)
#define DHTTYPE         DHT11

#define HEATER_PIN  9          // PWM -> IRF530 MOSFET gate (heating plant)
#define FAN_PIN     10         // forced-convection fan (thermal management)
#define LED_PIN     13         // indicator LED
#define BATTERY_PIN A1         // battery voltage via 10k/10k divider

// ============================================================
//  TEST OVERRIDES  —  force an actuator regardless of the bands.
//  Leave all four false for normal band control. Set one per actuator
//  for a characterization run. If a *_ON and *_OFF are both true, OFF wins.
//  Safety cut-offs (>=40 C over-temp, low battery, sensor fault) ALWAYS
//  stay active, even in test mode.
//
//    Cooling-only run     -> HEATER_ALWAYS_OFF = true
//    Full-power heat test -> HEATER_ALWAYS_ON  = true
//    "with fan" run       -> FAN_ALWAYS_ON     = true
//    "without fan" run    -> FAN_ALWAYS_OFF    = true
// ============================================================
#define HEATER_ALWAYS_ON   false   // force heater to 100%
#define HEATER_ALWAYS_OFF  true   // force heater OFF
#define FAN_ALWAYS_ON      true   // force fan ON
#define FAN_ALWAYS_OFF     false   // force fan OFF

// ---------------- Plant temperature bands (all configurable) ----------------
//   plant <  T_LOW           ->  heater 100%, LED off,        fan off
//   T_LOW <= plant < T_MID   ->  heater 100%, LED steady on,  fan off
//   T_MID <= plant < T_HIGH  ->  heater 50%,  LED slow blink, fan on
//   plant >= T_HIGH          ->  heater off,  LED fast blink, fan on  (over-temp)
#define T_LOW    30.0          // C
#define T_MID    35.0          // C
#define T_HIGH   40.0          // C (hard over-temperature cut-off)

#define HEAT_FULL  255         // PWM for 100% heat
#define HEAT_HALF  128         // PWM for 50% heat
#define HEAT_OFF     0         // PWM for heater off

#define BLINK_SLOW 400         // ms, LED slow blink (T_MID..T_HIGH band)
#define BLINK_FAST 100         // ms, LED fast blink (>= T_HIGH, over-temp)

#define BATTERY_MIN  5.0       // V: under-voltage cut-off (heater off, LED slow blink) — spec floor
#define R_LOAD       4.0       // ohm: 2x 8 ohm resistors in parallel (for power/current estimate)
#define VDIV_GAIN    2.0       // 10k/10k battery-sense divider

#define READ_INTERVAL 1000     // ms between sensor reads / serial prints

DHT dhtPlant(DHT_PLANT_PIN, DHTTYPE);
DHT dhtPower(DHT_POWER_PIN, DHTTYPE);
DHT dhtControl(DHT_CONTROL_PIN, DHTTYPE);

unsigned long previousReadMillis  = 0;
unsigned long previousBlinkMillis = 0;
bool ledState = false;

// LED pattern set by updateControl(), consumed by the fast LED loop:
// 0 = OFF, 1 = STEADY on, 2 = SLOW blink, 3 = FAST blink.
int ledPattern = 1;

void setup()
{
  Serial.begin(9600);

  pinMode(HEATER_PIN, OUTPUT);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);

  digitalWrite(FAN_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
  analogWrite(HEATER_PIN, 0);

  dhtPlant.begin();
  dhtPower.begin();
  dhtControl.begin();

  Serial.println("================================");
  Serial.println("Payload-Pod Thermal Control Started");
  Serial.print("Heater test: ");
  Serial.println(HEATER_ALWAYS_ON ? "FORCE ON" : HEATER_ALWAYS_OFF ? "FORCE OFF" : "band");
  Serial.print("Fan test: ");
  Serial.println(FAN_ALWAYS_ON ? "FORCE ON" : FAN_ALWAYS_OFF ? "FORCE OFF" : "band");
  Serial.print("Bands (C): ");   Serial.print(T_LOW); Serial.print(" / ");
  Serial.print(T_MID); Serial.print(" / "); Serial.println(T_HIGH);
  Serial.println("================================");
}

void updateControl()
{
  // ---- read the three module sensors (raw, so a fault shows clearly) ----
  float tPlant   = dhtPlant.readTemperature();
  float tPower   = dhtPower.readTemperature();
  float tControl = dhtControl.readTemperature();
  bool plantOK   = !isnan(tPlant);
  bool powerOK   = !isnan(tPower);
  bool controlOK = !isnan(tControl);

  // controlling max over the VALID sensors only
  float tMax = -100.0;
  if (plantOK   && tPlant   > tMax) tMax = tPlant;
  if (powerOK   && tPower   > tMax) tMax = tPower;
  if (controlOK && tControl > tMax) tMax = tControl;

  // ---- battery voltage ----
  int rawBattery = analogRead(BATTERY_PIN);
  float batteryVoltage = rawBattery * (5.0 / 1023.0) * VDIV_GAIN;

  // ---- PLANT temperature bands -> heater / fan / LED ----
  int heaterPWM; bool fanOn; int ledPat; const char *mode;
  if (tPlant < T_LOW)        { heaterPWM = HEAT_FULL; fanOn = false; ledPat = 0; mode = "Heat 100% (<30C)"; }
  else if (tPlant < T_MID)   { heaterPWM = HEAT_FULL; fanOn = false; ledPat = 1; mode = "Heat 100% (30-35C)"; }
  else if (tPlant < T_HIGH)  { heaterPWM = HEAT_HALF; fanOn = true;  ledPat = 2; mode = "Heat 50% (35-40C)"; }
  else                       { heaterPWM = HEAT_OFF;  fanOn = true;  ledPat = 3; mode = "Overtemp off (>=40C)"; }

  // ---- test overrides: force an actuator regardless of the bands ----
  if (HEATER_ALWAYS_ON)  { heaterPWM = HEAT_FULL; mode = "TEST heater ON"; }
  if (HEATER_ALWAYS_OFF) { heaterPWM = HEAT_OFF;  mode = "TEST heater OFF"; }
  if (FAN_ALWAYS_ON)     fanOn = true;
  if (FAN_ALWAYS_OFF)    fanOn = false;

  // ---- safety overrides (ALWAYS win, even over the test overrides) ----
  if (plantOK && tPlant >= T_HIGH) {         // hard over-temperature cut-off
    heaterPWM = HEAT_OFF; mode = "OVERTEMP CUTOFF";
  }
  if (batteryVoltage < BATTERY_MIN) {        // under-voltage protection (spec)
    heaterPWM = HEAT_OFF; fanOn = false; ledPat = 2; mode = "LOW BATTERY";
  }
  if (!plantOK) {                            // no plant feedback -> stay safe
    heaterPWM = HEAT_OFF; fanOn = false; ledPat = 3; mode = "PLANT SENSOR FAULT";
  }

  analogWrite(HEATER_PIN, heaterPWM);
  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  ledPattern = ledPat;

  // ---- estimated current & power in the resistors (PWM-averaged) ----
  float duty = heaterPWM / 255.0;
  float current = duty * batteryVoltage / R_LOAD;     // A
  float power   = duty * batteryVoltage * batteryVoltage / R_LOAD;  // W

  const char *ledMode = (ledPat == 0) ? "OFF" : (ledPat == 1) ? "STEADY"
                       : (ledPat == 2) ? "SLOW" : "FAST";

  // =====================================
  // SERIAL OUTPUT  (parsed by the Python logger)
  // =====================================
  Serial.println("================================");
  Serial.print("Temp Plant = ");   Serial.print(tPlant);   Serial.println(" C");
  Serial.print("Temp Power = ");   Serial.print(tPower);   Serial.println(" C");
  Serial.print("Temp Control = "); Serial.print(tControl); Serial.println(" C");
  Serial.print("Temp Max = ");     Serial.print(tMax);     Serial.println(" C");
  Serial.print("Sensors = ");
  Serial.print(plantOK   ? "P-ok "  : "P-ERR ");
  Serial.print(powerOK   ? "W-ok "  : "W-ERR ");
  Serial.println(controlOK ? "C-ok" : "C-ERR");
  Serial.print("Battery Voltage = "); Serial.print(batteryVoltage); Serial.println(" V");
  Serial.print("Heater PWM = ");   Serial.println(heaterPWM);
  Serial.print("Duty = ");         Serial.print(duty * 100.0, 1); Serial.println(" %");
  Serial.print("Current = ");      Serial.print(current, 2); Serial.println(" A");
  Serial.print("Power = ");        Serial.print(power, 2);   Serial.println(" W");
  Serial.print("Fan = ");          Serial.println(fanOn ? "ON" : "OFF");
  Serial.print("LED = ");          Serial.println(ledMode);
  Serial.print("Mode: ");          Serial.println(mode);
  Serial.println("================================");
  Serial.println();
}

// Runs every loop iteration so blink rates are actually honored.
// ledPattern: 0 = OFF, 1 = STEADY on, 2 = SLOW blink, 3 = FAST blink.
void updateLED()
{
  unsigned long now = millis();
  if (ledPattern == 0) { digitalWrite(LED_PIN, LOW);  ledState = false; return; }
  if (ledPattern == 1) { digitalWrite(LED_PIN, HIGH); ledState = true;  return; }
  unsigned long period = (ledPattern == 3) ? BLINK_FAST : BLINK_SLOW;
  if (now - previousBlinkMillis >= period) {
    previousBlinkMillis = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }
}

void loop()
{
  unsigned long now = millis();

  if (now - previousReadMillis >= READ_INTERVAL) {
    previousReadMillis = now;
    updateControl();
  }

  updateLED();
}
