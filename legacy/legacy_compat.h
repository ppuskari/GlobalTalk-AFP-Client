#ifndef GT_AFP_LEGACY_COMPAT_H
#define GT_AFP_LEGACY_COMPAT_H

#include <stddef.h>

/*
 * Debian 8 / glibc does not provide strlcpy(), while Netatalk Client 0.9.5
 * uses it when libbsd development headers are unavailable.
 */
size_t strlcpy(char *dst, const char *src, size_t dstsize);

/*
 * cmdline_afp.c contains an interactive completion helper even in batch
 * builds.  The batch-only legacy target never calls it, but the translation
 * unit still references these readline globals.  Provide declarations here
 * and definitions in legacy_batch_main.c so no readline development package
 * is required.
 */
extern int rl_point;
extern char *rl_line_buffer;

#endif
