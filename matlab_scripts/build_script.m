function build_script(task_file, result_file)
%BUILD_SCRIPT Strict package-contract ERT/GCC builder.
% A task must identify a local package and its explicit hil_contract.json.
% No port aliases, inferred constants or default output values are generated.
    try
        task = read_json(task_file);
        require_task(task, {'model_name','slx_path','contract_path','output_dir','executable_dir'});
        model_name = task.model_name;
        slx_path = task.slx_path;
        contract_path = task.contract_path;
        output_dir = task.output_dir;
        executable_dir = task.executable_dir;
        contract = read_json(contract_path);
        if ~strcmp(contract.model_name, model_name)
            error('task model_name and contract.model_name differ');
        end
        if ~exist(slx_path, 'file'), error('Top model SLX not found'); end
        if ~exist(output_dir, 'dir'), mkdir(output_dir); end
        if ~exist(executable_dir, 'dir'), mkdir(executable_dir); end

        script_dir = fileparts(mfilename('fullpath'));
        hil_root = fileparts(script_dir);
        c_core_src = fullfile(hil_root, 'c_core', 'src');
        interface_json = fullfile(output_dir, [model_name '_interface.json']);
        analyze_model(slx_path, interface_json);
        adapted_slx = fullfile(output_dir, [model_name '_contract_copy.slx']);
        adapt_model(slx_path, interface_json, contract_path, adapted_slx);

        % The validation copy is deliberately never opened: a Simulink SLX
        % carries its model name internally, and renaming the file is neither
        % a model adaptation nor a valid way to select the build target.
        load_system(slx_path);
        close_cleanup = onCleanup(@() close_model_without_save(model_name));
        original_dir = pwd;
        cwd_cleanup = onCleanup(@() cd(original_dir));
        work_dir = fullfile(output_dir, 'matlab_build_work');
        if ~exist(work_dir, 'dir'), mkdir(work_dir); end
        cd(work_dir);
        Simulink.fileGenControl('set', 'CacheFolder', fullfile(output_dir, 'slcache'), ...
            'CodeGenFolder', output_dir, 'CodeGenFolderStructure', ...
            Simulink.filegen.CodeGenFolderStructure.ModelSpecific, 'createDir', true);
        set_param(model_name, 'SystemTargetFile', 'ert.tlc');
        set_param(model_name, 'TargetLang', 'C');
        try, set_param(model_name, 'GenerateCodeOnly', 'on');
        catch, set_param(model_name, 'GenCodeOnly', 'on'); end
        set_param(model_name, 'SolverType', 'Fixed-step');
        set_param(model_name, 'Solver', 'FixedStepDiscrete');
        set_param(model_name, 'FixedStep', '0.001');
        set_param(model_name, 'CodeInterfacePackaging', 'Nonreusable function');
        rtwbuild(model_name);

        build_info = RTW.getBuildDir(model_name);
        code_dir = build_info.BuildDirectory;
        model_h = fullfile(code_dir, [model_name '.h']);
        [u_type, y_type] = find_ert_io_types(model_h);
        if isempty(u_type) || isempty(y_type)
            error('ERT external input/output ABI was not generated');
        end
        u_fields = parse_struct_fields_with_types(model_h, u_type);
        y_fields = parse_struct_fields_with_types(model_h, y_type);
        validate_contract_abi(contract, y_fields, u_fields);
        generate_contract_header(fullfile(code_dir, 'model_contract.h'), contract, y_fields, u_fields);
        generate_bridge_header(fullfile(code_dir, 'model_rt_bridge.h'), model_name, u_type, y_type);

        c_files = dir(fullfile(code_dir, '*.c'));
        flags = generated_c_flags(code_dir, c_files);
        exe_path = fullfile(executable_dir, [model_name '_rt']);
        cmd = sprintf(['gcc -O2 -Wall -pthread -I"%s" -I"%s" ' ...
            '-DMODEL_RT_BRIDGE_HEADER=model_rt_bridge.h %s ' ...
            '"%s/main_rt.c" "%s/model_rt_wrapper.c" "%s/local_udp.c" ' ...
            '"%s/hal_stub.c" -lm -lrt -ljson-c -o "%s"'], ...
            code_dir, c_core_src, flags, c_core_src, c_core_src, c_core_src, c_core_src, exe_path);
        [status, output] = system(cmd);
        if status ~= 0, error('GCC failed: %s', output); end
        write_json(result_file, struct('code', 0, 'message', 'Build successful', ...
            'exe_path', exe_path, 'model_name', model_name, ...
            'contract_path', contract_path));
    catch ME
        write_json(result_file, struct('code', -1, 'message', ME.message));
    end
end

function require_task(task, names)
    for i = 1:length(names)
        if ~isfield(task, names{i}) || isempty(task.(names{i}))
            error('Build task missing %s', names{i});
        end
    end
end

function value = read_json(path)
    fid = fopen(path, 'r');
    if fid < 0, error('Cannot open %s', path); end
    value = jsondecode(fread(fid, '*char')'); fclose(fid);
end

function write_json(path, value)
    fid = fopen(path, 'w'); fprintf(fid, '%s', jsonencode(value)); fclose(fid);
end

function [u_type, y_type] = find_ert_io_types(header_path)
    content = fileread(header_path);
    u = regexp(content, 'typedef\s+struct\s*\{[\s\S]*?\}\s*(ExtU[A-Za-z0-9_]*)\s*;', 'tokens', 'once');
    y = regexp(content, 'typedef\s+struct\s*\{[\s\S]*?\}\s*(ExtY[A-Za-z0-9_]*)\s*;', 'tokens', 'once');
    u_type = ''; y_type = '';
    if ~isempty(u), u_type = u{1}; end
    if ~isempty(y), y_type = y{1}; end
end

function fields = parse_struct_fields_with_types(header_path, struct_name)
    content = fileread(header_path);
    token = regexp(content, ['typedef\s+struct\s*\{([\s\S]*?)\}\s*' struct_name '\s*;'], 'tokens', 'once');
    if isempty(token), error('Cannot parse generated ABI struct %s', struct_name); end
    body = regexprep(token{1}, '/\*[\s\S]*?\*/|//[^\r\n]*', '');
    declarations = regexp(body, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*;', 'tokens', 'lineanchors');
    fields = struct('name', {}, 'type', {});
    for i = 1:length(declarations)
        fields(end+1).type = declarations{i}{1}; %#ok<AGROW>
        fields(end).name = declarations{i}{2};
    end
    if isempty(fields), error('Generated ABI struct %s has no scalar fields', struct_name); end
end

function validate_contract_abi(contract, y_fields, u_fields)
    required = required_state_fields();
    if ~isfield(contract, 'state') || ~isfield(contract.state, 'outputs') || ...
            ~isfield(contract.state, 'units')
        error('Contract does not declare required state outputs and units');
    end
    for i = 1:length(required)
        key = required{i};
        if ~isfield(contract.state.outputs, key) || ~isfield(contract.state.units, key)
            error('Contract missing %s', key);
        end
        if ~strcmp(contract.state.units.(key), required_unit(key))
            error('Contract unit for %s is invalid', key);
        end
        field = lookup_field(y_fields, contract.state.outputs.(key));
        if isempty(field), error('Generated ExtY field missing: %s', contract.state.outputs.(key)); end
        if strcmp(key, 'airborne')
            if ~is_bool_type(field.type), error('airborne must be generated boolean scalar'); end
        elseif ~is_numeric_type(field.type)
            error('state output %s has unsupported generated type %s', key, field.type);
        end
    end
    if ~isfield(contract, 'parameters') || ~iscell_or_struct_array(contract.parameters)
        error('Contract parameters must be an array');
    end
    params = as_cell(contract.parameters);
    for i = 1:length(params)
        p = params{i};
        required_param_fields = {'name','generated_field','type','unit','default','min','max','class','allowed_phases'};
        for j = 1:length(required_param_fields)
            if ~isfield(p, required_param_fields{j}), error('Parameter lacks %s', required_param_fields{j}); end
        end
        if strcmp(p.class, 'readonly')
            f = lookup_field(y_fields, p.generated_field);
            if isempty(f), error('Readonly generated_field does not exist in ExtY: %s', p.generated_field); end
        else
            f = lookup_field(u_fields, p.generated_field);
            if isempty(f), error('Writable generated_field does not exist in ExtU: %s', p.generated_field); end
        end
        if strcmp(p.type, 'bool')
            if ~is_bool_type(f.type), error('Parameter %s boolean ABI mismatch', p.name); end
        elseif ~is_numeric_type(f.type)
            error('Parameter %s numeric ABI mismatch', p.name);
        end
        if ~any(strcmp(p.class, {'live','reset_only','readonly'})), error('Invalid parameter class'); end
    end
end

function generate_contract_header(path, contract, y_fields, u_fields)
    fid = fopen(path, 'w'); if fid < 0, error('Cannot write model_contract.h'); end
    fprintf(fid, '#ifndef HIL_MODEL_CONTRACT_H\n#define HIL_MODEL_CONTRACT_H\n#include <string.h>\n');
    required = required_state_fields();
    for i = 1:length(required)
        key = required{i}; name = contract.state.outputs.(key);
        fprintf(fid, '#define MODEL_READ_%s(y) ((y)->%s)\n', key, name);
    end
    params = as_cell(contract.parameters);
    fprintf(fid, 'enum { HIL_PARAM_LIVE=1, HIL_PARAM_RESET_ONLY=2, HIL_PARAM_READONLY=3 };\n');
    fprintf(fid, 'typedef struct { const char* name; int klass; double min_value; double max_value; int is_bool; unsigned phase_mask; } HilParameterSpec;\n');
    fprintf(fid, '#define HIL_PARAMETER_COUNT %d\n', length(params));
    fprintf(fid, 'static const HilParameterSpec HIL_PARAMETER_SPECS[HIL_PARAMETER_COUNT ? HIL_PARAMETER_COUNT : 1] = {\n');
    for i = 1:length(params)
        p = params{i};
        fprintf(fid, '{"%s", HIL_PARAM_%s, %.17g, %.17g, %d, %u},\n', p.name, upper(p.class), p.min, p.max, strcmp(p.type,'bool'), phase_mask_for_parameter(p));
    end
    if isempty(params), fprintf(fid, '{"",0,0,0,0,0},\n'); end
    fprintf(fid, '};\n');
    fprintf(fid, 'static unsigned hil_contract_phase_mask(const char* name) { unsigned i; for (i=0; i<HIL_PARAMETER_COUNT; ++i) if (!strcmp(HIL_PARAMETER_SPECS[i].name,name)) return HIL_PARAMETER_SPECS[i].phase_mask; return 0; }\n');
    fprintf(fid, 'static void hil_contract_apply_defaults(ModelU_t* u) {\n');
    for i = 1:length(params)
        p = params{i};
        if strcmp(p.class, 'readonly')
            continue;
        end
        if strcmp(p.type, 'bool')
            fprintf(fid, 'u->%s = %d;\n', p.generated_field, logical(p.default));
        else
            fprintf(fid, 'u->%s = (%s)%.17g;\n', p.generated_field, c_cast_type(p.type), p.default);
        end
    end
    fprintf(fid, '}\n');
    fprintf(fid, 'static int hil_contract_set_parameter(ModelU_t* u, const char* name, double value) {\n');
    for i = 1:length(params)
        p = params{i};
        if ~strcmp(p.class, 'readonly')
            if strcmp(p.type, 'bool')
                fprintf(fid, 'if (!strcmp(name,"%s")) { u->%s = value != 0.0; return 1; }\n', p.name, p.generated_field);
            else
                fprintf(fid, 'if (!strcmp(name,"%s")) { u->%s = (%s)value; return 1; }\n', p.name, p.generated_field, c_cast_type(p.type));
            end
        end
    end
    fprintf(fid, '(void)u; (void)name; (void)value; return 0; }\n#endif\n'); fclose(fid);
end

function generate_bridge_header(path, model_name, u_type, y_type)
    fid = fopen(path, 'w');
    fprintf(fid, '#ifndef HIL_MODEL_RT_BRIDGE_H\n#define HIL_MODEL_RT_BRIDGE_H\n#include "%s.h"\n', model_name);
    fprintf(fid, 'typedef %s ModelU_t;\n#define MODEL_U_T_DEFINED 1\ntypedef %s ModelY_t;\n#define MODEL_Y_T_DEFINED 1\n', u_type, y_type);
    fprintf(fid, '#define MODEL_INIT_FN %s_initialize\n#define MODEL_STEP_FN %s_step\n#define MODEL_TERM_FN %s_terminate\n#define MODEL_U_VAR %s_U\n#define MODEL_Y_VAR %s_Y\n#endif\n', model_name, model_name, model_name, model_name, model_name);
    fclose(fid);
end

function flags = generated_c_flags(code_dir, c_files)
    flags = '';
    for i = 1:length(c_files)
        if ~strcmp(c_files(i).name, 'ert_main.c')
            flags = [flags ' "' fullfile(code_dir, c_files(i).name) '"']; %#ok<AGROW>
        end
    end
end

function field = lookup_field(fields, name)
    field = [];
    for i = 1:length(fields)
        if strcmp(fields(i).name, name), field = fields(i); return; end
    end
end

function yes = is_numeric_type(type)
    yes = any(strcmp(type, {'real_T','real32_T','real64_T','double','float','int8_T','uint8_T','int16_T','uint16_T','int32_T','uint32_T','int64_T','uint64_T'}));
end

function yes = is_bool_type(type), yes = any(strcmp(type, {'boolean_T','bool','uint8_T'})); end
function yes = iscell_or_struct_array(value), yes = iscell(value) || isstruct(value); end
function cells = as_cell(value), if iscell(value), cells = value; else, cells = num2cell(value); end, end
function t = c_cast_type(type), if strcmp(type,'float'), t='float'; else, t='double'; end, end
function mask = phase_mask_for_parameter(parameter)
    mask = 0;
    phases = as_cell(parameter.allowed_phases);
    for i = 1:length(phases)
        switch phases{i}
            case 'RUNNING', mask = bitor(mask, 1);
            case 'PAUSED', mask = bitor(mask, 2);
            case 'RESETTING', mask = bitor(mask, 4);
            case 'ENDED', mask = bitor(mask, 8);
            otherwise, error('Invalid allowed task phase');
        end
    end
    if mask == 0, error('Parameter allowed_phases must not be empty'); end
end
function close_model_without_save(model_name), if bdIsLoaded(model_name), close_system(model_name, 0); end, end
function fields = required_state_fields(), fields = {'north_m','east_m','down_m','vn_mps','ve_mps','vd_mps','q_w','q_x','q_y','q_z','p_radps','q_radps','r_radps','airborne'}; end
function unit = required_unit(field)
    units = struct('north_m','m','east_m','m','down_m','m','vn_mps','m/s','ve_mps','m/s','vd_mps','m/s','q_w','1','q_x','1','q_y','1','q_z','1','p_radps','rad/s','q_radps','rad/s','r_radps','rad/s','airborne','bool'); unit = units.(field);
end
