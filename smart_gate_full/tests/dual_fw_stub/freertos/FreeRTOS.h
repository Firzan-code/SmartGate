#pragma once
#include "Arduino.h"
using TickType_t = uint32_t;
using BaseType_t = int;
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define pdTRUE 1
#define pdFALSE 0
#define pdPASS 1
#define pdMS_TO_TICKS(n) (n)
namespace fake { inline int enters = 0, jumpAtEnter = 0; }
inline void portENTER_CRITICAL(portMUX_TYPE *) { if (++fake::enters == fake::jumpAtEnter) fake::now += fake::jumpMs; }
inline void portEXIT_CRITICAL(portMUX_TYPE *) {}
inline void portENTER_CRITICAL_ISR(portMUX_TYPE *) {}
inline void portEXIT_CRITICAL_ISR(portMUX_TYPE *) {}
