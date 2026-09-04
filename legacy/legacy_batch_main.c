#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "afp.h"
#include "cmdline_afp.h"

/* Satisfy the unused interactive completion helper in cmdline_afp.c. */
int rl_point = 0;
char *rl_line_buffer = NULL;

/* Batch mode does not need the interactive UI synchronization callbacks. */
void trigger_connected(void)
{
}

void cmdline_loop_started(void)
{
}

void cmdline_forced_ending_hook(void)
{
    fprintf(stderr, "gt-afp-pull: AFP client forced termination\n");
    _exit(1);
}

static void usage(const char *prog)
{
    fprintf(stderr,
            "GlobalTalk AFP-over-DDP batch pull client\n"
            "Usage: %s [-r] [-V] [-M mode] AFP_URL LOCAL_PATH\n"
            "\n"
            "  -r        recursively retrieve directories\n"
            "  -V        verbose transfer output\n"
            "  -M mode   metadata mode: auto, netatalk, xattr, macos, none\n"
            "\n"
            "Example:\n"
            "  %s -r -V -M netatalk \\\n\n"
            "    'afp+ddp://BLIHNMNTE01@HuskyNet Global/VOLUME/path' \\\n\n"
            "    /srv/netatalk/archive\n",
            prog, prog);
}

int main(int argc, char **argv)
{
    const char *metadata_mode = "netatalk";
    char *url;
    char *local_path;
    int recursive = 0;
    int verbose = 0;
    int opt;
    int rc;

    while ((opt = getopt(argc, argv, "hM:rV")) != -1) {
        switch (opt) {
        case 'h':
            usage(argv[0]);
            return 0;
        case 'M':
            metadata_mode = optarg;
            break;
        case 'r':
            recursive = 1;
            break;
        case 'V':
            verbose = 1;
            break;
        default:
            usage(argv[0]);
            return 2;
        }
    }

    if (argc - optind != 2) {
        usage(argv[0]);
        return 2;
    }

    url = argv[optind];
    local_path = argv[optind + 1];

    cmdline_afp_setup_client();
    cmdline_set_verbose(verbose);

    if (cmdline_set_metadata_mode(metadata_mode) != 0) {
        fprintf(stderr, "gt-afp-pull: unknown metadata mode: %s\n",
                metadata_mode);
        return 2;
    }

    if (cmdline_afp_setup(1, url) != 0) {
        fprintf(stderr, "gt-afp-pull: AFP setup/connect failed\n");
        cmdline_afp_exit();
        return 1;
    }

    rc = cmdline_batch_transfer(local_path, 0, recursive);
    cmdline_afp_exit();

    if (rc < 0) {
        fprintf(stderr, "gt-afp-pull: transfer failed\n");
        return 1;
    }

    return 0;
}
