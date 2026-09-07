#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

static int parse_afp_version(const char *text)
{
    if (!text || strcmp(text, "auto") == 0) {
        return 0;
    }
    if (strcmp(text, "1.1") == 0) {
        return 11;
    }
    if (strcmp(text, "2.0") == 0) {
        return 20;
    }
    if (strcmp(text, "2.1") == 0) {
        return 21;
    }
    if (strcmp(text, "2.2") == 0) {
        return 22;
    }
    return -1;
}

static void usage(const char *prog)
{
    fprintf(stderr,
            "GlobalTalk AFP-over-DDP volume/directory browser\n"
            "Usage: %s [-A version] AFP_URL\n"
            "\n"
            "  -A version  AFP version: auto, 1.1, 2.0, 2.1, 2.2\n"
            "\n"
            "List server volumes:\n"
            "  %s 'afp+ddp://Blackbird@BaroNet'\n"
            "\n"
            "Probe an older server with AFP 2.0:\n"
            "  %s -A 2.0 'afp+ddp://Babylon 5@BabCom'\n"
            "\n"
            "List a volume or directory:\n"
            "  %s 'afp+ddp://Blackbird@BaroNet/Blackbird Public/path'\n",
            prog, prog, prog, prog);
}

int main(int argc, char **argv)
{
    int requested_version = 0;
    int opt;
    int rc;

    while ((opt = getopt(argc, argv, "A:h")) != -1) {
        switch (opt) {
        case 'A':
            requested_version = parse_afp_version(optarg);
            if (requested_version < 0) {
                fprintf(stderr, "gt-afp-ls: unsupported AFP version: %s\n",
                        optarg);
                usage(argv[0]);
                return 2;
            }
            break;
        case 'h':
            usage(argv[0]);
            return 0;
        default:
            usage(argv[0]);
            return 2;
        }
    }

    if (argc - optind != 1) {
        usage(argv[0]);
        return 2;
    }

    cmdline_afp_setup_client();
    cmdline_set_verbose(0);

    /* Non-batch setup keeps the normal afpcmd volume/path semantics. */
    if (cmdline_afp_setup(0, argv[optind], requested_version) != 0) {
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
