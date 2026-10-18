#pragma once

#include <stddef.h>

namespace carscps {

constexpr size_t RESPONSE_CAPACITY = 768;

template<class Sender>
bool sendOnce(
    const char* response,
    size_t length,
    Sender sender) {

  if (
      !response ||
      length == 0 ||
      length >= RESPONSE_CAPACITY
  ) {
    return false;
  }

  return sender(response, length) ==
      static_cast<int>(length);
}

}  // namespace carscps
