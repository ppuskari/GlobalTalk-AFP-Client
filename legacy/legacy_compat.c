#include "legacy_compat.h"

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
