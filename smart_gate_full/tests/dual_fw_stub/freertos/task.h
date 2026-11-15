#pragma once
#include "FreeRTOS.h"
using TaskHandle_t = void *;
namespace fake {
inline uintptr_t currentTask = 1;  // Arduino loopTask
inline constexpr uintptr_t acquisitionTaskId = 2;  // same core, different task
inline void (*taskEntry)(void *) = nullptr;
inline void *taskArgument = nullptr;
inline bool taskSlice = false;
struct TaskYield {};
inline void runTaskSlice() {
 if (!taskEntry) return;
 const uintptr_t previous = currentTask;
 currentTask = acquisitionTaskId; taskSlice = true;
 try { taskEntry(taskArgument); }
 catch (const TaskYield &) {}
 catch (...) { currentTask = previous; taskSlice = false; throw; }
 currentTask = previous; taskSlice = false;
}
}
inline TaskHandle_t xTaskGetCurrentTaskHandle() { return reinterpret_cast<void *>(fake::currentTask); }
inline BaseType_t xTaskCreatePinnedToCore(void (*entry)(void *), const char *, uint32_t, void *argument, unsigned, TaskHandle_t *out, int) {
 ++fake::taskCalls;
 if (!fake::ok()) return pdFALSE;
 fake::taskEntry = entry; fake::taskArgument = argument;
 *out = reinterpret_cast<void *>(fake::acquisitionTaskId); return pdPASS;
}
inline void vTaskDelay(TickType_t ms) {
 fake::now += ms;
 if (fake::taskSlice) throw fake::TaskYield{};
}
inline void vTaskDelete(TaskHandle_t) {}
