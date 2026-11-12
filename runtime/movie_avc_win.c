// H.264 (AVC) decoding for the host movie::Decoder, through Windows' built-in Media Foundation H.264 decoder.
//
// Why this exists: Yoshi's pre-rendered movies are H.264 (movie::Decoder type 1). On the console the movie library
// hands them to the hardware decoder, which the host runtime does not provide, so the library aborts (result
// 0x106c6f in InitializeDecoderByTransferMemory). ov_movie.c already replaces the decoder for VP9 with libvpx; this
// file gives it the same "compressed frame in, NV12 picture out" service for H.264.
//
// Why Media Foundation: the decoder ships with Windows, outputs NV12 (the format the game asks for) and needs no
// extra DLL next to the game. It decodes in software here (no Direct3D device is given to it).
//
// Shape of the service: movie_avc_send() queues one compressed access unit, movie_avc_receive() returns at most one
// decoded picture with ITS OWN timestamp. H.264 may hold pictures back to reorder them, so a picture can come out
// several inputs after the one that carried it; movie_avc_drain() tells the decoder no more input is coming.
#define COBJMACROS
#include <windows.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mftransform.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "host.h"
#include "movie_avc.h"

// The H.264 decoder's class id, {62CE7E72-4C71-4D20-B15D-452831A87D9D} (wmcodecdsp.h: CLSID_CMSH264DecoderMFT).
static const GUID k_h264_decoder = {0x62ce7e72, 0x4c71, 0x4d20, {0xb1, 0x5d, 0x45, 0x28, 0x31, 0xa8, 0x7d, 0x9d}};

struct MovieAvc {
    IMFTransform *decoder;
    int width, height;          // the picture the game was told about
    int coded_height, stride;   // the decoder's own buffer layout (rows are padded to a multiple of 16)
    int own_samples;            // the decoder brings its own output samples (else we supply the buffer)
    DWORD out_bytes;            // size of an output buffer we supply
    uint8_t *scratch;           // input converted to start-code form
    int scratch_cap;
    int inputs_logged;
};

// COM has to be initialised on every thread that touches the decoder: the movie worker thread and the guest threads
// that configure, flush and destroy it. Joining the multithreaded apartment twice is harmless and is never undone,
// because the threads outlive the decoder.
static void com_here(void) {
    static __thread int done;
    if (done) return;
    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    done = 1;
}

// Pick NV12 from the output types the decoder offers and read back the buffer layout it will use.
static int choose_nv12_output(MovieAvc *a) {
    for (DWORD i = 0;; i++) {
        IMFMediaType *type = NULL;
        if (FAILED(IMFTransform_GetOutputAvailableType(a->decoder, 0, i, &type))) return 0;
        GUID subtype;
        int ok = SUCCEEDED(IMFMediaType_GetGUID(type, &MF_MT_SUBTYPE, &subtype)) && IsEqualGUID(&subtype, &MFVideoFormat_NV12) &&
                 SUCCEEDED(IMFTransform_SetOutputType(a->decoder, 0, type, 0));
        if (ok) {
            // frame size is packed as (width << 32 | height); the coded height may exceed the picture's (1080 -> 1088)
            UINT64 size = 0;
            UINT32 stride = 0;
            IMFMediaType_GetUINT64(type, &MF_MT_FRAME_SIZE, &size);
            a->coded_height = (int)(size & 0xffffffffu);
            a->stride = SUCCEEDED(IMFMediaType_GetUINT32(type, &MF_MT_DEFAULT_STRIDE, &stride)) && (int)stride > 0
                            ? (int)stride : (int)(size >> 32);
        }
        IMFMediaType_Release(type);
        if (ok) break;
    }
    MFT_OUTPUT_STREAM_INFO info = {0};
    if (FAILED(IMFTransform_GetOutputStreamInfo(a->decoder, 0, &info))) return 0;
    a->own_samples = (info.dwFlags & (MFT_OUTPUT_STREAM_PROVIDES_SAMPLES | MFT_OUTPUT_STREAM_CAN_PROVIDE_SAMPLES)) != 0;
    a->out_bytes = info.cbSize;
    return a->stride >= a->width && a->coded_height >= a->height;
}

MovieAvc *movie_avc_open(int width, int height) {
    com_here();
    if (FAILED(MFStartup(MF_VERSION, MFSTARTUP_LITE))) return NULL;
    MovieAvc *a = calloc(1, sizeof *a);
    if (!a) return NULL;
    a->width = width;
    a->height = height;
    IMFMediaType *in = NULL;
    // create the decoder and tell it what comes in: H.264 video of this size, progressive
    int ok = SUCCEEDED(CoCreateInstance(&k_h264_decoder, NULL, CLSCTX_INPROC_SERVER, &IID_IMFTransform, (void **)&a->decoder)) &&
             SUCCEEDED(MFCreateMediaType(&in)) &&
             SUCCEEDED(IMFMediaType_SetGUID(in, &MF_MT_MAJOR_TYPE, &MFMediaType_Video)) &&
             SUCCEEDED(IMFMediaType_SetGUID(in, &MF_MT_SUBTYPE, &MFVideoFormat_H264)) &&
             SUCCEEDED(IMFMediaType_SetUINT64(in, &MF_MT_FRAME_SIZE, ((UINT64)(UINT32)width << 32) | (UINT32)height)) &&
             SUCCEEDED(IMFMediaType_SetUINT32(in, &MF_MT_INTERLACE_MODE, MFVideoInterlace_Progressive)) &&
             SUCCEEDED(IMFTransform_SetInputType(a->decoder, 0, in, 0)) && choose_nv12_output(a);
    if (in) IMFMediaType_Release(in);
    if (ok) {
        IMFTransform_ProcessMessage(a->decoder, MFT_MESSAGE_NOTIFY_BEGIN_STREAMING, 0);
        IMFTransform_ProcessMessage(a->decoder, MFT_MESSAGE_NOTIFY_START_OF_STREAM, 0);
        return a;
    }
    movie_avc_close(a);
    return NULL;
}

void movie_avc_close(MovieAvc *a) {
    if (!a) return;
    com_here();
    if (a->decoder) IMFTransform_Release(a->decoder);
    free(a->scratch);
    free(a);
}

// After a seek: forget everything queued and decoded; the next input starts at a key frame.
void movie_avc_flush(MovieAvc *a) {
    com_here();
    IMFTransform_ProcessMessage(a->decoder, MFT_MESSAGE_COMMAND_FLUSH, 0);
}

void movie_avc_drain(MovieAvc *a) {
    com_here();
    IMFTransform_ProcessMessage(a->decoder, MFT_MESSAGE_NOTIFY_END_OF_STREAM, 0);
    IMFTransform_ProcessMessage(a->decoder, MFT_MESSAGE_COMMAND_DRAIN, 0);
}

// The Windows decoder wants "Annex B" input: each NAL unit preceded by the start code 00 00 00 01. MP4 files store
// NAL units with a 4-byte big-endian length instead. Accept both: input that already starts with a start code is
// passed through, anything else is treated as length-prefixed units and rewritten. Returns the byte count, 0 if the
// input is neither.
static int to_start_codes(MovieAvc *a, const uint8_t *data, int size, const uint8_t **out) {
    if (size >= 4 && data[0] == 0 && data[1] == 0 && (data[2] == 1 || (data[2] == 0 && data[3] == 1))) {
        *out = data;
        return size;
    }
    if (size > a->scratch_cap) {
        free(a->scratch);
        a->scratch = malloc((size_t)size);
        a->scratch_cap = a->scratch ? size : 0;
        if (!a->scratch) return 0;
    }
    int at = 0;
    while (at + 4 <= size) {
        uint32_t unit = (uint32_t)data[at] << 24 | (uint32_t)data[at + 1] << 16 | (uint32_t)data[at + 2] << 8 | data[at + 3];
        if (!unit || unit > (uint32_t)(size - at - 4)) return 0;
        // the length field and the start code are both 4 bytes, so the rewrite keeps every offset
        a->scratch[at] = a->scratch[at + 1] = a->scratch[at + 2] = 0;
        a->scratch[at + 3] = 1;
        memcpy(a->scratch + at + 4, data + at + 4, unit);
        at += 4 + (int)unit;
    }
    if (at != size) return 0;
    *out = a->scratch;
    return size;
}

// Queue one compressed access unit. 1 = taken, 0 = the decoder is full (receive a picture, then send again),
// -1 = error.
int movie_avc_send(MovieAvc *a, const uint8_t *data, int size, int64_t time_us) {
    com_here();
    if (a->inputs_logged < 3) {   // the first inputs show which byte layout the game's demuxer produces
        a->inputs_logged++;
        rt_log("movie: H.264 input %d: %d bytes at %lld us, starts %02x %02x %02x %02x %02x %02x %02x %02x", a->inputs_logged,
               size, (long long)time_us, size > 0 ? data[0] : 0, size > 1 ? data[1] : 0, size > 2 ? data[2] : 0,
               size > 3 ? data[3] : 0, size > 4 ? data[4] : 0, size > 5 ? data[5] : 0, size > 6 ? data[6] : 0,
               size > 7 ? data[7] : 0);
    }
    const uint8_t *bytes;
    int n = to_start_codes(a, data, size, &bytes);
    if (!n) return -1;
    IMFSample *sample = NULL;
    IMFMediaBuffer *buffer = NULL;
    BYTE *dst = NULL;
    int r = -1;
    // wrap the bytes in a Media Foundation sample stamped with the presentation time (100 ns units)
    if (SUCCEEDED(MFCreateSample(&sample)) && SUCCEEDED(MFCreateMemoryBuffer((DWORD)n, &buffer)) &&
        SUCCEEDED(IMFMediaBuffer_Lock(buffer, &dst, NULL, NULL))) {
        memcpy(dst, bytes, (size_t)n);
        IMFMediaBuffer_Unlock(buffer);
        IMFMediaBuffer_SetCurrentLength(buffer, (DWORD)n);
        IMFSample_AddBuffer(sample, buffer);
        IMFSample_SetSampleTime(sample, time_us * 10);
        HRESULT hr = IMFTransform_ProcessInput(a->decoder, 0, sample, 0);
        r = SUCCEEDED(hr) ? 1 : hr == MF_E_NOTACCEPTING ? 0 : -1;
    }
    if (buffer) IMFMediaBuffer_Release(buffer);
    if (sample) IMFSample_Release(sample);
    return r;
}

// Fetch one decoded picture as packed NV12 (width x height luma rows, then interleaved chroma rows) into dst.
// 1 = a picture and its time, 0 = none ready (send more input; after a drain: the stream is finished), -1 = error.
int movie_avc_receive(MovieAvc *a, uint8_t *dst, int64_t *time_us) {
    com_here();
    for (int attempt = 0; attempt < 4; attempt++) {
        MFT_OUTPUT_DATA_BUFFER out = {0};
        IMFMediaBuffer *buffer = NULL;
        DWORD status = 0;
        if (!a->own_samples) {   // we supply the buffer the decoder writes into
            if (FAILED(MFCreateSample(&out.pSample)) || FAILED(MFCreateMemoryBuffer(a->out_bytes, &buffer))) return -1;
            IMFSample_AddBuffer(out.pSample, buffer);
            IMFMediaBuffer_Release(buffer);
            buffer = NULL;
        }
        HRESULT hr = IMFTransform_ProcessOutput(a->decoder, 0, 1, &out, &status);
        if (out.pEvents) IMFCollection_Release(out.pEvents);
        int r = -1;
        if (hr == MF_E_TRANSFORM_NEED_MORE_INPUT) r = 0;
        else if (hr == MF_E_TRANSFORM_STREAM_CHANGE) r = choose_nv12_output(a) ? 2 : -1;   // layout known now: ask again
        else if (SUCCEEDED(hr) && out.pSample && SUCCEEDED(IMFSample_ConvertToContiguousBuffer(out.pSample, &buffer))) {
            BYTE *src = NULL;
            DWORD have = 0;
            LONGLONG t = 0;
            if (SUCCEEDED(IMFMediaBuffer_Lock(buffer, &src, NULL, &have)) &&
                have >= (DWORD)(a->stride * a->coded_height + a->stride * (a->height / 2))) {
                // copy the visible rows out of the decoder's padded layout: luma, then interleaved chroma
                for (int y = 0; y < a->height; y++) memcpy(dst + (size_t)y * a->width, src + (size_t)y * a->stride, (size_t)a->width);
                const BYTE *chroma = src + (size_t)a->stride * a->coded_height;
                for (int y = 0; y < a->height / 2; y++)
                    memcpy(dst + (size_t)(a->height + y) * a->width, chroma + (size_t)y * a->stride, (size_t)a->width);
                IMFMediaBuffer_Unlock(buffer);
                IMFSample_GetSampleTime(out.pSample, &t);
                *time_us = t / 10;
                r = 1;
            }
        }
        if (buffer) IMFMediaBuffer_Release(buffer);
        if (out.pSample) IMFSample_Release(out.pSample);
        if (r != 2) return r;
    }
    return -1;
}
