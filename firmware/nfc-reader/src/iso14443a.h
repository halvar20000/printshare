// ISO 14443A chip number (UID) with a PN5180 - NTAG stickers, MIFARE (Bambu spool tags). The registry version 1.5 of
// the PN5180 library only has ISO 15693, so this follows the standard anticollision: WUPA → ATQA, then per cascade
// level ANTICOLLISION (0x93/0x95/0x97 0x20, no CRC) → 4 bytes + BCC, SELECT (… 0x70 + those 5 bytes, with CRC) → SAK.
// A cascade tag 0x88 means "3 UID bytes here, more on the next level". The UID comes out UID0 first, like Android.
#pragma once
#include <PN5180.h>

#define PN5180_CRC_TX_CONFIG (0x19)

class PN5180TypeA : public PN5180 {
 public:
  PN5180TypeA(uint8_t nss, uint8_t busy, uint8_t rst) : PN5180(nss, busy, rst) {}

  bool setupRF() {
    if (!loadRFConfig(0x00, 0x80)) return false;   // ISO 14443A, 106 kbit/s
    delay(10);
    if (!setRF_on()) return false;
    delay(10);
    return true;
  }

  // the chip's UID into uid (max 10 bytes); returns its length, 0 = no chip
  uint8_t readUid(uint8_t *uid) {
    writeRegisterWithAndMask(SYSTEM_CONFIG, 0xFFFFFFBF);     // crypto off
    crc(false);
    clearIRQStatus(0x000FFFFF);
    uint8_t wupa = 0x52;                                     // wakes halted chips too
    if (!sendData(&wupa, 1, 0x07) || received(2) < 2) return 0;
    readData(2);                                             // ATQA
    uint8_t n = 0;
    const uint8_t levels[3] = {0x93, 0x95, 0x97};
    for (uint8_t level : levels) {
      crc(false);
      uint8_t ac[2] = {level, 0x20};
      if (!sendData(ac, 2, 0) || received(5) < 5) return 0;
      uint8_t sel[7] = {level, 0x70};
      memcpy(sel + 2, readData(5), 5);
      if ((sel[2] ^ sel[3] ^ sel[4] ^ sel[5]) != sel[6]) return 0;   // BCC wrong: two chips at once
      crc(true);
      if (!sendData(sel, 7, 0) || received(1) < 1) return 0;
      uint8_t sak = readData(1)[0];
      if (sel[2] == 0x88) {                                   // cascade tag: 3 bytes, continue
        memcpy(uid + n, sel + 3, 3);
        n += 3;
        if (!(sak & 0x04)) return 0;
      } else {
        memcpy(uid + n, sel + 2, 4);
        return n + 4;
      }
    }
    return 0;
  }

 private:
  void crc(bool on) {
    if (on) {
      writeRegisterWithOrMask(CRC_RX_CONFIG, 0x01);
      writeRegisterWithOrMask(PN5180_CRC_TX_CONFIG, 0x01);
    } else {
      writeRegisterWithAndMask(CRC_RX_CONFIG, 0xFFFFFFFE);
      writeRegisterWithAndMask(PN5180_CRC_TX_CONFIG, 0xFFFFFFFE);
    }
  }

  // wait up to 20 ms for an answer; number of bytes received
  uint16_t received(uint16_t want) {
    uint32_t st = 0;
    for (int i = 0; i < 20; i++) {
      delay(1);
      if (getIRQStatus() & RX_IRQ_STAT) break;
    }
    readRegister(RX_STATUS, &st);
    clearIRQStatus(RX_IRQ_STAT | TX_IRQ_STAT | IDLE_IRQ_STAT | RX_SOF_DET_IRQ_STAT);
    uint16_t n = st & 0x1FF;
    return n >= want ? n : 0;
  }
};
