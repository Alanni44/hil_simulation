#include "model_loader.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <json-c/json.h>

typedef void (*fn_init)(void);
typedef void (*fn_step)(void);
typedef void (*fn_term)(void);

static struct {
    void* handle;
    fn_init init;
    fn_step step;
    fn_term term;
    ModelLoader_U_t* U;
    ModelLoader_Y_t* Y;
    char version[256];
    int loaded;
} g_ctx = {0};

static char pending_so_path[512] = {0};
static int has_pending = 0;

int model_load(const char* so_path) {
    if (g_ctx.loaded) {
        if (g_ctx.term) g_ctx.term();
        if (g_ctx.handle) dlclose(g_ctx.handle);
        g_ctx.loaded = 0;
        printf("[ModelLoader] Unloaded old\n");
    }

    void* h = dlopen(so_path, RTLD_NOW | RTLD_GLOBAL);
    if (!h) {
        fprintf(stderr, "[ModelLoader] dlopen failed: %s\n", dlerror());
        return -1;
    }

    fn_init init = (fn_init)dlsym(h, "my_uav_model_initialize");
    fn_step step = (fn_step)dlsym(h, "my_uav_model_step");
    fn_term term = (fn_term)dlsym(h, "my_uav_model_terminate");
    ModelLoader_U_t* U = (ModelLoader_U_t*)dlsym(h, "my_uav_model_U");
    ModelLoader_Y_t* Y = (ModelLoader_Y_t*)dlsym(h, "my_uav_model_Y");

    if (!init || !step || !term || !U || !Y) {
        fprintf(stderr, "[ModelLoader] Missing symbols in %s\n", so_path);
        dlclose(h);
        return -1;
    }

    g_ctx.handle = h;
    g_ctx.init = init;
    g_ctx.step = step;
    g_ctx.term = term;
    g_ctx.U = U;
    g_ctx.Y = Y;
    g_ctx.loaded = 1;
    snprintf(g_ctx.version, sizeof(g_ctx.version), "%s", so_path);

    init();
    printf("[ModelLoader] Loaded: %s\n", so_path);
    return 0;
}

void model_unload(void) {
    if (g_ctx.loaded) {
        if (g_ctx.term) g_ctx.term();
        if (g_ctx.handle) dlclose(g_ctx.handle);
        g_ctx.loaded = 0;
        printf("[ModelLoader] Unloaded\n");
    }
}

int model_is_loaded(void) { return g_ctx.loaded; }
void model_step_call(void) { if (g_ctx.loaded && g_ctx.step) g_ctx.step(); }
void model_get_output(ModelLoader_Y_t* out) {
    if (g_ctx.loaded && g_ctx.Y) memcpy(out, g_ctx.Y, sizeof(ModelLoader_Y_t));
}
ModelLoader_U_t* model_get_input(void) { return g_ctx.loaded ? g_ctx.U : NULL; }
const char* model_get_version(void) { return g_ctx.loaded ? g_ctx.version : NULL; }

void model_check_for_update(void) {
    const char* signal_file = "/tmp/model_ready.signal";
    if (access(signal_file, F_OK) != 0) return;

    FILE* f = fopen(signal_file, "r");
    if (!f) return;

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char* content = malloc(size + 1);
    if (!content) { fclose(f); return; }
    fread(content, 1, size, f);
    content[size] = '\0';
    fclose(f);

    struct json_object *root, *so_path_obj;
    root = json_tokener_parse(content);
    if (root) {
        json_object_object_get_ex(root, "so_path", &so_path_obj);
        if (so_path_obj) {
            const char* path = json_object_get_string(so_path_obj);
            strncpy(pending_so_path, path, sizeof(pending_so_path) - 1);
            has_pending = 1;
            printf("[ModelLoader] New model pending: %s\n", pending_so_path);
        }
        json_object_put(root);
    }
    free(content);
    unlink(signal_file);
}

void model_apply_pending_update(void) {
    if (!has_pending) return;
    printf("[ModelLoader] Applying update: %s\n", pending_so_path);
    int ret = model_load(pending_so_path);
    if (ret == 0) {
        printf("[ModelLoader] Update successful\n");
    } else {
        printf("[ModelLoader] Update failed\n");
    }
    has_pending = 0;
    memset(pending_so_path, 0, sizeof(pending_so_path));
}