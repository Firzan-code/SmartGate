#pragma once
#include "FreeRTOS.h"
struct FakeQueue { size_t limit, bytes; std::deque<std::vector<uint8_t>> data; };
using QueueHandle_t = FakeQueue *;
namespace fake { inline void (*afterDequeue)() = nullptr; }
inline QueueHandle_t xQueueCreate(size_t n, size_t bytes) { ++fake::queueCalls; return fake::ok() ? new FakeQueue{n, bytes, {}} : nullptr; }
inline BaseType_t xQueueSend(QueueHandle_t q, const void *p, TickType_t wait) {
 if (!q || wait || q->data.size() >= q->limit) return pdFALSE;
 const auto *v = static_cast<const uint8_t *>(p); q->data.emplace_back(v, v + q->bytes); return pdTRUE;
}
inline BaseType_t xQueueReceive(QueueHandle_t q, void *p, TickType_t wait) {
 if (!q || wait || q->data.empty()) return pdFALSE;
 std::memcpy(p, q->data.front().data(), q->bytes); q->data.pop_front();
 if (fake::afterDequeue) { auto hook=fake::afterDequeue; fake::afterDequeue=nullptr; hook(); }
 return pdTRUE;
}
inline BaseType_t xQueueReset(QueueHandle_t q) { if (!q) return pdFALSE; q->data.clear(); return pdPASS; }
inline void vQueueDelete(QueueHandle_t q) { delete q; }
