#ifndef GT_AFP_LEGACY_COMPAT_H
#define GT_AFP_LEGACY_COMPAT_H

#include <stddef.h>

/*
 * Debian 8 / glibc does not provide strlcpy(), while Netatalk Client 0.9.5
 * uses it when libbsd development headers are unavailable.
 */
size_t strlcpy(char *dst, const char *src, size_t dstsize);

/*
 * cmdline_afp.c retains a few readline-oriented helpers even in the batch
 * transfer path.  The Jessie legacy target deliberately does not depend on
 * GNU Readline, so provide the tiny ABI surface that translation unit needs.
 * readline() returns malloc-owned storage just like GNU Readline.
 */
char *readline(const char *prompt);
extern int rl_point;
extern char *rl_line_buffer;

#endif
