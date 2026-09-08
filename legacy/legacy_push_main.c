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
    fprintf(stderr, "gt-afp-push: AFP client forced termination\n");
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
            "GlobalTalk AFP-over-DDP batch push client\n"
            "Usage: %s [-r] [-V] [-M mode] [-A version] LOCAL_PATH AFP_URL\n"
            "\n"
            "  -r        recursively upload directories\n"
            "  -V        verbose transfer output\n"
            "  -M mode   metadata mode: auto, netatalk, xattr, macos, none\n"
            "  -A ver    AFP version: auto, 1.1, 2.0, 2.1, 2.2\n"
            "\n"
            "The AFP URL selects the destination volume/directory.\n"
            "Example:\n"
            "  %s -r -V -M netatalk /tmp/corpus \\\n\n"
            "    'afp+ddp://server@zone/Volume/UploadTest'\n",
            prog, prog);
}

int main(int argc, char **argv)
{
    const char *metadata_mode = "netatalk";
    char *local_path;
    char *url;
    int requested_version = 0;
    int recursive = 0;
    int verbose = 0;
    int opt;
    int rc;

    while ((opt = getopt(argc, argv, "A:hM:rV")) != -1) {
        switch (opt) {
        case 'A':
            requested_version = parse_afp_version(optarg);
            if (requested_version < 0) {
                fprintf(stderr, "gt-afp-push: unsupported AFP version: %s\n",
                        optarg);
                usage(argv[0]);
                return 2;
            }
            break;
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

    local_path = argv[optind];
    url = argv[optind + 1];

    cmdline_afp_setup_client();
    cmdline_set_verbose(verbose);

    if (cmdline_set_metadata_mode(metadata_mode) != 0) {
        fprintf(stderr, "gt-afp-push: unknown metadata mode: %s\n",
                metadata_mode);
        return 2;
    }

    if (cmdline_afp_setup(1, url, requested_version) != 0) {
        fprintf(stderr, "gt-afp-push: AFP setup/connect failed\n");
        cmdline_afp_exit();
        return 1;
    }

    rc = cmdline_batch_transfer(local_path, 1, recursive);
    cmdline_afp_exit();

    if (rc < 0) {
        fprintf(stderr, "gt-afp-push: transfer failed\n");
        return 1;
    }

    return 0;
}
