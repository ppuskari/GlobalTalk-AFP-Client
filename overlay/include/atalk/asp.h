/*
 * GlobalTalk AFP Client -- minimal ASP wire constants
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * This intentionally does NOT include Netatalk's <atalk/afp.h>.
 * Netatalk Client 0.9.5 has its own AFP protocol declarations and including
 * both sets in one translation unit causes duplicate enum/type definitions.
 *
 * The AFP-over-DDP adapter only needs these ASP wire-format constants; ATP,
 * NBP and sockaddr_at declarations still come from the installed libatalk
 * development headers.
 */

#ifndef GLOBALTALK_AFP_ASP_WIRE_SHIM_H
#define GLOBALTALK_AFP_ASP_WIRE_SHIM_H 1

#define ASP_HDRSIZ        4
#define ASP_CMDSIZ        578
#define ASP_MAXPACKETS    8
#define ASP_CMDMAXSIZ     (ASP_CMDSIZ + ASP_HDRSIZ)
#define ASP_DATASIZ       (ASP_CMDSIZ * ASP_MAXPACKETS)
#define ASP_DATAMAXSIZ    ((ASP_CMDSIZ + ASP_HDRSIZ) * ASP_MAXPACKETS)

#define ASPFUNC_CLOSE     1
#define ASPFUNC_CMD       2
#define ASPFUNC_STAT      3
#define ASPFUNC_OPEN      4
#define ASPFUNC_TICKLE    5
#define ASPFUNC_WRITE     6
#define ASPFUNC_WRTCONT   7
#define ASPFUNC_ATTN      8

#define ASPERR_OK         0x0000
#define ASPERR_BADVERS    0xfbd6
#define ASPERR_BUFSMALL   0xfbd5
#define ASPERR_NOSESS     0xfbd4
#define ASPERR_NOSERV     0xfbd3
#define ASPERR_PARM       0xfbd2
#define ASPERR_SERVBUSY   0xfbd1
#define ASPERR_SESSCLOS   0xfbd0
#define ASPERR_SIZERR     0xfbcf
#define ASPERR_TOOMANY    0xfbce
#define ASPERR_NOACK      0xfbcd

#endif
