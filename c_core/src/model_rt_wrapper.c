/*
 * model_rt_wrapper.c
 *
 * Static-link replacement for model_loader.c.
 * The Simulink-generated model symbols are resolved via MODEL_RT_BRIDGE_H,
 * which is a header written by build_script.m and injected at compile time.
 *
 * Compile with:  -include path/to/model_rt_bridge.h
 * or:            -DMODEL_RT_BRIDGE_H='"path/to/model_rt_bridge.h"'
 *
 * Hot-reload: reads /tmp/model_ready.signal, then calls execv() to
 * replace this process with the freshly built executable.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <json-c/json.h>
#include <sys/stat.h>

/* The bridge header is injected at compile time (or default to hand-written model) */
#if !defined(MODEL_RT_BRIDGE_H)
#define MODEL_RT_BRIDGE_H "my_uav_model.h"
#endif

/* Bring in the generated type/function definitions.
   On a real ERT build the macro will point to the generated bridge;
   for development it points directly at my_uav_model.h. */
#define STRINGIFY_(x) #x
#define STRINGIFY(x) STRINGIFY_(x)
#include STRINGIFY(MODEL_RT_BRIDGE_H)

#include "model_rt_wrapper.h"

/* ---- preprocessor symbol glue ---- */
#define PASTE2(a, b) a##b
#define PASTE(a, b) PASTE2(a, b)

/*
 * Per-plan defaults.  build_script.m overrides these via -D so the
 * wrapper calls the correct model symbols even when the .slx name differs.
 */
#ifndef MODEL_INIT_FN
#define MODEL_INIT_FN  my_uav_model_initialize
#endif
#ifndef MODEL_STEP_FN
#define MODEL_STEP_FN  my_uav_model_step
#endif
#ifndef MODEL_TERM_FN
#define MODEL_TERM_FN  my_uav_model_terminate
#endif
#ifndef MODEL_U_VAR
#define MODEL_U_VAR    my_uav_model_U
#endif
#ifndef MODEL_Y_VAR
#define MODEL_Y_VAR    my_uav_model_Y
#endif

/* ---- implementation ---- */

/*
 * Compile-time assertion: ensure ModelU_t / ModelY_t sizes match the
 * generated model structs.  If this fails, model_rt_wrapper.h and the
 * generated model header have diverged.
 */
_Static_assert(sizeof(ModelU_t) == sizeof(MODEL_U_VAR),
               "ModelU_t size mismatch with generated model U struct");
_Static_assert(sizeof(ModelY_t) == sizeof(MODEL_Y_VAR),
               "ModelY_t size mismatch with generated model Y struct");

static int _loaded = 0;

void model_initialize(void) {
    MODEL_INIT_FN();
    _loaded = 1;
    printf("[ModelRT] Static-link model initialized via " STRINGIFY(MODEL_INIT_FN) "\n");
}

void model_step(void) {
    if (_loaded) MODEL_STEP_FN();
}

void model_terminate(void) {
    if (_loaded) { MODEL_TERM_FN(); _loaded = 0; }
}

ModelU_t* model_get_input(void) {
    return (ModelU_t*)&MODEL_U_VAR;
}

void model_get_output(ModelY_t* out) {
    if (out) memcpy(out, &MODEL_Y_VAR, sizeof(ModelY_t));
}

int model_is_loaded(void) { return _loaded; }

/* ---- hot-reload via execv ---- */

void model_check_for_update(void) {
    /* no-op: the check is done in main_rt.c's 1-sec tick by calling
       model_apply_pending_update when the signal file exists */
}

void model_apply_pending_update(int* argc_ptr, char** argv) {
    const char* signal_file = "/tmp/model_ready.signal";
    struct stat st;
    if (stat(signal_file, &st) != 0) return;

    FILE* f = fopen(signal_file, "r");
    if (!f) return;

    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char* content = malloc(size + 1);
    if (!content) { fclose(f); return; }
    size_t nr = fread(content, 1, size, f);
    if (nr > 0) content[nr] = '\0'; else content[0] = '\0';
    fclose(f);
    unlink(signal_file);

    struct json_object* root = json_tokener_parse(content);
    free(content);
    if (!root) return;

    struct json_object* exe_obj;
    const char* exe_path = NULL;
    json_object_object_get_ex(root, "exe_path", &exe_obj);
    if (exe_obj) exe_path = json_object_get_string(exe_obj);

    if (!exe_path) { json_object_put(root); return; }

    printf("[ModelRT] Hot-reload: execv(%s)\n", exe_path);

    model_terminate();

    /*
     * execv replaces this process.  argv[0] is the exe path, the rest
     * of argv is forwarded so the new instance knows its own args.
     */
    char** new_argv = malloc(2 * sizeof(char*));
    new_argv[0] = (char*)exe_path;
    new_argv[1] = NULL;

    execv(exe_path, new_argv);

    /* execv only returns on error */
    perror("[ModelRT] execv failed");
    free(new_argv);
    json_object_put(root);
    /* restart the old model so the loop doesn't crash while we wait */
    model_initialize();
}
