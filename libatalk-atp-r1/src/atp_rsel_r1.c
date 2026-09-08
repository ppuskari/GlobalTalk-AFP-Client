/*
 * libatalk ATP-R1 compatibility shim
 *
 * Purpose:
 *   Prevent Netatalk 2.2.4 atp_rsel() from entering an unbounded blocking
 *   receive after the current response transaction has exhausted its retries.
 *
 * This wrapper is intentionally narrow. It does not modify normal ATP packet
 * processing, retries, TIDs, response bitmaps, or the public ABI.
 *
 * The build script renames the original libatalk symbol:
 *     atp_rsel -> atp_rsel_legacy
 * then installs this function as the public atp_rsel().
 */

#include <errno.h>

#include <atalk/atp.h>

extern int atp_rsel_legacy(ATP,
                           struct sockaddr_at *,
                           int);

int
atp_rsel(ATP ah, struct sockaddr_at *faddr, int func)
{
    /*
     * atp_rresp() calls atp_rsel(..., ATP_TRESP) in a loop.
     *
     * In old libatalk, an incomplete/unusable packet can make atp_rsel()
     * return 0 after resend_request() has consumed the final retry.
     * On the next call, "requesting" is false; the legacy implementation
     * skips select() and its timeout and can block forever in receive.
     *
     * If a response transaction is still incomplete but there are no
     * retries left, its only correct outcome is ETIMEDOUT.
     */
    if (ah != 0 &&
        (func & ATP_TRESP) != 0 &&
        ah->atph_rrespcount > 0 &&
        ah->atph_rbitmap != 0 &&
        ah->atph_reqtries <= 0 &&
        ah->atph_reqtries != ATP_TRIES_INFINITE) {
        errno = ETIMEDOUT;
        return -1;
    }

    return atp_rsel_legacy(ah, faddr, func);
}
