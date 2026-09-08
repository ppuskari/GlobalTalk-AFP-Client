#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
#
# Temporary R4C hardware diagnostic for AFP CreateDir/CreateFile over ASP.
# The server is demonstrably performing both mutations while the client reports
# a transport failure before afp_reply() is reached.  Record the ATP transaction
# state around atp_sreq()/atp_rresp() so we can distinguish no response from an
# incomplete response bitmap/EOM case without changing protocol behavior.

from __future__ import print_function

import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = (os.path.abspath(sys.argv[1]) if len(sys.argv) > 1
      else os.path.join(ROOT, "work", "netatalk-client"))
PATH = os.path.join(UP, "lib", "asp_transport.c")
MARKER = "GLOBALTALK R4C ASP XACT DIAG"


def die(msg):
    raise SystemExit("apply_asp_xact_diag: " + msg)


def replace_once(text, old, new, what):
    count = text.count(old)
    if count != 1:
        die("{}: expected guard once, found {}".format(what, count))
    return text.replace(old, new, 1)


if not os.path.exists(PATH):
    die("missing {}".format(PATH))

with io.open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

if MARKER in text:
    print("ASP transaction diagnostic already applied: {}".format(UP))
    raise SystemExit(0)

include_old = '''#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n'''
include_new = '''#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\n#include <stdio.h>\n'''
text = replace_once(text, include_old, include_new, "stdio include")

anchor = '''static int asp_xact(struct afpc_asp *ctx,\n'''
helper = r'''/* GLOBALTALK R4C ASP XACT DIAG
 * Temporary hardware-only diagnostic.  AFP command numbers 6 and 7 are
 * FPCreateDir and FPCreateFile in the pinned 0.9.5 command table.
 */
static void r4c_asp_xact_diag(const char *stage,
                              struct afpc_asp *ctx,
                              const void *request,
                              size_t request_len,
                              int rc,
                              int saved_errno,
                              int response_count)
{
    const unsigned char *p = (const unsigned char *)request;
    unsigned int cmd;
    FILE *f;

    if (!ctx || !ctx->atp || !p || request_len <= ASP_HDRSIZ ||
            p[0] != ASPFUNC_CMD) {
        return;
    }

    cmd = p[ASP_HDRSIZ];
    if (cmd != 6U && cmd != 7U) {
        return;
    }

    f = fopen("/tmp/gt-afp-r4c-asp-xact.log", "a");
    if (!f) {
        return;
    }

    fprintf(f,
            "R4C_ASP_XACT stage=%s cmd=%u sid=%u seq=%u "
            "rc=%d errno=%d respcount=%d rbitmap=0x%02x "
            "reqtries=%d rrespcount=%d\\n",
            stage,
            cmd,
            (unsigned int)p[1],
            request_len >= 4U ?
                (unsigned int)(((unsigned int)p[2] << 8) | p[3]) : 0U,
            rc,
            saved_errno,
            response_count,
            (unsigned int)ctx->atp->atph_rbitmap,
            ctx->atp->atph_reqtries,
            ctx->atp->atph_rrespcount);
    fclose(f);
}

'''
text = replace_once(text, anchor, helper + anchor, "asp_xact anchor")

old_sreq = '''    if (atp_sreq(ctx->atp, &atpb,\n                 (int)response_count, ATP_XO) < 0) {\n        return -1;\n    }\n\n    if (response_count == 0) {\n'''
new_sreq = '''    r4c_asp_xact_diag("before-sreq", ctx, request, request_len,\n                      0, 0, (int)response_count);\n\n    if (atp_sreq(ctx->atp, &atpb,\n                 (int)response_count, ATP_XO) < 0) {\n        int saved_errno = errno;\n        r4c_asp_xact_diag("sreq-fail", ctx, request, request_len,\n                          -1, saved_errno, (int)response_count);\n        errno = saved_errno;\n        return -1;\n    }\n\n    r4c_asp_xact_diag("after-sreq", ctx, request, request_len,\n                      0, 0, (int)response_count);\n\n    if (response_count == 0) {\n'''
text = replace_once(text, old_sreq, new_sreq, "atp_sreq block")

old_rresp = '''    if (atp_rresp(ctx->atp, &atpb) < 0) {\n        return -1;\n    }\n\n    for (i = 0; i < (unsigned int)atpb.atp_rresiovcnt; i++) {\n'''
new_rresp = '''    {\n        int rrc = atp_rresp(ctx->atp, &atpb);\n        int saved_errno = errno;\n        r4c_asp_xact_diag(rrc < 0 ? "rresp-fail" : "rresp-ok",\n                          ctx, request, request_len, rrc, saved_errno,\n                          (int)response_count);\n        if (rrc < 0) {\n            errno = saved_errno;\n            return -1;\n        }\n    }\n\n    for (i = 0; i < (unsigned int)atpb.atp_rresiovcnt; i++) {\n'''
text = replace_once(text, old_rresp, new_rresp, "atp_rresp block")

with io.open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

print("Applied ASP transaction diagnostic: {}".format(UP))
