#ifndef MODEL_RT_WRAPPER_H
#define MODEL_RT_WRAPPER_H

#ifdef __cplusplus
extern "C" {
#endif

/* The build script provides the generated ERT ABI through this header.
 * Include it before declaring development fallbacks so every translation
 * unit sees the exact same ModelU_t and ModelY_t definitions. */
#if defined(MODEL_RT_BRIDGE_HEADER)
#define MODEL_RT_STRINGIFY_(x) #x
#define MODEL_RT_STRINGIFY(x) MODEL_RT_STRINGIFY_(x)
#include MODEL_RT_STRINGIFY(MODEL_RT_BRIDGE_HEADER)
#endif

/*
 * When MODEL_RT_BRIDGE_HEADER is defined (by build_script.m at compile time),
 * the bridge header provides ModelU_t and ModelY_t typedefs automatically
 * (pointing to the generated model's actual struct types).
 *
 * There is no production fallback ABI: a deployable executable is compiled
 * only after MATLAB has generated model_rt_bridge.h from a verified package.
 */

#if !defined(MODEL_U_T_DEFINED) || !defined(MODEL_Y_T_DEFINED)
#error "A generated and contract-verified ModelU_t/ModelY_t bridge is required"
#endif

/* ---- Static-link model API ---- */

void model_initialize(void);
void model_step(void);
void model_terminate(void);
ModelU_t* model_get_input(void);
void model_get_output(ModelY_t* out);
int model_is_loaded(void);

#ifdef __cplusplus
}
#endif

#endif
