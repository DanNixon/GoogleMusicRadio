/*
  Google Pay Music Radio Arduino script
  Dan Nixon 2013
  dan-nixon.com
  
  11/04/2013
*/

#include <Encoder.h>
#include <LiquidCrystal.h>
#include <CmdMessenger.h>
#include <Streaming.h>

#define PORT_SPEED 115200

char field_separator = '%';
char command_separator = '~';

const int ADC_TH = 100;
const int DB_TIME = 20;

const int LCD_ROWS = 4;
const int LCD_COLS = 20;

//LCD PINS
#define LCD_D4 11
#define LCD_D5 10
#define LCD_D6 9
#define LCD_D7 8
#define LCD_RS 13
#define LCD_EN 12

//ENCODERS
#define VOL_ENC_A 3
#define VOL_ENC_B 5
#define CUR_ENC_A 2
#define CUR_ENC_B 4
long volEncPos = -999;
long curEncPos = -999;
static const int VOL_ENCODER_DELTA = 1;
static const int CUR_ENCODER_DELTA = 1;

//ENCODER BUTTONS
#define SELECT_PIN 6
boolean selLast = false;
#define MUTE_PIN 7
boolean muteLast = false;

//ADC BUTTONS
#define STOP_ADC 0
boolean stopLast = false;
#define PLAY_ADC 1
boolean playLast = false;
#define NEXT_ADC 2
boolean nextLast = false;
#define LOVE_ADC 4
boolean loveLast = false;
#define DISP_ADC 3
boolean dispLast = false;
#define BACK_ADC 5
boolean backLast = false;

Encoder volumeEnc(VOL_ENC_A, VOL_ENC_B);
Encoder cursorEnc(CUR_ENC_A, CUR_ENC_B);
CmdMessenger msgr = CmdMessenger(Serial, field_separator, command_separator);
LiquidCrystal lcd(LCD_RS, LCD_EN, LCD_D4, LCD_D5, LCD_D6, LCD_D7);

//COMMAND LIST
enum
{
  kCOMM_ERROR    = 000,
  kACK           = 001,
  kARDUINO_READY = 002,
  kERR           = 003,
  kNEXT          = 012, //10
  kSTOP          = 013,
  kPLAY          = 014,
  kBACK          = 015,
  kINCVOL        = 016,
  kDECVOL        = 017,
  kUP            = 020,
  kDOWN          = 021,
  kSEL           = 022,
  kDISP          = 023,
  kLOVE          = 024, //20
  kMUTE          = 025,
  kSEND_CMDS_END,
};

messengerCallbackFunction messengerCallbacks[] = 
{
  lcdPrint,
  lcdVolume,
  lcdClear,
  NULL
};

//CALLBACKS
void lcdPrint() {
  msgr.sendCmd(kACK, "LCD_P");
  int rowNo = msgr.readInt();
  char row[LCD_COLS + 1] = {};
  msgr.copyString(row, (LCD_COLS + 1));
  lcd.setCursor(0, rowNo);
  lcd.print(row);
}

void lcdClear() {
  msgr.sendCmd(kACK, "LCD_C");
  lcd.clear();
}

void lcdVolume() {
  msgr.sendCmd(kACK, "VOL_P");
  int volume = msgr.readInt();
  float barRange = LCD_COLS - 2;
  float barWeight = 64.0 / barRange;
  int barQuant = (int) (volume / barWeight);
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Volume: ");
  lcd.setCursor(8, 0);
  lcd.print(volume);
  lcd.setCursor(0, 1);
  lcd.print("[");
  lcd.setCursor((LCD_COLS - 1), 1);
  lcd.print("]");
  lcd.setCursor(1, 1);
  for(int i = 0; i < barQuant; i++) {
    lcd.write(255);
  }
}

//DEFAULT CALLBACKS
void arduino_ready() {
  msgr.sendCmd(kACK,"READY");
}

void unknownCmd() {
  msgr.sendCmd(kERR,"U_CMD");
}

//SETUP

void attach_callbacks(messengerCallbackFunction* callbacks) {
  int i = 0;
  int offset = kSEND_CMDS_END;
  while(callbacks[i]) {
    msgr.attach(offset+i, callbacks[i]);
    i++;
  }
}

void setup() {
  Serial.begin(PORT_SPEED);
  msgr.print_LF_CR();
  msgr.attach(kARDUINO_READY, arduino_ready);
  msgr.attach(unknownCmd);
  attach_callbacks(messengerCallbacks);
  lcd.begin(LCD_COLS, LCD_ROWS);
  //PIN CONFS
  pinMode(SELECT_PIN, INPUT);
  digitalWrite(SELECT_PIN, HIGH);
  pinMode(MUTE_PIN, INPUT);
  digitalWrite(MUTE_PIN, HIGH);
  long volEncPos = volumeEnc.read();
  long curEncPos = cursorEnc.read();
  arduino_ready();
  lcd.print("Waiting for Pi...");
}

//MAIN LOOP
void checkButtons() {
  if(analogRead(PLAY_ADC) <= ADC_TH) {
    if(playLast == false) {
      msgr.sendCmd(kPLAY, "PLAY");
      delay(DB_TIME);
      playLast = true;
    }
  } else {
    if(playLast == true) {
      playLast = false;
    }
  }
  
  if(analogRead(STOP_ADC) <= ADC_TH) {
    if(stopLast == false) {
      msgr.sendCmd(kSTOP, "STOP");
      delay(DB_TIME);
      stopLast = true;
    }
  } else {
    if(stopLast == true) {
      stopLast = false;
    }
  }
  
  if(analogRead(NEXT_ADC) <= ADC_TH) {
    if(nextLast == false) {
      msgr.sendCmd(kNEXT, "NEXT");
      delay(DB_TIME);
      nextLast = true;
    }
  } else {
    if(nextLast == true) {
      nextLast = false;
    }
  }
  
  if(analogRead(BACK_ADC) <= ADC_TH) {
    if(backLast == false) {
      msgr.sendCmd(kBACK, "BACK");
      delay(DB_TIME);
      backLast = true;
    }
  } else {
    if(backLast == true) {
      backLast = false;
    }
  }
  
  if(analogRead(DISP_ADC) <= ADC_TH) {
    if(dispLast == false) {
      msgr.sendCmd(kDISP, "DISP");
      delay(DB_TIME);
      dispLast = true;
    }
  } else {
    if(dispLast == true) {
      dispLast = false;
    }
  }
  
  if(analogRead(LOVE_ADC) <= ADC_TH) {
    if(loveLast == false) {
      msgr.sendCmd(kLOVE, "LOVE");
      delay(DB_TIME);
      loveLast = true;
    }
  } else {
    if(loveLast == true) {
      loveLast = false;
    }
  }
  if(digitalRead(SELECT_PIN) == LOW) {
    if(selLast == false) {
      msgr.sendCmd(kSEL, "SEL");
      delay(DB_TIME);
      selLast = true;
    }
  } else {
    if(selLast == true) {
      selLast = false;
    }
  }
  if(digitalRead(MUTE_PIN) == LOW) {
    if(muteLast == false) {
      msgr.sendCmd(kMUTE, "MUTE");
      delay(DB_TIME);
      selLast = true;
    }
  } else {
    if(muteLast == true) {
      muteLast = false;
    }
  }
}

void checkEncoders() {
  long newVolEncPos = volumeEnc.read();
  if(newVolEncPos > (volEncPos + VOL_ENCODER_DELTA)) {
    msgr.sendCmd(kDECVOL, "DECVOL");
    volEncPos += VOL_ENCODER_DELTA;
  }
  else if(newVolEncPos < (volEncPos - VOL_ENCODER_DELTA)) {
    msgr.sendCmd(kINCVOL, "INCVOL");
    volEncPos -= VOL_ENCODER_DELTA;
  }
  
  long newCurEncPos = cursorEnc.read();
  if(newCurEncPos > (curEncPos + CUR_ENCODER_DELTA)) {
    msgr.sendCmd(kUP, "UP");
    curEncPos += CUR_ENCODER_DELTA;
  }
  else if(newCurEncPos < (curEncPos - CUR_ENCODER_DELTA)) {
    msgr.sendCmd(kDOWN, "DOWN");
    curEncPos -= CUR_ENCODER_DELTA;
  }
}

void loop() 
{
  msgr.feedinSerialData();
  checkButtons();
  checkEncoders();
}
