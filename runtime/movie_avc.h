// H.264 decoding service for the host movie::Decoder (ov_movie.c). movie_avc_win.c implements it on Windows with the
// Media Foundation H.264 decoder.
//
// NOT IMPLEMENTED ELSEWHERE: other platforms have no implementation yet. A macOS/Linux port belongs in a sibling file
// (VideoToolbox / libavcodec) providing these same five functions; until then ov_movie.c must leave H.264 decoders to
// the library on those platforms.
#pragma once
#include <stdint.h>

typedef struct MovieAvc MovieAvc;

MovieAvc *movie_avc_open(int width, int height);                                      // NULL = no decoder available
void movie_avc_close(MovieAvc *a);
void movie_avc_flush(MovieAvc *a);                                                    // after a seek
void movie_avc_drain(MovieAvc *a);                                                    // no more input is coming
int movie_avc_send(MovieAvc *a, const uint8_t *data, int size, int64_t time_us);      // 1 taken, 0 full, -1 error
int movie_avc_receive(MovieAvc *a, uint8_t *nv12, int64_t *time_us);                  // 1 picture, 0 none, -1 error
