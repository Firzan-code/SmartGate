#pragma once
#include "Arduino.h"
#define F_GETFL 1
#define F_SETFL 2
#define O_NONBLOCK 128
inline int fcntl(int, int cmd, int flags = 0) { if (!fake::ok()) return -1; if(cmd==F_SETFL) fake::nonblocking=(flags&O_NONBLOCK)!=0; return 0; }
