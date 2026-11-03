/* Existing GPIO command protocol, batched in native code; no FPGA changes.
 * regs points to PYNQ's existing mmap. ARM device-memory accesses are volatile
 * and ordered with a full barrier around command publication. */
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stddef.h>
#include <time.h>

static double now_seconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int lcd_pack_rgb565(const uint8_t *rgb, size_t pixels, uint8_t *output) {
    if (!rgb || !output || pixels > 320u*320u) return -1;
    for (size_t i = 0; i < pixels; ++i) {
        uint16_t value = ((uint16_t)(rgb[3*i] >> 3) << 11) |
                         ((uint16_t)(rgb[3*i+1] >> 2) << 5) |
                         (rgb[3*i+2] >> 3);
        output[2*i] = value >> 8;
        output[2*i+1] = value & 255;
    }
    return (int)(pixels*2);
}

/* Return completed byte count; -1 before any write, -2 on partial failure.
 * Never retry partial writes: LCD state must be explicitly re-established. */
int lcd_data_write(volatile uint32_t *regs, const uint8_t *data,
                   size_t length, double timeout, uint32_t *toggle) {
    if (!regs || !data || !toggle || length > 4096 || timeout <= 0)
        return -1;
    uint32_t state = regs[2];
    if ((state >> 16) != 0x5a32 || (state & 1) != (*toggle & 1))
        return -1;
    double deadline = now_seconds() + timeout;
    const int triple = (state & 0x1000) != 0;
    for (size_t i = 0; i < length;) {
        size_t count = triple && length-i >= 3 ? 3 : 1;
        uint32_t payload = count == 3 ?
            ((uint32_t)data[i] << 16) | ((uint32_t)data[i+1] << 8) | data[i+2] : data[i];
        unsigned polls = 0;
        while (regs[2] & 2) {
            if ((++polls & 1023) == 0 && now_seconds() >= deadline)
                return i ? -2 : -1;
        }
        *toggle ^= 1;
        __sync_synchronize();
        regs[0] = (*toggle << 31) | ((count == 3 ? 4u : 2u) << 24) | payload;
        __sync_synchronize();
        polls = 0;
        do {
            state = regs[2];
            if ((++polls & 1023) == 0 && now_seconds() >= deadline)
                return -2;
        } while ((state & 3) != *toggle);
        i += count;
        if ((i & 255) == 255 && now_seconds() >= deadline)
            return -2;
    }
    return (int)length;
}
