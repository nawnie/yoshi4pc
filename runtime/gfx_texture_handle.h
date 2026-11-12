/* Resolve Ryujinx's packed texture reflection against caller-supplied constant-buffer words.
 * PackSlots/PackOffsets and ReadPackedId semantics: Ryujinx.Graphics.Shader/TextureHandle.cs (MIT).
 * A false result means the handle cannot safely be resolved, rather than silently reading a different binding.
 */
#ifndef GFX_TEXTURE_HANDLE_H
#define GFX_TEXTURE_HANDLE_H
#include <stdint.h>

typedef int (*GfxHandleReadWord)(void *context, unsigned cbuf, unsigned word, uint32_t *value);

static inline int gfx_texture_handle_read(int32_t slots, uint32_t packed, GfxHandleReadWord read_word,
                                          void *context, uint32_t *out) {
    if (slots < 0 || !read_word || !out) return 0;
    unsigned texture_slot = (unsigned)slots & 0xffffu;
    unsigned encoded_sampler_slot = (uint32_t)slots >> 16;
    unsigned sampler_slot = encoded_sampler_slot ? encoded_sampler_slot - 1 : texture_slot;
    unsigned texture_offset = packed & 0x3fffu;
    unsigned sampler_offset = (packed >> 14) & 0x3fffu;
    unsigned kind = packed >> 28;
    uint32_t texture, sampler = 0;
    if (kind > 3 || !read_word(context, texture_slot, texture_offset, &texture)) return 0;
    if (kind == 1 || kind == 2) {
        if (!read_word(context, sampler_slot, sampler_offset, &sampler)) return 0;
    } else if (kind == 3) sampler = sampler_offset;
    if (kind == 2 || kind == 3) sampler <<= 20;
    *out = texture | sampler;
    return 1;
}
#endif
