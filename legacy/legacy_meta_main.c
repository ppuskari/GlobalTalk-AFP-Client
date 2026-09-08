#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "afp.h"
#include "cmdline_afp.h"

/* Satisfy the unused interactive completion helper in cmdline_afp.c. */
int rl_point = 0;
char *rl_line_buffer = NULL;

void trigger_connected(void)
{
}

void cmdline_loop_started(void)
{
}

void cmdline_forced_ending_hook(void)
{
    fprintf(stderr, "gt-afp-meta: AFP client forced termination\n");
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
            "GlobalTalk AFP-over-DDP metadata validation tool\n"
            "Usage: %s [-A version] AFP_URL TYPE ACTION REMOTE_PATH [FILE]\n"
            "\n"
            "  TYPE    finderinfo | resourcefork\n"
            "  ACTION  get | set | remove\n"
            "  FILE    required for set; optional output file for get\n"
            "\n"
            "AFP_URL should select the server volume or a directory.\n"
            "Examples:\n"
            "  %s 'afp+ddp://server@zone/Volume/Test' \\\n\n"
            "    finderinfo get 'Sample' finderinfo.bin\n"
            "  %s 'afp+ddp://server@zone/Volume/Test' \\\n\n"
            "    resourcefork set 'Sample' rfork.bin\n",
            prog, prog, prog);
}

static int append_quoted(char *out, size_t out_size, size_t *used,
                         const char *arg)
{
    size_t i;

    if (*used != 0) {
        if (*used + 1 >= out_size) {
            return -1;
        }
        out[(*used)++] = ' ';
    }

    if (*used + 1 >= out_size) {
        return -1;
    }
    out[(*used)++] = '"';

    for (i = 0; arg[i] != '\0'; i++) {
        if (arg[i] == '\\' || arg[i] == '"') {
            if (*used + 1 >= out_size) {
                return -1;
            }
            out[(*used)++] = '\\';
        }
        if (*used + 1 >= out_size) {
            return -1;
        }
        out[(*used)++] = arg[i];
    }

    if (*used + 2 > out_size) {
        return -1;
    }
    out[(*used)++] = '"';
    out[*used] = '\0';
    return 0;
}

int main(int argc, char **argv)
{
    char command[MAX_INPUT_LEN];
    size_t used = 0;
    int requested_version = 0;
    int opt;
    int rc;
    int i;
    char *url;
    char *type;
    char *action;

    while ((opt = getopt(argc, argv, "A:h")) != -1) {
        switch (opt) {
        case 'A':
            requested_version = parse_afp_version(optarg);
            if (requested_version < 0) {
                fprintf(stderr, "gt-afp-meta: unsupported AFP version: %s\n",
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

    if (argc - optind < 4 || argc - optind > 5) {
        usage(argv[0]);
        return 2;
    }

    url = argv[optind];
    type = argv[optind + 1];
    action = argv[optind + 2];

    if (strcmp(type, "finderinfo") != 0
            && strcmp(type, "resourcefork") != 0) {
        fprintf(stderr, "gt-afp-meta: unsupported metadata type: %s\n", type);
        return 2;
    }

    if (strcmp(action, "get") != 0
            && strcmp(action, "set") != 0
            && strcmp(action, "remove") != 0) {
        fprintf(stderr, "gt-afp-meta: unsupported action: %s\n", action);
        return 2;
    }

    if (strcmp(action, "set") == 0 && argc - optind != 5) {
        fprintf(stderr, "gt-afp-meta: set requires an input file\n");
        return 2;
    }
    if (strcmp(action, "remove") == 0 && argc - optind != 4) {
        fprintf(stderr, "gt-afp-meta: remove does not take a local file\n");
        return 2;
    }

    memset(command, 0, sizeof(command));
    if (append_quoted(command, sizeof(command), &used, action) != 0) {
        return 2;
    }

    for (i = optind + 3; i < argc; i++) {
        if (append_quoted(command, sizeof(command), &used, argv[i]) != 0) {
            fprintf(stderr, "gt-afp-meta: command too long\n");
            return 2;
        }
    }

    cmdline_afp_setup_client();
    cmdline_set_verbose(0);

    if (cmdline_afp_setup(0, url, requested_version) != 0) {
        fprintf(stderr, "gt-afp-meta: AFP setup/connect failed\n");
        cmdline_afp_exit();
        return 1;
    }

    if (strcmp(type, "finderinfo") == 0) {
        rc = com_finderinfo(command);
    } else {
        rc = com_resourcefork(command);
    }

    cmdline_afp_exit();

    if (rc < 0) {
        fprintf(stderr, "gt-afp-meta: operation failed\n");
        return 1;
    }

    return 0;
}
