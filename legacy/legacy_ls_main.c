#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#include "afp.h"
#include "cmdline_afp.h"

/* Satisfy the unused interactive completion helper in cmdline_afp.c. */
int rl_point = 0;
char *rl_line_buffer = NULL;

/* This small browser is synchronous and does not use the interactive UI. */
void trigger_connected(void)
{
}

void cmdline_loop_started(void)
{
}

void cmdline_forced_ending_hook(void)
{
    fprintf(stderr, "gt-afp-ls: AFP client forced termination\n");
    _exit(1);
}

static void usage(const char *prog)
{
    fprintf(stderr,
            "GlobalTalk AFP-over-DDP volume/directory browser\n"
            "Usage: %s AFP_URL\n"
            "\n"
            "List server volumes:\n"
            "  %s 'afp+ddp://Blackbird@BaroNet'\n"
            "\n"
            "List a volume or directory:\n"
            "  %s 'afp+ddp://Blackbird@BaroNet/Blackbird Public/path'\n",
            prog, prog, prog);
}

int main(int argc, char **argv)
{
    int rc;

    if (argc != 2) {
        usage(argv[0]);
        return 2;
    }

    cmdline_afp_setup_client();
    cmdline_set_verbose(0);

    /* Non-batch setup keeps the normal afpcmd volume/path semantics. */
    if (cmdline_afp_setup(0, argv[1]) != 0) {
        fprintf(stderr, "gt-afp-ls: AFP setup/connect failed\n");
        cmdline_afp_exit();
        return 1;
    }

    /* With no attached volume com_dir(\"\") lists volumes.  With a volume
     * or rooted path in the URL it lists the selected directory. */
    rc = com_dir("");
    cmdline_afp_exit();

    if (rc < 0) {
        fprintf(stderr, "gt-afp-ls: listing failed\n");
        return 1;
    }

    return 0;
}
