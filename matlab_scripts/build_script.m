function build_script(task_file, result_file)
%BUILD_SCRIPT HIL model build pipeline (V2 — with auto-adaptation)
%
% Task JSON fields:
%   model_name   - model name (e.g. 'Quad_sim')
%   slx_path     - absolute path to .slx file
%   output_dir   - where generated code & executable go
%   lib_name     - ignored (legacy)
%
% New V2 pipeline:
%   1. analyze_model     → interface.json
%   2. adapt_model       → _adapted.slx + field_mapping.json
%   3. configure ERT + rtwbuild
%   4. parse generated types → model_mapping.h
%   5. generate model_config.h (for main_rt.c)
%   6. compile via GCC → executable

    fprintf('[MATLAB] Build script V2 started\n');
    fprintf('[MATLAB] Task file: %s\n', task_file);

    try
        fid = fopen(task_file, 'r');
        task_json = fread(fid, '*char')';
        fclose(fid);
        task = jsondecode(task_json);
    catch ME
        write_result(result_file, -1, sprintf('Failed to read task: %s', ME.message));
        return;
    end

    model_name = task.model_name;
    slx_path = task.slx_path;
    output_dir = task.output_dir;
    lib_name = task.lib_name;

    fprintf('[MATLAB] Model: %s\n', model_name);
    fprintf('[MATLAB] SLX: %s\n', slx_path);
    fprintf('[MATLAB] Output: %s\n', output_dir);

    % ---- Step 0: determine script directory paths ----
    script_dir = fileparts(mfilename('fullpath'));
    if isempty(script_dir)
        script_dir = pwd;
    end
    hil_root = fullfile(fileparts(script_dir));
    c_core_src = fullfile(hil_root, 'c_core', 'src');

    % ---- Step 1: analyze model ----
    fprintf('[MATLAB] ---- Step 1: analyze_model ----\n');
    interface_json = fullfile(output_dir, [model_name '_interface.json']);
    try
        analyze_model(slx_path, interface_json);
    catch ME
        write_result(result_file, -1, sprintf('analyze_model failed: %s', ME.message));
        return;
    end

    % ---- Step 2: adapt model ----
    fprintf('[MATLAB] ---- Step 2: adapt_model ----\n');
    adapted_slx = fullfile(output_dir, [model_name '_adapted.slx']);
    adapt_dir = fullfile(fileparts(fileparts(script_dir)), 'matlab_scripts');
    if ~exist(fullfile(adapt_dir, 'adapt_model.m'), 'file')
        adapt_dir = script_dir;
    end
    addpath(adapt_dir);

    try
        adapt_result = adapt_model(slx_path, interface_json, adapted_slx);
    catch ME
        write_result(result_file, -1, sprintf('adapt_model failed: %s', ME.message));
        return;
    end

    field_mapping_json = fullfile(output_dir, 'field_mapping.json');
    if ~exist(field_mapping_json, 'file')
        write_result(result_file, -1, 'field_mapping.json not generated');
        return;
    end
    fid = fopen(field_mapping_json, 'r');
    if fid < 0
        write_result(result_file, -1, 'Cannot read field_mapping.json');
        return;
    end
    mapping_raw = fread(fid, '*char')';
    fclose(fid);
    field_mapping = jsondecode(mapping_raw);

    % Save a copy of field_mapping for the C build step (if not already there)
    dest_mapping = fullfile(output_dir, 'field_mapping.json');
    if ~strcmp(field_mapping_json, dest_mapping)
        copyfile(field_mapping_json, dest_mapping);
    end

    % Determine which SLX to build
    if adapt_result.adapted
        build_slx = adapted_slx;
        build_model = field_mapping.model_name;
        fprintf('[MATLAB] Building ADAPTED model: %s\n', build_model);
    else
        build_slx = slx_path;
        build_model = model_name;
        fprintf('[MATLAB] Building ORIGINAL model (already has interface)\n');
    end

    % ---- Step 3: load & configure ERT ----
    fprintf('[MATLAB] ---- Step 3: ERT configuration ----\n');
    try
        load_system(build_slx);
        % Never leave a modified model open when this noninteractive build
        % exits, otherwise MATLAB prompts for a save and blocks the test.
        model_cleanup = onCleanup(@() close_model_without_save(build_model));
        fprintf('[MATLAB] Model loaded: %s\n', build_model);
    catch ME
        write_result(result_file, -1, sprintf('Failed to load model: %s', ME.message));
        return;
    end

    try
        codegen_cache_dir = fullfile(output_dir, 'slcache');
        Simulink.fileGenControl('set', ...
            'CacheFolder', codegen_cache_dir, ...
            'CodeGenFolder', output_dir, ...
            'CodeGenFolderStructure', ...
                Simulink.filegen.CodeGenFolderStructure.ModelSpecific, ...
            'createDir', true);
        set_param(build_model, 'SystemTargetFile', 'ert.tlc');
        set_param(build_model, 'TargetLang', 'C');
        set_param(build_model, 'GenerateComments', 'on');
        set_param(build_model, 'GenerateReport', 'on');
        % GenCodeOnly is the R2018b name; GenerateCodeOnly appeared in R2019a
        try
            set_param(build_model, 'GenerateCodeOnly', 'on');
        catch
            set_param(build_model, 'GenCodeOnly', 'on');
        end
        set_param(build_model, 'SolverType', 'Fixed-step');
        set_param(build_model, 'Solver', 'FixedStepDiscrete');
        set_param(build_model, 'FixedStep', '0.001');
        set_param(build_model, 'CodeInterfacePackaging', 'Nonreusable function');
        fprintf('[MATLAB] ERT configured\n');
    catch ME
        write_result(result_file, -1, sprintf('Config failed: %s', ME.message));
        return;
    end

    % ---- Step 4: generate C code ----
    fprintf('[MATLAB] ---- Step 4: Code generation ----\n');
    try
        v = version('-release');
        ver_num = str2double(v(2:5));
        if ver_num >= 2019
            cfg = coder.config('lib');
            cfg.GenCodeOnly = true;
            cfg.TargetLang = 'C';
            slbuild(build_model, cfg);
        else
            rtwbuild(build_model);
        end
        fprintf('[MATLAB] Code generated\n');
    catch ME
        write_result(result_file, -1, sprintf('Code generation failed: %s', ME.message));
        return;
    end

    % ---- Step 5: locate generated code ----
    % Do not infer the folder from pwd or a user preference.  ERT reports
    % the exact build directory through RTW.getBuildDir after a successful build.
    try
        build_dir_info = RTW.getBuildDir(build_model);
        code_dir = build_dir_info.BuildDirectory;
    catch ME
        write_result(result_file, -1, ...
            sprintf('Cannot determine generated code directory: %s', ME.message));
        return;
    end
    if ~exist(code_dir, 'dir')
        write_result(result_file, -1, ...
            sprintf('Generated code directory not found: %s', code_dir));
        return;
    end
    fprintf('[MATLAB] Code directory: %s\n', code_dir);

    % ---- Step 6: parse generated types → model_mapping.h ----
    fprintf('[MATLAB] ---- Step 5: Generate model_mapping.h ----\n');
    model_h = fullfile(code_dir, [build_model '.h']);
    if ~exist(model_h, 'file')
        write_result(result_file, -1, 'Generated model header not found');
        return;
    end

    [u_type, y_type] = find_ert_io_types(model_h);
    if isempty(u_type) || isempty(y_type)
        write_result(result_file, -1, ...
            'Cannot discover ERT ExtU/ExtY ABI from generated model header');
        return;
    end
    if struct_has_array_field(model_h, u_type) || struct_has_array_field(model_h, y_type)
        write_result(result_file, -1, ...
            'HIL contract supports scalar root Inport/Outport fields only');
        return;
    end
    if struct_has_unsupported_scalar_type(model_h, u_type) || ...
            struct_has_unsupported_scalar_type(model_h, y_type)
        write_result(result_file, -1, ...
            'HIL contract supports numeric and boolean root Inport/Outport fields only');
        return;
    end
    u_fields = parse_struct_fields(model_h, u_type);
    y_fields = parse_struct_fields(model_h, y_type);
    if isempty(u_fields) || isempty(y_fields)
        write_result(result_file, -1, ...
            'ERT ABI has empty or unsupported external input/output structs');
        return;
    end

    fprintf('[MATLAB] ModelU_t fields (%d): %s\n', ...
        length(u_fields), strjoin(u_fields, ', '));
    fprintf('[MATLAB] ModelY_t fields (%d): %s\n', ...
        length(y_fields), strjoin(y_fields, ', '));

    % Write model_mapping.h
    mapping_h = fullfile(code_dir, 'model_mapping.h');
    fid = fopen(mapping_h, 'w');
    fprintf(fid, '/* Auto-generated by build_script.m V2 */\n');
    fprintf(fid, '/* Model: %s */\n', build_model);
    fprintf(fid, '#ifndef MODEL_MAPPING_H\n');
    fprintf(fid, '#define MODEL_MAPPING_H\n\n');

    % --- Input field mapping (standard → model-specific) ---
    %   Maps standard names (cmd_x, etc.) → actual ERT-generated field names
    %   tunable_params lists ALL Inports so every one is reachable via UDP JSON
    std_inputs = field_mapping.inputs;
    std_input_names = fieldnames(std_inputs);

    % merge tunable_params (model-specific params without standard name)
    extra_tunable = struct();
    if isfield(field_mapping, 'tunable_params')
        tp = field_mapping.tunable_params;
        tp_names = fieldnames(tp);
        for ti = 1:length(tp_names)
            tn = tp_names{ti};
            if ~isfield(std_inputs, tn) && ~any(strcmp(std_input_names, tn))
                % Check this param name exists in u_fields
                for j = 1:length(u_fields)
                    if strcmp(u_fields{j}, tn)
                        extra_tunable.(tn) = tn;  % name is its own standard name
                        break;
                    end
                end
            end
        end
    end
    all_input_names = [std_input_names; fieldnames(extra_tunable)'];

    fprintf(fid, '/* ---- ModelU_t field mapping ---- */\n');
    fprintf(fid, '/* Standard name → actual field name */\n');
    for i = 1:length(all_input_names)
        std_name = all_input_names{i};
        % prefer standard name, fallback to raw name
        if isfield(std_inputs, std_name)
            actual_name = std_inputs.(std_name);
        else
            actual_name = extra_tunable.(std_name);
        end
        % Check actual_name exists in u_fields
        found = false;
        for j = 1:length(u_fields)
            if strcmp(u_fields{j}, actual_name)
                found = true; break;
            end
        end
        if found
            clean_name = matlab.lang.makeValidName(std_name);
            fprintf(fid, '#define MODEL_U_%s %s\n', clean_name, actual_name);
            fprintf(fid, '#define HAS_U_%s 1\n', clean_name);
        else
            clean_name = matlab.lang.makeValidName(std_name);
            fprintf(fid, '/* #define MODEL_U_%s NOT_PRESENT */\n', clean_name);
            fprintf(fid, '#define HAS_U_%s 0\n', clean_name);
        end
    end

    fprintf(fid, '/* ---- ModelU_t ALL fields (including model-specific tunables) ---- */\n');
    % Also emit ALL u_fields as tunable, regardless of mapping
    for j = 1:length(u_fields)
        fn = matlab.lang.makeValidName(u_fields{j});
        % skip if already covered via all_input_names
        already_covered = false;
        for ai = 1:length(all_input_names)
            if strcmp(fn, matlab.lang.makeValidName(all_input_names{ai}))
                already_covered = true; break;
            end
        end
        if ~already_covered
            fprintf(fid, '#define MODEL_U_%s %s\n', fn, u_fields{j});
            fprintf(fid, '#define HAS_U_%s 1\n', fn);
            % also add to all_input_names so model_config picks it up
            all_input_names{end+1} = u_fields{j};
        end
    end

    fprintf(fid, '\n/* ---- Safe standard input writers ---- */\n');
    for i = 1:length(std_input_names)
        std_name = std_input_names{i};
        actual_name = std_inputs.(std_name);
        found = any(strcmp(u_fields, actual_name));
        clean_name = matlab.lang.makeValidName(std_name);
        if found
            fprintf(fid, '#define MODEL_WRITE_%s(u_ptr, value) do { (u_ptr)->%s = (value); } while (0)\n', ...
                clean_name, actual_name);
        else
            fprintf(fid, '#define MODEL_WRITE_%s(u_ptr, value) do { (void)(u_ptr); (void)(value); } while (0)\n', ...
                clean_name);
        end
    end

    fprintf(fid, '\n/* ---- ModelY_t field mapping ---- */\n');
    fprintf(fid, '/* Standard name → actual field name */\n');
    std_outputs = field_mapping.outputs;
    std_output_names = fieldnames(std_outputs);
    for i = 1:length(std_output_names)
        std_name = std_output_names{i};
        actual_name = std_outputs.(std_name);
        found = false;
        for j = 1:length(y_fields)
            if strcmp(y_fields{j}, actual_name)
                found = true; break;
            end
        end
        if found
            clean_name = matlab.lang.makeValidName(std_name);
            fprintf(fid, '#define MODEL_Y_%s %s\n', clean_name, actual_name);
            fprintf(fid, '#define HAS_Y_%s 1\n', clean_name);
        else
            clean_name = matlab.lang.makeValidName(std_name);
            fprintf(fid, '/* #define MODEL_Y_%s NOT_PRESENT */\n', clean_name);
            fprintf(fid, '#define HAS_Y_%s 0\n', clean_name);
        end
    end

    fprintf(fid, '\n/* ---- Safe state readers: missing optional fields use defaults ---- */\n');
    reader_names = {'pos_x','pos_y','pos_z','roll','pitch','yaw', ...
                    'vel_x','vel_y','vel_z','lat','lon','alt', ...
                    'acc_x','acc_y','acc_z','airborne'};
    reader_defaults = {'0.0','0.0','0.0','0.0f','0.0f','0.0f', ...
                       '0.0f','0.0f','0.0f','39.9','116.4','100.0', ...
                       '0.0f','0.0f','0.0f','0'};
    for i = 1:length(reader_names)
        std_name = reader_names{i};
        actual_name = 'NOT_FOUND';
        if isfield(std_outputs, std_name)
            actual_name = std_outputs.(std_name);
        end
        if any(strcmp(y_fields, actual_name))
            fprintf(fid, '#define MODEL_READ_%s(y_ptr) ((y_ptr)->%s)\n', ...
                std_name, actual_name);
        else
            fprintf(fid, '#define MODEL_READ_%s(y_ptr) (%s)\n', ...
                std_name, reader_defaults{i});
        end
    end

    fprintf(fid, '\n#endif /* MODEL_MAPPING_H */\n');
    fclose(fid);
    fprintf('[MATLAB] model_mapping.h generated: %s\n', mapping_h);

    % Also write model_config.h (for main_rt.c)
    model_config_h = fullfile(code_dir, 'model_config.h');
    fid = fopen(model_config_h, 'w');
    fprintf(fid, '/* Auto-generated by build_script.m V2 */\n');
    fprintf(fid, '#ifndef MODEL_CONFIG_H\n');
    fprintf(fid, '#define MODEL_CONFIG_H\n\n');
    fprintf(fid, '#include "model_mapping.h"\n\n');
    fprintf(fid, '/* Model identity */\n');
    % Escape backslashes for C
    fprintf(fid, '#define MODEL_NAME "%s"\n', strrep(build_model, '\', '\\'));
    fprintf(fid, '#define MODEL_SLX "%s"\n', strrep(slx_path, '\', '\\'));
    fprintf(fid, '#define MODEL_ADAPTED %d\n', adapt_result.adapted);

    % Default values for optional fields
    fprintf(fid, '\n/* Defaults for optional fields */\n');
    fprintf(fid, '#define MODEL_DEFAULT_POS_X 0.0\n');
    fprintf(fid, '#define MODEL_DEFAULT_POS_Y 0.0\n');
    fprintf(fid, '#define MODEL_DEFAULT_POS_Z 10.0\n');
    fprintf(fid, '#define MODEL_DEFAULT_ROLL  0.0f\n');
    fprintf(fid, '#define MODEL_DEFAULT_PITCH 0.0f\n');
    fprintf(fid, '#define MODEL_DEFAULT_YAW   0.0f\n');

    fprintf(fid, '\n/* Runtime dispatch table — maps string key → byte offset into ModelU_t */\n');
    fprintf(fid, '#define MODEL_U_TUNABLE_COUNT %d\n', length(u_fields));
    fprintf(fid, '/* All fields: %s */\n', strjoin(u_fields, ', '));
    fprintf(fid, '#include <stddef.h>  /* for offsetof */\n');
    fprintf(fid, 'struct _tunable_entry { const char* name; size_t offset; };\n');
    fprintf(fid, 'static const struct _tunable_entry MODEL_U_TUNABLE_TABLE[] = {\n');
    for j = 1:length(u_fields)
        fn = u_fields{j};
        fprintf(fid, '    {"%s", offsetof(ModelU_t, %s)},\n', fn, fn);
    end
    fprintf(fid, '};\n');

    fprintf(fid, '\n#endif /* MODEL_CONFIG_H */\n');
    fclose(fid);

    % ---- Step 7: bridge header ----
    fprintf('[MATLAB] ---- Step 6: Bridge header ----\n');
    bridge_h = fullfile(code_dir, 'model_rt_bridge.h');
    fid = fopen(bridge_h, 'w');
    fprintf(fid, '/* Auto-generated by build_script.m V2 */\n');
    fprintf(fid, '#ifndef HIL_MODEL_RT_BRIDGE_GENERATED_H\n');
    fprintf(fid, '#define HIL_MODEL_RT_BRIDGE_GENERATED_H\n\n');
    fprintf(fid, '#include "%s.h"\n\n', build_model);
    fprintf(fid, 'typedef %s ModelU_t;\n', u_type);
    fprintf(fid, '#define MODEL_U_T_DEFINED 1\n');
    fprintf(fid, 'typedef %s ModelY_t;\n\n', y_type);
    fprintf(fid, '#define MODEL_Y_T_DEFINED 1\n\n');
    fprintf(fid, '#define MODEL_INIT_FN  %s_initialize\n', build_model);
    fprintf(fid, '#define MODEL_STEP_FN  %s_step\n', build_model);
    fprintf(fid, '#define MODEL_TERM_FN  %s_terminate\n', build_model);
    fprintf(fid, '#define MODEL_U_VAR    %s_U\n', build_model);
    fprintf(fid, '#define MODEL_Y_VAR    %s_Y\n\n', build_model);
    fprintf(fid, '#endif\n');
    fclose(fid);
    fprintf('[MATLAB] Bridge header: %s\n', bridge_h);

    % ---- Step 8: compile ----
    fprintf('[MATLAB] ---- Step 7: GCC compile ----\n');
    try
        c_files = dir(fullfile(code_dir, '*.c'));
        if isempty(c_files)
            error('No C files found in %s', code_dir);
        end

        exe_dir = fullfile(fileparts(output_dir), 'executables');
        if ~exist(exe_dir, 'dir')
            mkdir(exe_dir);
        end
        exe_path = fullfile(exe_dir, [model_name '_rt']);

        cmd = sprintf(['gcc -O2 -Wall -pthread ' ...
                       '-I"%s" -I"%s" ' ...
                       '-DMODEL_RT_BRIDGE_HEADER=\\"%s\\" ' ...
                       '%s "%s/main_rt.c" ' ...
                       '"%s/model_rt_wrapper.c" ' ...
                       '"%s/local_udp.c" ' ...
                       '"%s/hal_stub.c" ' ...
                       '-lm -lrt -ljson-c -lpthread ' ...
                       '-o "%s"'], ...
            code_dir, c_core_src, bridge_h, ...
            gen_c_flags(code_dir, c_files), c_core_src, ...
            c_core_src, c_core_src, c_core_src, exe_path);

        % On Windows (dev), skip -lrt
        if ispc
            cmd = strrep(cmd, '-lrt', '');
        end

        fprintf('[MATLAB] Compiling:\n%s\n', cmd);
        [status, output] = system(cmd);
        if status ~= 0
            error('Compile failed: %s', output);
        end
        fprintf('[MATLAB] Executable: %s\n', exe_path);
    catch ME
        write_result(result_file, -1, sprintf('Compile failed: %s', ME.message));
        return;
    end

    % ---- Done ----
    result = struct('code', 0, 'message', 'Build successful', ...
                    'exe_path', exe_path, 'model_name', model_name, ...
                    'adapted', adapt_result.adapted, ...
                    'timestamp', datestr(now, 'yyyy-mm-dd HH:MM:SS'));
    write_result_json(result_file, result);
    fprintf('[MATLAB] Build complete\n');
end

% ---- Helpers ----

function [u_type, y_type] = find_ert_io_types(header_path)
%FIND_ERT_IO_TYPES Locate default ERT external I/O struct typedefs.
% R2018b ERT names these ExtU_* and ExtY_*; the model short name is part
% of the generated identifier and must not be guessed by the caller.
    u_type = '';
    y_type = '';
    fid = fopen(header_path, 'r');
    if fid < 0
        return;
    end
    content = fread(fid, '*char')';
    fclose(fid);

    u_match = regexp(content, ...
        'typedef\s+struct\s*\{[\s\S]*?\}\s*(ExtU[A-Za-z0-9_]*)\s*;', ...
        'tokens', 'once');
    y_match = regexp(content, ...
        'typedef\s+struct\s*\{[\s\S]*?\}\s*(ExtY[A-Za-z0-9_]*)\s*;', ...
        'tokens', 'once');
    if ~isempty(u_match)
        u_type = u_match{1};
    end
    if ~isempty(y_match)
        y_type = y_match{1};
    end
end

function found = struct_has_array_field(header_path, struct_name)
%STRUCT_HAS_ARRAY_FIELD Reject vector and matrix root I/O before C binding.
    found = false;
    fid = fopen(header_path, 'r');
    if fid < 0
        return;
    end
    content = fread(fid, '*char')';
    fclose(fid);
    pattern = ['typedef\s+struct\s*\{([\s\S]*?)\}\s*' struct_name '\s*;'];
    tokens = regexp(content, pattern, 'tokens', 'once');
    if ~isempty(tokens)
        found = ~isempty(regexp(tokens{1}, '\[[^\]]+\]', 'once'));
    end
end

function found = struct_has_unsupported_scalar_type(header_path, struct_name)
%STRUCT_HAS_UNSUPPORTED_SCALAR_TYPE Reject Bus/enum/fixed-point I/O fields.
    found = false;
    fid = fopen(header_path, 'r');
    if fid < 0
        return;
    end
    content = fread(fid, '*char')';
    fclose(fid);
    pattern = ['typedef\s+struct\s*\{([\s\S]*?)\}\s*' struct_name '\s*;'];
    tokens = regexp(content, pattern, 'tokens', 'once');
    if isempty(tokens)
        found = true;
        return;
    end
    declarations = regexp(tokens{1}, ...
        '^\s*([A-Za-z_][A-Za-z0-9_]*)\s+[A-Za-z_][A-Za-z0-9_]*\s*;', ...
        'tokens', 'lineanchors');
    allowed = {'real_T','real32_T','real64_T','boolean_T', ...
               'int8_T','uint8_T','int16_T','uint16_T','int32_T','uint32_T', ...
               'int64_T','uint64_T','int_T','uint_T','float','double', ...
               'int','unsigned','signed','char','short','long'};
    for i = 1:length(declarations)
        if ~ismember(declarations{i}{1}, allowed)
            found = true;
            return;
        end
    end
end

function fields = parse_struct_fields(header_path, struct_name)
%PARSE_STRUCT_FIELDS Extract field names from a C struct definition
    fields = {};
    if ~exist(header_path, 'file')
        return;
    end
    fid = fopen(header_path, 'r');
    if fid < 0
        return;
    end
    content = fread(fid, '*char')';
    fclose(fid);

    % Find the struct body: typedef struct { ... } StructName;
    pattern = sprintf('typedef%sstruct%s\\{[^}]*\\}\\s*%s;', ...
        '\s+', '\s+', struct_name);
    match = regexp(content, pattern, 'match', 'dotexceptnewline');
    if isempty(match)
        % Try without typedef
        pattern = sprintf('struct%s\\{[^}]*\\}\\s*%s;', '\s+', struct_name);
        match = regexp(content, pattern, 'match', 'dotexceptnewline');
    end
    if isempty(match)
        % For ERT: sometimes the struct is typedef struct { ... } name_t ;
        % with line breaks. Try simpler: find line with "} name_t;"
        lines = strsplit(content, '\n');
        in_struct = false;
        for i = 1:length(lines)
            line = strtrim(lines{i});
            if startsWith(line, 'typedef struct') || startsWith(line, 'struct')
                % Look for struct name in this or near lines
                if contains(line, struct_name)
                    in_struct = true;
                    continue;
                end
            end
            if in_struct
                % Extract field declarations: "type name;" or "type name1, name2;"
                if contains(line, ';') && ~contains(line, '}') && ~startsWith(line, '/*') && ~startsWith(line, '//')
                    % Strip comments
                    comment_pos = strfind(line, '//');
                    if ~isempty(comment_pos)
                        line = strtrim(line(1:comment_pos-1));
                    end
                    % Get identifiers after type
                    % Simple: split by ';' then take last word before ';'
                    parts = strsplit(line, ';');
                    for p = 1:length(parts)
                        part = strtrim(parts{p});
                        if isempty(part) || startsWith(part, '/*')
                            continue;
                        end
                        % "type name" → take "name"
                        tokens = strsplit(part);
                        for t = length(tokens):-1:1
                            token = tokens{t};
                            % skip C keywords and types
                            if ~ismember(token, {'struct','const','volatile', ...
                                    'double','float','int','char','short','long', ...
                                    'uint8_t','uint16_t','uint32_t','uint64_t', ...
                                    'int8_t','int16_t','int32_t','int64_t', ...
                                    'real_T','real32_T','boolean_T','char_T', ...
                                    'int_T','uint_T','byte_T','real64_T'})
                                fields{end+1} = token;
                                break;
                            end
                        end
                    end
                end
                if contains(line, ['} ' struct_name ';']) || contains(line, ['}' struct_name ';'])
                    break;
                end
            end
        end
        return;
    end

    body = match{1};
    % Extract the part between { and }
    brace_start = strfind(body, '{');
    brace_end = strfind(body, '}');
    if isempty(brace_start) || isempty(brace_end)
        return;
    end
    inner = body(brace_start(1)+1 : brace_end(end)-1);

    % Parse field declarations: lines ending with ;
    lines = strsplit(inner, ';');
    for i = 1:length(lines)
        line = strtrim(lines{i});
        if isempty(line) || startsWith(line, '/*') || startsWith(line, '//')
            continue;
        end
        % Strip inline comments
        comment_pos = strfind(line, '//');
        if ~isempty(comment_pos)
            line = strtrim(line(1:comment_pos-1));
        end
        if isempty(line), continue; end
        % Get field name (last token)
        tokens = strsplit(line);
        if ~isempty(tokens)
            fields{end+1} = tokens{end};
        end
    end
end

function flags = gen_c_flags(code_dir, c_files)
    flags = '';
    for i = 1:length(c_files)
        flags = [flags ' "' fullfile(code_dir, c_files(i).name) '"'];
    end
end

function write_result_json(filename, data)
    fid = fopen(filename, 'w');
    fprintf(fid, '%s', jsonencode(data));
    fclose(fid);
end

function write_result(filename, code, message)
    data = struct('code', code, 'message', message);
    write_result_json(filename, data);
end

function close_model_without_save(model_name)
%CLOSE_MODEL_WITHOUT_SAVE Avoid interactive save prompts in batch MATLAB.
    try
        if bdIsLoaded(model_name)
            close_system(model_name, 0);
        end
    catch
        % The build result has already been written; never mask it during cleanup.
    end
end
