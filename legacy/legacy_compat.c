#include "legacy_compat.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t strlcpy(char *dst, const char *src, size_t dstsize)
{
    size_t srclen = strlen(src);

    if (dstsize != 0) {
        size_t copylen = srclen >= dstsize ? dstsize - 1 : srclen;
        memcpy(dst, src, copylen);
        dst[copylen] = '\0';
    }

    return srclen;
}

char *readline(const char *prompt)
{
    char buffer[4096];
    char *line;
    size_t len;

    if (prompt && *prompt) {
        fputs(prompt, stdout);
        fflush(stdout);
    }

    if (!fgets(buffer, sizeof(buffer), stdin)) {
        return NULL;
    }

    len = strlen(buffer);
    if (len > 0 && buffer[len - 1] == '\n') {
        buffer[--len] = '\0';
    }

    line = malloc(len + 1);
    if (!line) {
        return NULL;
    }

    memcpy(line, buffer, len + 1);
    return line;
}
