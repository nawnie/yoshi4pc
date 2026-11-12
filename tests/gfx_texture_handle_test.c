#include <stdint.h>
#include <stdio.h>
#include "../runtime/gfx_texture_handle.h"

static uint32_t banks[4][8];
static int get_word(void *unused, unsigned bank, unsigned word, uint32_t *out) {
    (void)unused;
    if (bank >= 4 || word >= 8) return 0;
    *out = banks[bank][word];
    return 1;
}
#define CHECK(expr) do { if (!(expr)) { fprintf(stderr,"failed at line %d: %s\n", __LINE__, #expr); return 1; } } while (0)
int main(void) {
    uint32_t value = 0;
    banks[3][0] = 0x12345;
    banks[3][4] = 0xABC00000;
    CHECK(gfx_texture_handle_read(0x00040003, 0x10010000, get_word, 0, &value));
    CHECK(value == 0xABC12345);
    banks[1][4] = 0x00500000;
    CHECK(gfx_texture_handle_read(0x00020003, 0x10010000, get_word, 0, &value));
    CHECK(value == 0x00512345);
    banks[3][4] = 0x234;
    CHECK(gfx_texture_handle_read(3, 0x20010000, get_word, 0, &value));
    CHECK(value == 0x23412345);
    CHECK(gfx_texture_handle_read(3, 0x30010000, get_word, 0, &value));
    CHECK(value == 0x00412345);
    CHECK(gfx_texture_handle_read(3, 0, get_word, 0, &value));
    CHECK(value == 0x12345);
    CHECK(!gfx_texture_handle_read(-1, 0, get_word, 0, &value));
    CHECK(!gfx_texture_handle_read(3, 0x40000000, get_word, 0, &value));
    CHECK(!gfx_texture_handle_read(3, 0x10024000, get_word, 0, &value));
    CHECK(!gfx_texture_handle_read(3, 0, get_word, 0, 0));
    puts("texture handle decoding checks passed");
    return 0;
}
